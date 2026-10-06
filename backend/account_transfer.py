import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import uuid4

import database
from accounting import AUDITED_TABLES
from auth import SECRET_KEY


MAX_BYTES = 10 * 1024 * 1024
COPY_TABLES = ("journal", "watchlist")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _signature(payload):
    return hmac.new(SECRET_KEY.encode(), ("stockpilot-account-transfer-v1:" + _canonical(payload)).encode(), hashlib.sha256).hexdigest()


def export_account(user_id):
    conn = database.get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" if database.USE_PG else "BEGIN")
        cursor.execute(f"SELECT id, display_name FROM users WHERE id={database.PH}", (user_id,))
        user = database._fetchone(cursor)
        if not user:
            raise ValueError("Account not found")
        cursor.execute(f"SELECT * FROM accounting_events WHERE user_id={database.PH} ORDER BY id", (user_id,))
        events = []
        combined_histories = False
        for event in database._fetchall(cursor):
            if event["source"] == "account_transfer":
                combined_histories = combined_histories or json.loads(event["after_json"]).get("combined_histories", False)
                continue
            item = {key: event[key] for key in ("id", "source", "source_id", "operation", "recorded_at")}
            for field in ("before", "after"):
                value = json.loads(event[field + "_json"] or "null")
                if isinstance(value, dict):
                    value.pop("user_id", None)
                    value.pop("idempotency_key", None)
                item[field] = value
            events.append(item)
        tables = {}
        counts = {}
        for table in (*AUDITED_TABLES, *COPY_TABLES):
            cursor.execute(f"SELECT * FROM {table} WHERE user_id={database.PH} ORDER BY id", (user_id,))
            rows = database._fetchall(cursor)
            counts[table] = len(rows)
            if table in COPY_TABLES:
                tables[table] = [{key: value for key, value in row.items() if key != "user_id"} for row in rows]
        payload = json.loads(json.dumps({"format": "stockpilot-account-transfer", "version": 1,
            "source_user_id": user_id, "source_name": user["display_name"], "events": events,
            "tables": tables, "counts": counts, "combined_histories": combined_histories}, default=str, allow_nan=False))
        encoded = _canonical(payload)
        package = {"payload": encoded, "signature": _signature(encoded), "exported_at": datetime.now(timezone.utc).isoformat()}
        if len(_canonical(package).encode()) > MAX_BYTES - 64:
            raise ValueError("Account exceeds the 10 MB transfer limit")
        return package
    finally:
        conn.rollback()
        database._release(conn)


def verify_package(package, user_id):
    if not isinstance(package, dict) or not isinstance(package.get("payload"), str):
        raise ValueError("Select a StockPilot account transfer file, not an accounting report")
    encoded = package["payload"]
    if len(_canonical(package).encode()) > MAX_BYTES:
        raise ValueError("Transfer file exceeds 10 MB")
    signature = package.get("signature")
    if not isinstance(signature, str) or len(signature) != 64 or not signature.isascii() or not hmac.compare_digest(_signature(encoded), signature):
        raise ValueError("Transfer signature is invalid. Use an unmodified export from this StockPilot installation")
    payload = json.loads(encoded)
    if payload.get("format") != "stockpilot-account-transfer" or payload.get("version") != 1:
        raise ValueError("Unsupported transfer format")
    if payload["source_user_id"] == user_id:
        raise ValueError("Sign in to a different account to import this file")
    return payload


def _insert(cursor, table, values):
    columns = ", ".join(values)
    cursor.execute(f"INSERT INTO {table} ({columns}) VALUES ({', '.join([database.PH] * len(values))})"
                   + (" RETURNING id" if database.USE_PG else ""), tuple(values.values()))
    return database._fetchone(cursor)["id"] if database.USE_PG else cursor.lastrowid


def _state(cursor, payload, user_id):
    key = f"account-transfer:{payload['source_user_id']}"
    digest = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    cursor.execute(f"SELECT after_json FROM accounting_events WHERE user_id={database.PH} AND idempotency_key={database.PH}", (user_id, key))
    previous = database._fetchone(cursor)
    if previous:
        previous = json.loads(previous["after_json"])
        if previous["digest"] != digest:
            raise ValueError("This source account was already imported. A newer export cannot be merged automatically without duplicating trades")
    return key, digest, previous


def preview_import(user_id, package):
    payload = verify_package(package, user_id)
    conn = database.get_db()
    try:
        cursor = conn.cursor()
        _, _, previous = _state(cursor, payload, user_id)
        existing = {}
        for table in (*AUDITED_TABLES, *COPY_TABLES):
            cursor.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE user_id={database.PH}", (user_id,))
            existing[table] = database._fetchone(cursor)["count"]
        return {"source_name": payload["source_name"], "source_user_id": payload["source_user_id"],
                "counts": payload["counts"], "ledger_events": len(payload["events"]),
                "destination_counts": existing, "already_imported": previous is not None}
    finally:
        conn.rollback()
        database._release(conn)


def import_account(user_id, package):
    payload = verify_package(package, user_id)
    conn = database.get_db()
    try:
        cursor = conn.cursor()
        if database.USE_PG:
            cursor.execute(f"SELECT id FROM users WHERE id={database.PH} FOR UPDATE", (user_id,))
        else:
            cursor.execute("BEGIN IMMEDIATE")
        key, digest, previous = _state(cursor, payload, user_id)
        if previous:
            return {"already_imported": True, "counts": previous["counts"]}
        cursor.execute(f"SELECT id FROM accounting_events WHERE user_id={database.PH} LIMIT 1", (user_id,))
        combined_histories = bool(database._fetchone(cursor)) or payload.get("combined_histories", False)
        columns = {}
        for table in (*AUDITED_TABLES, *COPY_TABLES):
            cursor.execute(f"SELECT * FROM {table} WHERE 1=0")
            columns[table] = {column[0] for column in cursor.description} - {"id", "user_id"}
        cursor.execute(f"SELECT after_json FROM accounting_events WHERE user_id={database.PH} AND source='manual' AND operation='LINK'", (user_id,))
        cycle_names = {json.loads(row["after_json"])["cycle"] for row in database._fetchall(cursor)}
        renamed_cycles = {}
        record_ids = {}
        event_ids = {}
        origin_events = []
        for event in payload["events"]:
            source, source_id, operation = event["source"], event["source_id"], event["operation"]
            identity = (source, source_id)
            after = dict(event["after"] or {})
            if source in AUDITED_TABLES:
                values = {field: value for field, value in after.items() if field not in {"id", "user_id"}}
                if set(values) - columns[source]:
                    raise ValueError("Export schema is incompatible with this installation")
                if "source_lot_id" in values and values["source_lot_id"] is not None:
                    opening_source = "holdings" if source == "closed_trades" else "options"
                    values["source_lot_id"] = record_ids.get((opening_source, values["source_lot_id"]))
                if operation in {"INSERT", "SNAPSHOT"}:
                    if identity in record_ids:
                        if operation != "SNAPSHOT":
                            raise ValueError("Duplicate opening record in export")
                    else:
                        record_ids[identity] = _insert(cursor, source, {"user_id": user_id, **values})
                elif operation == "UPDATE":
                    if identity not in record_ids or not values:
                        raise ValueError("Missing opening record in export")
                    cursor.execute(f"UPDATE {source} SET {', '.join(f'{field}={database.PH}' for field in values)} WHERE user_id={database.PH} AND id={database.PH}",
                                   (*values.values(), user_id, record_ids[identity]))
                elif operation == "DELETE":
                    if identity not in record_ids:
                        raise ValueError("Missing deleted record in export")
                    cursor.execute(f"DELETE FROM {source} WHERE user_id={database.PH} AND id={database.PH}", (user_id, record_ids[identity]))
                else:
                    raise ValueError("Unsupported financial event in export")
                cursor.execute(f"SELECT id FROM accounting_events WHERE user_id={database.PH} AND source={database.PH} AND source_id={database.PH} ORDER BY id DESC LIMIT 1",
                               (user_id, source, record_ids[identity]))
                event_ids[event["id"]] = database._fetchone(cursor)["id"]
                if operation == "SNAPSHOT":
                    _insert(cursor, "accounting_events", {"user_id": user_id, "source": source,
                        "source_id": record_ids[identity], "operation": "SNAPSHOT",
                        "after_json": json.dumps({**values, "id": record_ids[identity], "user_id": user_id})})
            elif source in {"manual", "closed_option_import", "closed_option_edit"}:
                if source == "manual":
                    if after.get("event_id") is not None:
                        if after["event_id"] not in event_ids:
                            raise ValueError("Missing ledger reference in export")
                        after["event_id"] = event_ids[after["event_id"]]
                    if after.get("kind") == "link":
                        name = after["cycle"]
                        if name not in renamed_cycles:
                            candidate = name
                            suffix = 1
                            while candidate in cycle_names:
                                candidate = f"{name[:45]} (import {payload['source_user_id']}-{suffix})"
                                suffix += 1
                            renamed_cycles[name] = candidate
                            cycle_names.add(candidate)
                        after["cycle"] = renamed_cycles[name]
                    mapped_id = after["event_id"] if operation == "REVERSE" else 0
                else:
                    mapped_id = record_ids[("closed_options", source_id)]
                after["idempotency_key"] = uuid4().hex
                event_ids[event["id"]] = _insert(cursor, "accounting_events", {"user_id": user_id, "source": source,
                    "source_id": mapped_id, "operation": operation, "after_json": json.dumps(after),
                    "recorded_at": event["recorded_at"], "idempotency_key": after["idempotency_key"]})
            else:
                raise ValueError("Unsupported ledger source in export")
            origin_events.append({"source_event_id": event["id"], "destination_event_id": event_ids[event["id"]],
                                  "source_recorded_at": event["recorded_at"], "source_operation": operation})
        for table in COPY_TABLES:
            for row in payload["tables"][table]:
                values = {field: value for field, value in row.items() if field not in {"id", "user_id"}}
                if set(values) - columns[table]:
                    raise ValueError("Export schema is incompatible with this installation")
                if table == "watchlist":
                    cursor.execute(f"SELECT id FROM watchlist WHERE user_id={database.PH} AND ticker={database.PH}", (user_id, values["ticker"]))
                    if database._fetchone(cursor):
                        continue
                _insert(cursor, table, {"user_id": user_id, **values})
        _insert(cursor, "accounting_events", {"user_id": user_id, "source": "account_transfer", "source_id": 0,
            "operation": "IMPORT", "idempotency_key": key, "after_json": json.dumps({"digest": digest,
                "source_user_id": payload["source_user_id"], "source_name": payload["source_name"],
                "counts": payload["counts"], "origin_events": origin_events, "cycle_names": renamed_cycles,
                "combined_histories": combined_histories})})
        conn.commit()
        return {"already_imported": False, "counts": payload["counts"], "cycle_names": renamed_cycles}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.rollback()
        database._release(conn)