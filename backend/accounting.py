import json
from datetime import date, datetime
from decimal import Decimal


AUDITED_TABLES = ("holdings", "options", "closed_trades", "closed_options", "transactions")


def install_audit_schema(conn, postgres=False):
    cursor = conn.cursor()
    identity = "BIGSERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS accounting_events (
            id {identity},
            user_id INTEGER NOT NULL REFERENCES users(id),
            source TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            operation TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounting_user ON accounting_events(user_id, id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounting_source ON accounting_events(source, source_id)")
    if postgres:
        cursor.execute("ALTER TABLE accounting_events ADD COLUMN IF NOT EXISTS idempotency_key TEXT")
        cursor.execute("ALTER TABLE accounting_events ENABLE ROW LEVEL SECURITY")
        for role in ("anon", "authenticated"):
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
            if cursor.fetchone():
                cursor.execute(f"REVOKE ALL ON accounting_events FROM {role}")
    elif "idempotency_key" not in [row[1] for row in cursor.execute("PRAGMA table_info(accounting_events)").fetchall()]:
        cursor.execute("ALTER TABLE accounting_events ADD COLUMN idempotency_key TEXT")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounting_request ON accounting_events(user_id, idempotency_key)")
    cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_accounting_reversal
        ON accounting_events(user_id, source_id) WHERE source='manual' AND operation='REVERSE'""")
    for table, columns in {"closed_trades": {"source_lot_id": "INTEGER", "acquired_at": "TEXT"},
                           "closed_options": {"source_lot_id": "INTEGER"}}.items():
        for column, datatype in columns.items():
            if postgres:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {datatype}")
            elif column not in [row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()]:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {datatype}")
    if postgres:
        cursor.execute("""
            CREATE OR REPLACE FUNCTION stockpilot_audit_capture() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    INSERT INTO accounting_events(user_id, source, source_id, operation, before_json)
                    VALUES (OLD.user_id, TG_TABLE_NAME, OLD.id, TG_OP, to_jsonb(OLD)::text);
                    RETURN OLD;
                ELSIF TG_OP = 'UPDATE' THEN
                    INSERT INTO accounting_events(user_id, source, source_id, operation, before_json, after_json)
                    VALUES (NEW.user_id, TG_TABLE_NAME, NEW.id, TG_OP, to_jsonb(OLD)::text, to_jsonb(NEW)::text);
                ELSE
                    INSERT INTO accounting_events(user_id, source, source_id, operation, after_json)
                    VALUES (NEW.user_id, TG_TABLE_NAME, NEW.id, TG_OP, to_jsonb(NEW)::text);
                END IF;
                RETURN NEW;
            END; $$
        """)
        cursor.execute("""
            CREATE OR REPLACE FUNCTION stockpilot_audit_immutable() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Accounting events are append-only';
            END; $$
        """)
        cursor.execute("DROP TRIGGER IF EXISTS accounting_events_immutable ON accounting_events")
        cursor.execute("""CREATE TRIGGER accounting_events_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
            ON accounting_events FOR EACH STATEMENT EXECUTE FUNCTION stockpilot_audit_immutable()""")
    else:
        for operation in ("UPDATE", "DELETE"):
            cursor.execute(f"""CREATE TRIGGER IF NOT EXISTS accounting_events_no_{operation.lower()}
                BEFORE {operation} ON accounting_events BEGIN
                SELECT RAISE(ABORT, 'Accounting events are append-only'); END""")
    for table in AUDITED_TABLES:
        if postgres:
            snapshot = "to_jsonb(original)::text"
        else:
            columns = [row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
            snapshot = "json_object(" + ", ".join(f"'{column}', original.{column}" for column in columns) + ")"
        cursor.execute(f"""INSERT INTO accounting_events(user_id, source, source_id, operation, after_json)
            SELECT original.user_id, '{table}', original.id, 'SNAPSHOT', {snapshot} FROM {table} original
            WHERE NOT EXISTS (SELECT 1 FROM accounting_events event
                WHERE event.source = '{table}' AND event.source_id = original.id)""")
        if postgres:
            cursor.execute(f"DROP TRIGGER IF EXISTS stockpilot_audit ON {table}")
            cursor.execute(f"""CREATE TRIGGER stockpilot_audit AFTER INSERT OR UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION stockpilot_audit_capture()""")
        else:
            for operation in ("INSERT", "UPDATE", "DELETE"):
                before = snapshot.replace("original.", "OLD.") if operation != "INSERT" else "NULL"
                after = snapshot.replace("original.", "NEW.") if operation != "DELETE" else "NULL"
                row = "OLD" if operation == "DELETE" else "NEW"
                cursor.execute(f"DROP TRIGGER IF EXISTS audit_{table}_{operation.lower()}")
                cursor.execute(f"""CREATE TRIGGER IF NOT EXISTS audit_{table}_{operation.lower()}
                    AFTER {operation} ON {table} BEGIN
                    INSERT INTO accounting_events(user_id, source, source_id, operation, before_json, after_json)
                    VALUES ({row}.user_id, '{table}', {row}.id, '{operation}', {before}, {after}); END""")


def list_events(user_id, after_id=0, limit=200):
    import database
    if after_id < 0 or not 1 <= limit <= 1000:
        raise ValueError("Invalid ledger page")
    rows = database._run(
        f"SELECT * FROM accounting_events WHERE user_id={database.PH} AND id>{database.PH} ORDER BY id LIMIT {database.PH}",
        (user_id, after_id, limit), fetch="all",
    )
    for row in rows:
        row["before"] = json.loads(row.pop("before_json") or "null")
        row["after"] = json.loads(row.pop("after_json") or "null")
    return rows


def _active_manual(events):
    reversed_ids = {event["source_id"] for event in events if event["source"] == "manual" and event["operation"] == "REVERSE"}
    return [event for event in events if event["source"] == "manual" and event["operation"] != "REVERSE" and event["id"] not in reversed_ids]


def record_entry(user_id, request):
    import database
    from portfolio_models import AccountingEntryRequest
    request = AccountingEntryRequest.model_validate(request)
    payload = request.model_dump(mode="json")
    conn = database.get_db()
    try:
        cursor = conn.cursor()
        if database.USE_PG:
            cursor.execute(f"SELECT id FROM users WHERE id={database.PH} FOR UPDATE", (user_id,))
        else:
            cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(f"SELECT * FROM accounting_events WHERE user_id={database.PH} AND idempotency_key={database.PH}",
                       (user_id, request.idempotency_key))
        existing = database._fetchone(cursor)
        if existing:
            previous = {"exit_reason": None, "target_capture_pct": None, "account": None, **json.loads(existing["after_json"])}
            if previous != payload:
                raise ValueError("Request key already used for a different entry")
            return {"id": existing["id"]}
        target = None
        if request.event_id is not None:
            cursor.execute(f"SELECT * FROM accounting_events WHERE user_id={database.PH} AND id={database.PH}", (user_id, request.event_id))
            target = database._fetchone(cursor)
            if not target:
                raise ValueError("Referenced ledger event not found")
        if request.kind in {"link", "reverse", "review"} and target is None:
            raise ValueError("Select a ledger event")
        if request.kind == "reverse":
            if target["source"] != "manual" or target["operation"] == "REVERSE":
                raise ValueError("Only manual entries can be reversed; correct trade records through their owning workflow")
            cursor.execute(f"SELECT id FROM accounting_events WHERE user_id={database.PH} AND source='manual' AND operation='REVERSE' AND source_id={database.PH}", (user_id, request.event_id))
            if database._fetchone(cursor):
                raise ValueError("Entry already reversed")
        elif request.kind == "review":
            if target["source"] not in {"closed_trades", "closed_options"} or target["operation"] not in {"INSERT", "SNAPSHOT"}:
                raise ValueError("Review a recorded closed trade")
            cursor.execute(f"SELECT * FROM {target['source']} WHERE user_id={database.PH} AND id={database.PH}",
                           (user_id, target["source_id"]))
            trade = database._fetchone(cursor)
            if not trade:
                raise ValueError("Closed trade no longer exists")
            if request.target_capture_pct is not None and (target["source"] != "closed_options" or trade["position"] != "short"):
                raise ValueError("Capture targets apply only to short options")
        elif request.kind == "link":
            if target["source"] not in {"holdings", "options", "closed_trades", "closed_options"} or target["operation"] not in {"INSERT", "SNAPSHOT"}:
                raise ValueError("Link an opening lot or a closed trade")
            if not request.cycle or not request.cycle.strip() or request.quantity is None:
                raise ValueError("A cycle name and allocated quantity are required")
            cursor.execute(f"SELECT * FROM {target['source']} WHERE user_id={database.PH} AND id={database.PH}",
                           (user_id, target["source_id"]))
            target_data = database._fetchone(cursor)
            if not target_data:
                raise ValueError("The linked lot or trade no longer exists")
            quantity = Decimal(str(target_data.get("shares", target_data.get("contracts"))))
            if target["source"] in {"options", "closed_options"} and request.quantity != request.quantity.to_integral_value():
                raise ValueError("Option allocations must be whole contracts")
            cursor.execute(f"SELECT * FROM accounting_events WHERE user_id={database.PH} AND source='manual'", (user_id,))
            prior = database._fetchall(cursor)
            allocated = sum((Decimal(json.loads(event["after_json"])["quantity"]) for event in _active_manual(prior)
                             if event["operation"] == "LINK" and json.loads(event["after_json"])["event_id"] == request.event_id), Decimal("0"))
            if request.quantity + allocated > quantity:
                raise ValueError("Cycle allocation exceeds this lot's quantity")
        elif request.amount <= 0 and request.kind != "valuation":
            raise ValueError("Amount must be positive")
        if request.kind == "fee" and target and (target["source"] not in {"holdings", "options", "closed_trades", "closed_options"}
                               or target["operation"] not in {"INSERT", "SNAPSHOT"}):
            raise ValueError("Attach fees to a lot or closed trade")
        if request.kind == "withdrawal" and request.nav_before is not None and request.amount > request.nav_before:
            raise ValueError("Withdrawal exceeds the recorded pre-flow NAV")
        cursor.execute(f"""INSERT INTO accounting_events(user_id, source, source_id, operation, after_json, idempotency_key)
            VALUES ({database.PH}, 'manual', {database.PH}, {database.PH}, {database.PH}, {database.PH})"""
            + (" RETURNING id" if database.USE_PG else ""),
            (user_id, request.event_id if request.kind == "reverse" else 0, request.kind.upper(), json.dumps(payload), request.idempotency_key))
        result_id = database._fetchone(cursor)["id"] if database.USE_PG else cursor.lastrowid
        conn.commit()
        return {"id": result_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        database._release(conn)


def time_weighted_return(entries):
    ordered = sorted(entries, key=lambda entry: (datetime.fromisoformat(entry["occurred_at"].replace("Z", "+00:00")), entry["id"]))
    baseline = None
    factor = Decimal("1")
    observations = 0
    last_kind = None
    for entry in ordered:
        kind = entry["kind"]
        if kind not in {"valuation", "deposit", "withdrawal"}:
            continue
        amount = Decimal(str(entry["amount"]))
        if kind == "valuation":
            if amount < 0:
                return {"pct": None, "reason": "Negative NAV requires separate review"}
            if baseline is not None:
                if baseline <= 0:
                    return {"pct": None, "reason": "A new return period is required after zero NAV"}
                factor *= amount / baseline
                observations += 1
            baseline = amount
        elif baseline is not None:
            if entry.get("nav_before") is None:
                return {"pct": None, "reason": "A cash flow is missing its immediately preceding NAV"}
            before = Decimal(str(entry["nav_before"]))
            if before <= 0:
                return {"pct": None, "reason": "NAV must remain positive"}
            factor *= before / baseline
            baseline = before + (amount if kind == "deposit" else -amount)
            if baseline <= 0:
                return {"pct": None, "reason": "NAV must remain positive after cash flows"}
        last_kind = kind
    if observations == 0 or last_kind != "valuation":
        return {"pct": None, "reason": "Opening and ending account valuations are required"}
    return {"pct": round(float((factor - 1) * 100), 4), "reason": None}


def report(user_id):
    import database
    rows = database._run(f"SELECT * FROM accounting_events WHERE user_id={database.PH} ORDER BY id", (user_id,), fetch="all")
    events = {row["id"]: row for row in rows}
    manual = [{**json.loads(row["after_json"]), "id": row["id"]} for row in _active_manual(rows)]
    reviews = {}
    for entry in manual:
        if entry["kind"] == "review":
            target = events.get(entry["event_id"])
            if target:
                reviews[(target["source"], target["source_id"])] = {
                    "review_id": entry["id"], "exit_reason": entry.get("exit_reason"),
                    "target_capture_pct": float(entry["target_capture_pct"]) if entry.get("target_capture_pct") is not None else None,
                    "review_note": entry["note"], "review_recorded_at": events[entry["id"]]["recorded_at"],
                }
    fees = {}
    for entry in manual:
        if entry["kind"] == "fee":
            fees[entry["event_id"]] = fees.get(entry["event_id"], Decimal("0")) + Decimal(entry["amount"])
    latest = {}
    for event in rows:
        if event["source"] in AUDITED_TABLES:
            latest[(event["source"], event["source_id"])] = event
    tax_rows = []
    allocated_opening_fees = {}
    for (source, source_id), event in latest.items():
        if source not in {"closed_trades", "closed_options"} or event["operation"] == "DELETE":
            continue
        trade = json.loads(event["after_json"])
        source_events = [row for row in rows if row["source"] == source and row["source_id"] == source_id]
        closing_fees = sum((fees.get(row["id"], Decimal("0")) for row in source_events), Decimal("0"))
        opening_source = "holdings" if source == "closed_trades" else "options"
        quantity = Decimal(str(trade.get("shares", trade.get("contracts"))))
        opening_fees = Decimal("0")
        for row in rows:
            if row["source"] == opening_source and row["source_id"] == trade.get("source_lot_id") and row["operation"] in {"INSERT", "SNAPSHOT"}:
                lot = json.loads(row["after_json"])
                lot_quantity = Decimal(str(lot.get("shares", lot.get("contracts"))))
                if lot_quantity <= 0:
                    continue
                original_fee = fees.get(row["id"], Decimal("0"))
                used_quantity, used_fee = allocated_opening_fees.get(row["id"], (Decimal("0"), Decimal("0")))
                remainder = original_fee - used_fee
                portion = remainder if used_quantity + quantity >= lot_quantity else (original_fee * quantity / lot_quantity).quantize(Decimal("0.01"))
                portion = max(Decimal("0"), min(portion, remainder))
                allocated_opening_fees[row["id"]] = (used_quantity + quantity, used_fee + portion)
                opening_fees += portion
        total_fees = opening_fees + closing_fees
        acquired = trade.get("acquired_at") if source == "closed_trades" else trade.get("opened_at")
        sold = str(trade.get("closed_at") or trade.get("date_closed") or "")[:10]
        term = "review"
        if acquired and sold:
            start, end = date.fromisoformat(str(acquired)[:10]), date.fromisoformat(sold)
            anniversary = start.replace(year=start.year + 1, day=min(start.day, 28) if start.month == 2 else start.day)
            term = "long" if end > anniversary else "short"
        if source == "closed_trades":
            basis = Decimal(str(trade["buy_price"])) * quantity + opening_fees
            proceeds = Decimal(str(trade["sell_price"])) * quantity - closing_fees
        else:
            opened = Decimal(str(trade["open_premium"])) * quantity * 100
            closed = Decimal(str(trade["close_premium"])) * quantity * 100
            basis, proceeds = (opened + opening_fees, closed - closing_fees) if trade["position"] == "long" else (closed + closing_fees, opened - opening_fees)
            term = "review"
        opening_event = next((row["id"] for row in source_events if row["operation"] in {"INSERT", "SNAPSHOT"}), None)
        tax_rows.append({"event_id": event["id"], "opening_event_id": opening_event,
                 "source": source, "source_id": source_id, "ticker": trade["ticker"], "quantity": float(quantity),
                 "option_type": trade.get("option_type"), "position": trade.get("position"),
                 "gross_pnl": trade["pnl"], "review": reviews.get((source, source_id)),
                         "acquired_at": acquired, "closed_at": sold, "term": term,
                         "basis": round(float(basis), 2), "proceeds": round(float(proceeds), 2),
                         "fees": round(float(total_fees), 2), "gain": round(float(proceeds - basis), 2)})
    cycles = {}
    for entry in manual:
        if entry["kind"] != "link":
            continue
        target = events.get(entry["event_id"])
        if not target:
            continue
        cycle = cycles.setdefault(entry["cycle"], {"name": entry["cycle"], "links": [], "realized_pnl": 0.0,
            "put_pnl": Decimal("0"), "call_pnl": Decimal("0"), "stock_pnl": Decimal("0"), "fees": Decimal("0"),
            "unresolved_links": 0, "open_links": 0})
        target_data = json.loads(target["after_json"])
        current = latest.get((target["source"], target["source_id"]))
        link = {"link_id": entry["id"], "event_id": target["id"], "source": target["source"],
                "ticker": target_data["ticker"], "quantity": entry["quantity"], "status": "unresolved"}
        cycle["links"].append(link)
        if current and current["operation"] != "DELETE":
            current_data = json.loads(current["after_json"])
            link["ticker"] = current_data["ticker"]
            allocated = sum((Decimal(other["quantity"]) for other in manual if other["kind"] == "link"
                             and other["event_id"] == entry["event_id"]), Decimal("0"))
            available = Decimal(str(current_data.get("shares", current_data.get("contracts"))))
            if allocated <= available and target["source"] in {"holdings", "options"}:
                link["status"] = "open"
                cycle["open_links"] += 1
            elif allocated <= available:
                trade = next((trade for trade in tax_rows if trade["source"] == target["source"] and trade["source_id"] == target["source_id"]), None)
                if trade:
                    portion = Decimal(entry["quantity"]) / Decimal(str(trade["quantity"]))
                    component = "stock_pnl" if trade["source"] == "closed_trades" else "put_pnl" if trade["option_type"] == "put" else "call_pnl"
                    cycle[component] += Decimal(str(trade["gross_pnl"])) * portion
                    cycle["fees"] += Decimal(str(trade["fees"])) * portion
                    link["status"] = "realized"
        if link["status"] == "unresolved":
            cycle["unresolved_links"] += 1
    for cycle in cycles.values():
        for component in ("put_pnl", "call_pnl", "stock_pnl", "fees"):
            cycle[component] = round(float(cycle[component]), 2)
        cycle["realized_pnl"] = round(cycle["put_pnl"] + cycle["call_pnl"] + cycle["stock_pnl"] - cycle["fees"], 2)
    combined_histories = any(row["source"] == "account_transfer" and json.loads(row["after_json"]).get("combined_histories") for row in rows)
    twr = {"pct": None, "reason": "Transferred account histories are combined; valuations are not consolidated total-account NAV"} if combined_histories else time_weighted_return(manual)
    return {"manual_entries": manual, "tax_lots": tax_rows, "cycles": list(cycles.values()),
            "fees": round(float(sum(fees.values(), Decimal("0"))), 2),
            "external_cash_flow": round(sum(float(entry["amount"]) * (1 if entry["kind"] == "deposit" else -1)
                                             for entry in manual if entry["kind"] in {"deposit", "withdrawal"}), 2),
            "dividends": round(sum(float(entry["amount"]) for entry in manual if entry["kind"] == "dividend"), 2),
            "twr": twr, "last_event_id": rows[-1]["id"] if rows else 0,
            "has_legacy_snapshots": any(row["operation"] == "SNAPSHOT" for row in rows),
            "notes": ["US informational lot report, not a filing-ready tax return. Recorded lot selections are retained; ticker sales use FIFO.",
                      "Wash sales, corporate actions, assignment/exercise basis adjustments and option tax treatment require review.",
                      "Only recorded fees and cash flows are included. TWR uses entered total-account NAV, including cash and option liabilities.",
                      "Cycle totals include only explicitly allocated closed trades; open positions are not realized profit."]}