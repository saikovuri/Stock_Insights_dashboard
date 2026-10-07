"""Brokerage account labels, user-entered cash balances, daily NAV snapshots and wheel-cycle auto-linking."""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

log = logging.getLogger(__name__)
_LABELED = ("holdings", "options", "closed_trades", "closed_options", "journal")


def install_schema(conn, postgres=False):
    cursor = conn.cursor()
    real = "DOUBLE PRECISION" if postgres else "REAL"
    cursor.execute(f"""CREATE TABLE IF NOT EXISTS account_cash (
        user_id INTEGER NOT NULL REFERENCES users(id), account TEXT NOT NULL, cash {real} NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(user_id, account))""")
    cursor.execute(f"""CREATE TABLE IF NOT EXISTS nav_snapshots (
        user_id INTEGER NOT NULL REFERENCES users(id), account TEXT NOT NULL, day TEXT NOT NULL,
        cash {real}, stocks {real}, options {real}, nav {real}, complete INTEGER NOT NULL,
        recorded_at TEXT NOT NULL, PRIMARY KEY(user_id, account, day))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS applied_splits (
        user_id INTEGER NOT NULL REFERENCES users(id), ticker TEXT NOT NULL, split_date TEXT NOT NULL,
        ratio TEXT NOT NULL, applied_at TEXT NOT NULL, PRIMARY KEY(user_id, ticker, split_date))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS watchlist_lists (
        user_id INTEGER NOT NULL REFERENCES users(id), ticker TEXT NOT NULL, list_name TEXT NOT NULL,
        PRIMARY KEY(user_id, ticker, list_name))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS watchlist_groups (
        user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, position INTEGER NOT NULL,
        PRIMARY KEY(user_id, name))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS applied_actions (
        user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL, ticker TEXT NOT NULL, action_date TEXT NOT NULL,
        details TEXT NOT NULL, applied_at TEXT NOT NULL, PRIMARY KEY(user_id, kind, ticker, action_date))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS user_rules (
        user_id INTEGER PRIMARY KEY REFERENCES users(id), rules TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    cursor.execute(f"""CREATE TABLE IF NOT EXISTS buy_zones (
        user_id INTEGER NOT NULL REFERENCES users(id), ticker TEXT NOT NULL, price {real} NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(user_id, ticker))""")
    if postgres:
        for table in ("account_cash", "nav_snapshots", "applied_splits", "watchlist_lists", "watchlist_groups", "applied_actions",
                      "user_rules", "buy_zones"):
            cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            for role in ("anon", "authenticated"):
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
                if cursor.fetchone():
                    cursor.execute(f"REVOKE ALL ON {table} FROM {role}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cash(user_id: int) -> dict[str, dict]:
    import database
    rows = database._run(f"SELECT account, cash, updated_at FROM account_cash WHERE user_id={database.PH}", (user_id,), "all")
    return {r["account"]: r for r in rows}


def list_accounts(user_id: int) -> dict:
    """Every account label in use, with its cash balance and cash still free after short-put collateral."""
    import database
    names = {database.DEFAULT_ACCOUNT}
    for table in _LABELED:
        rows = database._run(f"SELECT DISTINCT account FROM {table} WHERE user_id={database.PH}", (user_id,), "all")
        names |= {r["account"] or database.DEFAULT_ACCOUNT for r in rows}
    cash = _cash(user_id)
    names |= set(cash)
    collateral = {}
    for option in database.get_user_options(user_id):
        if option["position"] == "short" and option["option_type"] == "put":
            name = option.get("account") or database.DEFAULT_ACCOUNT
            collateral[name] = collateral.get(name, 0) + option["strike"] * 100 * option["contracts"]
    accounts = []
    for name in sorted(names, key=lambda n: (n != database.DEFAULT_ACCOUNT, n.lower())):
        entry = cash.get(name)
        balance = entry["cash"] if entry else None
        reserved = round(collateral.get(name, 0), 2)
        accounts.append({"name": name, "cash": balance, "cash_updated_at": entry["updated_at"] if entry else None,
                         "put_collateral": reserved,
                         "free_cash": round(balance - reserved, 2) if balance is not None else None})
    return {"accounts": accounts, "default": database.DEFAULT_ACCOUNT}


def set_cash(user_id: int, account: str, cash: float) -> dict:
    import database
    name = database.account_name(account) or database.DEFAULT_ACCOUNT
    database._run(f"""INSERT INTO account_cash (user_id, account, cash, updated_at) VALUES ({', '.join([database.PH] * 4)})
        ON CONFLICT (user_id, account) DO UPDATE SET cash=excluded.cash, updated_at=excluded.updated_at""",
                  (user_id, name, round(float(cash), 2), _now()))
    return {"account": name, "cash": round(float(cash), 2)}


def snapshot(user_id: int, day: str | None = None) -> list[dict]:
    """Record today's value per account from live marks. Missing marks make the snapshot incomplete, never zero."""
    import database
    from main import portfolio_summary_endpoint, options_summary_endpoint
    day = day or datetime.now(timezone.utc).date().isoformat()
    user = {"user_id": user_id}
    stocks, options = portfolio_summary_endpoint(user=user, account=None), options_summary_endpoint(user=user, account=None)
    cash = _cash(user_id)
    values: dict[str, dict] = {}

    def bucket(name):
        return values.setdefault(name or database.DEFAULT_ACCOUNT, {"stocks": 0.0, "options": 0.0, "complete": True})

    for holding in stocks.get("holdings", []):
        entry = bucket(holding.get("account"))
        if holding.get("current_value") is None:
            entry["complete"] = False
        else:
            entry["stocks"] += holding["current_value"]
    for option in options.get("options", []):
        entry = bucket(option.get("account"))
        if option.get("market_price") is None:
            entry["complete"] = False
        else:
            value = option["market_price"] * 100 * option["contracts"]
            entry["options"] += value if option["position"] == "long" else -value
    for name in cash:
        bucket(name)
    recorded = []
    for name, entry in values.items():
        balance = cash.get(name, {}).get("cash")
        complete = entry["complete"] and balance is not None
        nav = round(entry["stocks"] + entry["options"] + (balance or 0), 2) if complete else None
        row = (user_id, name, day, balance, round(entry["stocks"], 2), round(entry["options"], 2), nav, int(complete), _now())
        database._run(f"""INSERT INTO nav_snapshots (user_id, account, day, cash, stocks, options, nav, complete, recorded_at)
            VALUES ({', '.join([database.PH] * 9)}) ON CONFLICT (user_id, account, day) DO UPDATE SET cash=excluded.cash,
            stocks=excluded.stocks, options=excluded.options, nav=excluded.nav, complete=excluded.complete,
            recorded_at=excluded.recorded_at""", row)
        recorded.append({"account": name, "day": day, "cash": balance, "stocks": row[4], "options": row[5],
                         "nav": nav, "complete": complete})
    return recorded


def snapshot_all() -> int:
    import database
    users = {r["user_id"] for table in ("holdings", "options", "account_cash")
             for r in database._run(f"SELECT DISTINCT user_id FROM {table}", (), "all")}
    for uid in users:
        try:
            snapshot(uid)
        except Exception as error:
            log.info("NAV snapshot failed for user %s: %s", uid, error)
    return len(users)


def _external_flows(user_id: int, account: str | None = None) -> dict[str, Decimal]:
    """Deposits minus withdrawals per day. With an account, only that account's flows; unassigned entries count as Default."""
    import database
    from accounting import _active_manual
    events = database._run(f"SELECT * FROM accounting_events WHERE user_id={database.PH} AND source='manual' ORDER BY id",
                           (user_id,), "all")
    flows: dict[str, Decimal] = {}
    for event in _active_manual(events):
        payload = json.loads(event["after_json"])
        if payload.get("kind") in ("deposit", "withdrawal"):
            if account and (payload.get("account") or database.DEFAULT_ACCOUNT) != account:
                continue
            sign = 1 if payload["kind"] == "deposit" else -1
            day = payload["occurred_at"][:10]
            flows[day] = flows.get(day, Decimal("0")) + sign * Decimal(str(payload["amount"]))
    return flows


def nav_history(user_id: int, account: str | None = None) -> dict:
    import database
    rows = database._run(f"SELECT * FROM nav_snapshots WHERE user_id={database.PH} ORDER BY day", (user_id,), "all")
    days: dict[str, dict] = {}
    for row in rows:
        if account and row["account"] != account:
            continue
        entry = days.setdefault(row["day"], {"day": row["day"], "nav": 0.0, "cash": 0.0, "stocks": 0.0, "options": 0.0, "complete": True})
        entry["complete"] = entry["complete"] and bool(row["complete"])
        for key in ("nav", "cash", "stocks", "options"):
            entry[key] += row[key] or 0
    series = [{**d, "nav": round(d["nav"], 2) if d["complete"] else None} for d in days.values()]
    flows = _external_flows(user_id, account)
    growth, peak, drawdown, previous = 1.0, None, 0.0, None
    for point in series:
        if point["nav"] is None:
            continue
        if previous is not None and previous["nav"] > 0:
            flow = float(sum(v for d, v in flows.items() if previous["day"] < d <= point["day"]))
            growth *= (point["nav"] - flow) / previous["nav"]
        peak = growth if peak is None else max(peak, growth)
        drawdown = min(drawdown, growth / peak - 1)
        point["growth_index"] = round(growth * 100, 4)
        previous = point
    complete = [p for p in series if p["nav"] is not None]
    return {
        "account": account, "series": series,
        "return_pct": round((growth - 1) * 100, 2) if len(complete) > 1 else None,
        "max_drawdown_pct": round(drawdown * 100, 2) if len(complete) > 1 else None,
        "flow_adjusted": True,
        "note": ("Deposits and withdrawals from the Account ledger are removed from returns." if not account else
                 f"Deposits and withdrawals assigned to {account} are removed from returns; ledger entries without an "
                 f"account count toward {database.DEFAULT_ACCOUNT}. Moves between your accounts need a withdrawal and a deposit."),
    }


def link_closed_option(user_id: int, closed_id: int, contracts: int, cycle: str) -> dict:
    """Allocate a just-closed option to a named wheel cycle; retries reuse the same request key."""
    import accounting
    import database
    event = database._run(f"""SELECT id FROM accounting_events WHERE user_id={database.PH} AND source='closed_options'
        AND source_id={database.PH} AND operation='INSERT' ORDER BY id DESC""", (user_id, closed_id), "one")
    if not event:
        raise LookupError("Closed option ledger event not found")
    return accounting.record_entry(user_id, {
        "kind": "link", "event_id": event["id"], "cycle": cycle.strip(), "quantity": contracts,
        "occurred_at": datetime.now(timezone.utc), "idempotency_key": f"autolink-{event['id']}",
        "note": "Linked when the option was closed"})
