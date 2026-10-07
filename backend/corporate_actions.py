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


# ── Spin-offs and mergers (user-entered terms; free data sources don't publish them reliably) ──

def _locked_action(cur, user_id: int, kind: str, ticker: str, action_date: str):
    import database
    PH = database.PH
    if database.USE_PG:
        cur.execute(f"SELECT id FROM users WHERE id={PH} FOR UPDATE", (user_id,))
    else:
        cur.execute("BEGIN IMMEDIATE")
    cur.execute(f"SELECT 1 FROM applied_actions WHERE user_id={PH} AND kind={PH} AND ticker={PH} AND action_date={PH}",
                (user_id, kind, ticker, action_date))
    if database._fetchone(cur):
        raise ValueError(f"This {kind} was already recorded")


def _record_action(cur, user_id: int, kind: str, ticker: str, action_date: str, details: dict):
    import database
    PH = database.PH
    cur.execute(f"""INSERT INTO applied_actions (user_id, kind, ticker, action_date, details, applied_at)
        VALUES ({', '.join([PH] * 6)})""", (user_id, kind, ticker, action_date, json.dumps(details),
                                            datetime.now(timezone.utc).isoformat(timespec="seconds")))
    cur.execute(f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, {PH}, {PH}, {PH})",
                (user_id, kind.upper(), ticker, json.dumps({"action_date": action_date, **details})))


def _open_options(cur, user_id: int, ticker: str) -> int:
    import database
    cur.execute(f"SELECT COUNT(*) AS n FROM options WHERE user_id={database.PH} AND ticker={database.PH}", (user_id, ticker))
    return int(database._fetchone(cur)["n"])


def apply_spinoff(user_id: int, ticker: str, new_ticker: str, action_date: str, ratio: float, basis_pct: float) -> dict:
    """Each lot held before the ex-date gets ratio new shares per share. The new lot keeps the original
    acquisition date and account; basis_pct of the lot's cost moves to it (per the company's basis notice)."""
    import database
    PH = database.PH
    ticker, new_ticker = ticker.upper(), new_ticker.upper()
    conn = database.get_db()
    try:
        cur = conn.cursor()
        _locked_action(cur, user_id, "spinoff", ticker, action_date)
        cur.execute(f"SELECT * FROM holdings WHERE user_id={PH} AND ticker={PH} ORDER BY date_added, id", (user_id, ticker))
        lots = [h for h in database._fetchall(cur) if _day(h["date_added"]) < action_date]
        if not lots:
            raise LookupError(f"No {ticker} lots were held before {action_date}")
        moved = 0.0
        for lot in lots:
            cost = lot["shares"] * lot["buy_price"]
            child_cost = cost * basis_pct / 100
            child_shares = round(lot["shares"] * ratio, 6)
            cur.execute(f"UPDATE holdings SET buy_price={PH} WHERE id={PH}",
                        (round((cost - child_cost) / lot["shares"], 6), lot["id"]))
            cur.execute(f"""INSERT INTO holdings (user_id, ticker, shares, buy_price, date_added, account)
                VALUES ({', '.join([PH] * 6)})""", (user_id, new_ticker, child_shares,
                                                    round(child_cost / child_shares, 6), lot["date_added"], lot.get("account")))
            moved += child_cost
        details = {"new_ticker": new_ticker, "ratio": ratio, "basis_pct": basis_pct, "lots": len(lots),
                   "basis_moved": round(moved, 2)}
        options = _open_options(cur, user_id, ticker)
        _record_action(cur, user_id, "spinoff", ticker, action_date, details)
        conn.commit()
        return {"ticker": ticker, "action_date": action_date, **details, "options_unadjusted": options}
    except Exception:
        conn.rollback()
        raise
    finally:
        database._release(conn)


def apply_merger(user_id: int, ticker: str, action_date: str, new_ticker: str | None, ratio: float,
                 cash_per_share: float) -> dict:
    """Cash-only deals close every lot at the cash price on the deal date. Stock deals convert each lot in place
    (same acquisition date and account) at ratio new shares per old share. In mixed deals the cash is treated as
    a return of basis; any gain the cash triggers above basis is not recorded."""
    import database
    PH = database.PH
    ticker = ticker.upper()
    new_ticker = new_ticker.upper() if new_ticker else None
    conn = database.get_db()
    try:
        cur = conn.cursor()
        _locked_action(cur, user_id, "merger", ticker, action_date)
        cur.execute(f"SELECT * FROM holdings WHERE user_id={PH} AND ticker={PH} ORDER BY date_added, id", (user_id, ticker))
        lots = [h for h in database._fetchall(cur) if _day(h["date_added"]) <= action_date]
        if not lots:
            raise LookupError(f"No {ticker} lots were held on {action_date}")
        realized, basis_capped = 0.0, 0
        for lot in lots:
            if not ratio:
                result = database.sell_user_holding_by_lot(user_id, lot["id"], lot["shares"], cash_per_share,
                                                           _conn=conn, closed_at=f"{action_date} 20:00:00")
                realized += result["pnl"]
                continue
            remaining = lot["buy_price"] - cash_per_share
            basis_capped += remaining < 0
            cur.execute(f"UPDATE holdings SET ticker={PH}, shares={PH}, buy_price={PH} WHERE id={PH}",
                        (new_ticker, round(lot["shares"] * ratio, 6), round(max(remaining, 0) / ratio, 6), lot["id"]))
        details = {"new_ticker": new_ticker, "ratio": ratio, "cash_per_share": cash_per_share, "lots": len(lots),
                   "realized_pnl": round(realized, 2), "lots_cash_above_basis": basis_capped}
        options = _open_options(cur, user_id, ticker)
        _record_action(cur, user_id, "merger", ticker, action_date, details)
        conn.commit()
        return {"ticker": ticker, "action_date": action_date, **details, "options_unadjusted": options}
    except Exception:
        conn.rollback()
        raise
    finally:
        database._release(conn)


def applied_actions(user_id: int) -> list[dict]:
    import database
    rows = database._run(f"SELECT * FROM applied_actions WHERE user_id={database.PH} ORDER BY applied_at DESC",
                         (user_id,), "all")
    return [{"kind": r["kind"], "ticker": r["ticker"], "action_date": r["action_date"],
             "details": json.loads(r["details"]), "applied_at": r["applied_at"]} for r in rows]


def _last_bar(ticker: str) -> str | None:
    """Date of the latest daily bar ('' when Yahoo returns none); None when the lookup itself failed."""
    def _fetch():
        import yfinance as yf
        history = yf.Ticker(ticker).history(period="1mo", auto_adjust=False)
        return history.index[-1].date().isoformat() if len(history) else ""
    try:
        return get_or_fetch(f"lastbar:{ticker}", _fetch, ttl=6 * 3600)
    except Exception as error:
        log.info("Quote history unavailable for %s: %s", ticker, error)
        return None


def stale_holdings(user_id: int, max_age_days: int = 7) -> list[dict]:
    """Held symbols with no recent daily bar, a common sign of an acquisition or delisting. Only reported while
    a benchmark symbol has fresh data, so a data outage doesn't flag every holding."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date
    import database
    tickers = sorted({h["ticker"] for h in database.get_user_holdings(user_id)})[:40]
    if not tickers:
        return []
    today = datetime.now(timezone.utc).date()

    def age(day):
        return (today - date.fromisoformat(day)).days if day else None

    benchmark = _last_bar("SPY")
    if not benchmark or age(benchmark) > max_age_days:
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        bars = dict(zip(tickers, pool.map(_last_bar, tickers)))
    return [{"ticker": t, "last_quote": day or None} for t, day in bars.items()
            if day is not None and (day == "" or age(day) > max_age_days)]
