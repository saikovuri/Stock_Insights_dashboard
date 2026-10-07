"""Stock split detection and atomic adjustment of recorded lots and options."""

import json
import logging
from datetime import datetime, timezone
from fractions import Fraction

from cache import get_or_fetch

log = logging.getLogger(__name__)


def _splits(ticker: str) -> list[tuple[str, float]]:
    def _fetch():
        import yfinance as yf
        series = yf.Ticker(ticker).splits
        return [(index.date().isoformat(), float(ratio)) for index, ratio in series.items() if ratio and ratio > 0]
    try:
        return get_or_fetch(f"splits:{ticker}", _fetch, ttl=12 * 3600)
    except Exception as error:
        log.info("Split history unavailable for %s: %s", ticker, error)
        return []


def _day(value) -> str:
    return str(value or "")[:10]


def _option_ratio(ratio: float) -> int | None:
    """Whole-number forward splits map to more standard contracts; anything else becomes an adjusted contract."""
    return int(ratio) if ratio >= 2 and float(ratio).is_integer() else None


def pending_splits(user_id: int) -> list[dict]:
    import database
    holdings, options = database.get_user_holdings(user_id), database.get_user_options(user_id)
    applied = {(r["ticker"], r["split_date"]) for r in database._run(
        f"SELECT ticker, split_date FROM applied_splits WHERE user_id={database.PH}", (user_id,), "all")}
    out = []
    for ticker in sorted({row["ticker"] for row in holdings + options}):
        lots = [h for h in holdings if h["ticker"] == ticker]
        contracts = [o for o in options if o["ticker"] == ticker]
        for split_date, ratio in _splits(ticker):
            if (ticker, split_date) in applied:
                continue
            affected_lots = [h for h in lots if _day(h["date_added"]) < split_date]
            affected_options = [o for o in contracts if _day(o["date_added"]) < split_date <= o["expiry"]]
            if not affected_lots and not affected_options:
                continue
            fraction = Fraction(ratio).limit_denominator(1000)
            out.append({"ticker": ticker, "split_date": split_date, "ratio": ratio,
                        "label": f"{fraction.numerator}-for-{fraction.denominator}",
                        "lots": len(affected_lots), "options": len(affected_options),
                        "options_adjustable": _option_ratio(ratio) is not None or not affected_options})
    return out


def apply_split(user_id: int, ticker: str, split_date: str) -> dict:
    import database
    ticker = ticker.upper()
    match = next((s for s in pending_splits(user_id) if s["ticker"] == ticker and s["split_date"] == split_date), None)
    if not match:
        raise LookupError("No pending split for this ticker and date")
    ratio = match["ratio"]
    option_ratio = _option_ratio(ratio)
    PH = database.PH
    conn = database.get_db()
    try:
        cur = conn.cursor()
        if database.USE_PG:
            cur.execute(f"SELECT id FROM users WHERE id={PH} FOR UPDATE", (user_id,))
        else:
            cur.execute("BEGIN IMMEDIATE")
        cur.execute(f"SELECT 1 FROM applied_splits WHERE user_id={PH} AND ticker={PH} AND split_date={PH}",
                    (user_id, ticker, split_date))
        if database._fetchone(cur):
            raise ValueError("This split was already applied")
        cur.execute(f"SELECT * FROM holdings WHERE user_id={PH} AND ticker={PH}", (user_id, ticker))
        lots = [h for h in database._fetchall(cur) if _day(h["date_added"]) < split_date]
        for lot in lots:
            cur.execute(f"UPDATE holdings SET shares={PH}, buy_price={PH} WHERE id={PH}",
                        (round(lot["shares"] * ratio, 6), round(lot["buy_price"] / ratio, 6), lot["id"]))
        adjusted, skipped = 0, 0
        cur.execute(f"SELECT * FROM options WHERE user_id={PH} AND ticker={PH}", (user_id, ticker))
        for option in database._fetchall(cur):
            if not _day(option["date_added"]) < split_date <= option["expiry"]:
                continue
            if option_ratio is None:
                skipped += 1
                continue
            cur.execute(f"UPDATE options SET contracts={PH}, strike={PH}, premium={PH} WHERE id={PH}",
                        (option["contracts"] * option_ratio, round(option["strike"] / option_ratio, 4),
                         round(option["premium"] / option_ratio, 4), option["id"]))
            adjusted += 1
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur.execute(f"INSERT INTO applied_splits (user_id, ticker, split_date, ratio, applied_at) VALUES ({PH}, {PH}, {PH}, {PH}, {PH})",
                    (user_id, ticker, split_date, str(ratio), now))
        cur.execute(f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'SPLIT', {PH}, {PH})",
                    (user_id, ticker, json.dumps({"split_date": split_date, "ratio": ratio, "lots": len(lots),
                                                  "options": adjusted, "options_skipped": skipped})))
        conn.commit()
        return {"ticker": ticker, "split_date": split_date, "ratio": ratio, "lots": len(lots),
                "options": adjusted, "options_skipped": skipped}
    except Exception:
        conn.rollback()
        raise
    finally:
        database._release(conn)
