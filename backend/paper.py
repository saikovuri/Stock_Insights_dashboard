"""Paper trades: suggested ideas recorded as practice positions, kept apart from real holdings and P&L.

Entries and exits use the same realistic fill as the ideas (halfway between the midpoint and the bid when selling,
the ask when buying), re-quoted when the trade is opened or closed. Open trades are marked at midpoints; trades
whose expiry has passed settle at each leg's intrinsic value from the underlying's close on the expiry date.
"""
import json
import logging
from datetime import datetime, timezone

import database

log = logging.getLogger(__name__)
MAX_OPEN = 300


def install_schema(conn, postgres=False):
    cursor = conn.cursor()
    real = "DOUBLE PRECISION" if postgres else "REAL"
    cursor.execute(f"""CREATE TABLE IF NOT EXISTS paper_trades (
        id {"SERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"},
        user_id INTEGER NOT NULL REFERENCES users(id), ticker TEXT NOT NULL, source TEXT, label TEXT,
        legs TEXT NOT NULL, contracts INTEGER NOT NULL, entry {real} NOT NULL, opened_at TEXT NOT NULL, expiry TEXT NOT NULL,
        status TEXT NOT NULL, exit_value {real}, closed_at TEXT, pnl {real}, settle_price {real})""")
    cursor.execute("CREATE INDEX IF NOT EXISTS paper_trades_user ON paper_trades(user_id, status)")
    if postgres:
        cursor.execute("ALTER TABLE paper_trades ENABLE ROW LEVEL SECURITY")
        for role in ("anon", "authenticated"):
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
            if cursor.fetchone():
                cursor.execute(f"REVOKE ALL ON paper_trades FROM {role}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sign(leg: dict) -> int:
    return 1 if leg["position"] == "long" else -1


def _intrinsic(leg: dict, price: float) -> float:
    return max(price - leg["strike"], 0) if leg["option_type"] == "call" else max(leg["strike"] - price, 0)


def _quote(ticker: str, leg: dict, cache: dict) -> dict | None:
    import options_analytics as oa
    key = (ticker, leg["expiry"])
    if key not in cache:
        try:
            calls, puts = oa._chain(ticker, leg["expiry"])
            cache[key] = {"call": calls, "put": puts}
        except Exception as error:
            log.info("Paper quote failed for %s %s: %s", ticker, leg["expiry"], error)
            cache[key] = {"call": None, "put": None}
    df = cache[key][leg["option_type"]]
    if df is None or getattr(df, "empty", True):
        return None
    match = df[df["strike"] == leg["strike"]]
    if match.empty:
        return None
    row = match.iloc[0]
    bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
    if not (ask > 0 and ask >= bid >= 0):
        return None
    mid = (bid + ask) / 2 if bid > 0 else ask / 2
    return {"bid": bid, "ask": ask, "mid": mid}


def _fill(quote: dict, buying: bool) -> float:
    """Realistic fill: halfway between the midpoint and the price you'd cross to (ask when buying, bid when selling)."""
    return (quote["mid"] + (quote["ask"] if buying else quote["bid"])) / 2


def _value(legs: list[dict], prices: list[float]) -> float:
    """Signed per-share value of one structure: bought legs add, sold legs subtract (a debit is positive)."""
    return sum(_sign(leg) * leg["ratio"] * price for leg, price in zip(legs, prices))


def settle_ready(expiry: str) -> bool:
    """An expiry's close is final once the next day starts or 4:15 PM ET on the day (the track record's cutoff):
    right at the bell the daily bar can still show the last trade rather than the closing auction."""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    day = str(expiry)[:10]
    return day < now.date().isoformat() or (day == now.date().isoformat() and (now.hour, now.minute) >= (16, 15))


def expiry_close(ticker: str, day: str) -> float | None:
    """The underlying's daily close on `day`, or None when the provider has no bar for it."""
    import pandas as pd
    from stock_data import get_stock_data
    try:
        closes = get_stock_data(ticker, period="2y", interval="1d")["Close"]
        closes.index = pd.to_datetime(closes.index.date)
        on = closes[closes.index == pd.Timestamp(day)]
        return float(on.iloc[-1]) if len(on) and pd.notna(on.iloc[-1]) and on.iloc[-1] > 0 else None
    except Exception as error:
        log.info("Expiry close unavailable for %s %s: %s", ticker, day, error)
        return None


def _clean_legs(legs: list[dict]) -> list[dict]:
    import options_analytics as oa
    import spreads
    out = [{"position": leg["position"], "option_type": leg["option_type"], "strike": float(leg["strike"]),
            "expiry": str(leg["expiry"])[:10], "ratio": int(leg.get("ratio") or 1)} for leg in legs]
    if len({leg["expiry"] for leg in out}) != 1:
        raise ValueError("Paper trades use one expiry for every leg")
    if not oa._live(out[0]["expiry"]):
        raise ValueError("This expiry has already passed")
    if len(out) > 1:
        spreads.classify([{**leg, "premium": 0} for leg in out])
    return out


def open_trade(user_id: int, ticker: str, legs: list[dict], contracts: int, source: str | None, label: str | None) -> dict:
    PH = database.PH
    open_count = database._run(f"SELECT COUNT(*) AS n FROM paper_trades WHERE user_id={PH} AND status='open'", (user_id,), "one")["n"]
    if open_count >= MAX_OPEN:
        raise ValueError(f"You have {MAX_OPEN} open paper trades; close or delete some first")
    ticker = ticker.upper()
    legs = _clean_legs(legs)
    cache, fills = {}, []
    for leg in legs:
        quote = _quote(ticker, leg, cache)
        if quote is None or (leg["position"] == "short" and quote["bid"] <= 0):
            raise ValueError(f"No usable quote for the ${leg['strike']:g} {leg['option_type']} right now; try again during market hours")
        fills.append(round(_fill(quote, leg["position"] == "long"), 4))
    legs = [{**leg, "fill": fill} for leg, fill in zip(legs, fills)]
    entry = round(_value(legs, fills), 4)
    if entry == 0:
        raise ValueError("The legs net to zero at current prices")
    row = database._run(f"""INSERT INTO paper_trades (user_id, ticker, source, label, legs, contracts, entry, opened_at, expiry, status)
        VALUES ({', '.join([PH] * 10)}) RETURNING id""",
        (user_id, ticker, source, label, json.dumps(legs), contracts, entry, _now(), legs[0]["expiry"], "open"), "one")
    return _shape({"id": row["id"], "ticker": ticker, "source": source, "label": label, "legs": json.dumps(legs),
                   "contracts": contracts, "entry": entry, "opened_at": _now(), "expiry": legs[0]["expiry"], "status": "open",
                   "exit_value": None, "closed_at": None, "pnl": None, "settle_price": None})


def _shape(row: dict, mark: float | None = None) -> dict:
    legs = json.loads(row["legs"]) if isinstance(row["legs"], str) else row["legs"]
    out = {k: row[k] for k in ("id", "ticker", "source", "label", "contracts", "entry", "opened_at", "expiry", "status",
                               "exit_value", "closed_at", "pnl", "settle_price")}
    out["legs"] = legs
    out["style"] = "debit" if row["entry"] > 0 else "credit"
    if len(legs) > 1:
        import spreads
        try:
            info = spreads.describe([{**leg, "premium": leg["fill"]} for leg in legs], row["contracts"])
            out.update(structure=info["label"], strikes=info["strikes"], max_loss=info["max_loss"], max_profit=info["max_profit"])
        except ValueError:
            out.update(structure="Spread", strikes="/".join(f"${leg['strike']:g}" for leg in legs))
    else:
        leg = legs[0]
        out.update(structure=f"{leg['position'].title()} {leg['option_type']}", strikes=f"${leg['strike']:g}")
    if mark is not None:
        out["mark"] = round(mark, 4)
        out["unrealized"] = round((mark - row["entry"]) * 100 * row["contracts"], 2)
    return out


def _settle_expired(user_id: int, rows: list[dict]) -> None:
    import options_analytics as oa
    PH = database.PH
    for row in rows:
        if row["status"] != "open" or oa._live(row["expiry"]) or not settle_ready(row["expiry"]):
            continue
        price = expiry_close(row["ticker"], row["expiry"])
        if price is None:
            continue
        legs = json.loads(row["legs"])
        value = _value(legs, [_intrinsic(leg, price) for leg in legs])
        pnl = round((value - row["entry"]) * 100 * row["contracts"], 2)
        database._run(f"""UPDATE paper_trades SET status='expired', exit_value={PH}, closed_at={PH}, pnl={PH}, settle_price={PH}
            WHERE id={PH} AND user_id={PH} AND status='open'""",
            (round(value, 4), f"{row['expiry']}T20:00:00+00:00", pnl, round(price, 4), row["id"], user_id))
        row.update(status="expired", exit_value=round(value, 4), closed_at=f"{row['expiry']}T20:00:00+00:00", pnl=pnl,
                   settle_price=round(price, 4))


def list_trades(user_id: int) -> dict:
    PH = database.PH
    rows = database._run(f"SELECT * FROM paper_trades WHERE user_id={PH} ORDER BY opened_at DESC, id DESC", (user_id,), "all")
    _settle_expired(user_id, rows)
    cache, out = {}, []
    for row in rows:
        mark = None
        if row["status"] == "open":
            legs = json.loads(row["legs"])
            quotes = [_quote(row["ticker"], leg, cache) for leg in legs]
            if all(quotes):
                mark = _value(legs, [q["mid"] for q in quotes])
        out.append(_shape(row, mark))
    closed = [t for t in out if t["status"] != "open"]
    open_ = [t for t in out if t["status"] == "open"]
    wins = [t for t in closed if t["pnl"] > 0]
    return {
        "trades": out,
        "stats": {"closed": len(closed), "open": len(open_), "wins": len(wins),
                  "win_rate": round(len(wins) / len(closed) * 100) if closed else None,
                  "realized": round(sum(t["pnl"] for t in closed), 2),
                  "unrealized": None if any(t.get("mark") is None for t in open_) else round(sum(t["unrealized"] for t in open_), 2)},
        "note": "Practice positions, not real orders. Entries and exits assume a fill halfway between the midpoint and the bid/ask "
                "at the moment you record them; fees, early assignment and intraday management are not modeled. Expired "
                "trades settle at intrinsic value from the expiry-day close.",
    }


def close_trade(user_id: int, trade_id: int) -> dict:
    PH = database.PH
    row = database._run(f"SELECT * FROM paper_trades WHERE id={PH} AND user_id={PH}", (trade_id, user_id), "one")
    if not row:
        raise LookupError("Paper trade not found")
    if row["status"] != "open":
        raise ValueError("This paper trade is already closed")
    legs, cache = json.loads(row["legs"]), {}
    prices = []
    for leg in legs:
        quote = _quote(row["ticker"], leg, cache)
        if quote is None:
            raise ValueError(f"No usable quote for the ${leg['strike']:g} {leg['option_type']} right now; try again during market hours")
        prices.append(_fill(quote, leg["position"] == "short"))
    value = round(_value(legs, prices), 4)
    pnl = round((value - row["entry"]) * 100 * row["contracts"], 2)
    database._run(f"UPDATE paper_trades SET status='closed', exit_value={PH}, closed_at={PH}, pnl={PH} WHERE id={PH} AND user_id={PH}",
                  (value, _now(), pnl, trade_id, user_id))
    return {"id": trade_id, "exit_value": value, "pnl": pnl}


def delete_trade(user_id: int, trade_id: int) -> bool:
    PH = database.PH
    return database._run(f"DELETE FROM paper_trades WHERE id={PH} AND user_id={PH}", (trade_id, user_id)) > 0
