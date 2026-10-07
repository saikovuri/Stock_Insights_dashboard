"""Buy zones: a target entry price per watchlist stock, with the cash-secured put that would get you in near it
("get paid to wait"), plus an earnings / ex-dividend week view across the watchlist and holdings."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import database
import options_analytics as oa
from cache import get_or_fetch
from stock_data import get_quote

log = logging.getLogger(__name__)
MIN_DTE, MAX_DTE, IDEAL_DTE = 21, 50, 35
MIN_OI = 100


def get_zones(user_id: int) -> dict[str, float]:
    rows = database._run(f"SELECT ticker, price FROM buy_zones WHERE user_id={database.PH}", (user_id,), "all")
    return {r["ticker"]: float(r["price"]) for r in rows}


def set_zone(user_id: int, ticker: str, price: float | None) -> None:
    PH = database.PH
    if price is None:
        database._run(f"DELETE FROM buy_zones WHERE user_id={PH} AND ticker={PH}", (user_id, ticker))
        return
    database._run(f"""INSERT INTO buy_zones (user_id, ticker, price, updated_at) VALUES ({PH}, {PH}, {PH}, {PH})
        ON CONFLICT (user_id, ticker) DO UPDATE SET price=excluded.price, updated_at=excluded.updated_at""",
                  (user_id, ticker, price, datetime.now(timezone.utc).isoformat(timespec="seconds")))


def _put_to_wait(ticker: str, target: float, spot: float) -> dict | None:
    """Highest liquid put strike at or below the target, on the listed expiry closest to ~35 days."""
    def _fetch():
        expiries = [e for e in oa._expirations(ticker) if oa._live(e) and MIN_DTE <= oa._dte(e) <= MAX_DTE]
        if not expiries:
            return None
        expiry = min(expiries, key=lambda e: abs(oa._dte(e) - IDEAL_DTE))
        _, puts = oa._chain(ticker, expiry)
        rows = [r for r in oa._otm_rows(puts, "put", spot, oa._years(expiry))
                if r["strike"] <= target and r["oi"] >= MIN_OI and r["ask"] >= r["bid"] > 0]
        if not rows:
            return None
        best = max(rows, key=lambda r: r["strike"])
        dte = max(oa._dte(expiry), 1)
        return {"expiry": expiry, "dte": dte, "strike": best["strike"], "bid": round(best["bid"], 2), "mid": round(best["mid"], 2),
                "premium": round(best["mid"] * 100, 2), "cash_needed": round(best["strike"] * 100, 2),
                "effective_entry": round(best["strike"] - best["mid"], 2),
                "annualized_pct": round(best["mid"] / best["strike"] * 365 / dte * 100, 1),
                "chance_assigned_pct": round(best["p_itm"] * 100), "open_interest": best["oi"]}
    return get_or_fetch(f"buyzone:{ticker}:{target:.2f}", _fetch, ttl=600)


def overview(user_id: int) -> dict:
    zones = get_zones(user_id)

    def one(item):
        ticker, target = item
        try:
            spot = get_quote(ticker).get("price")
        except Exception:
            spot = None
        row = {"ticker": ticker, "target": target, "price": spot,
               "distance_pct": round((spot - target) / spot * 100, 1) if spot else None,
               "in_zone": bool(spot and spot <= target), "put": None}
        if spot and spot > target:
            try:
                row["put"] = _put_to_wait(ticker, target, spot)
            except Exception as error:
                log.info("No buy-zone put for %s: %s", ticker, error)
        return row

    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(one, list(zones.items())[:30]))
    items.sort(key=lambda r: (r["distance_pct"] is None, r["distance_pct"] if r["distance_pct"] is not None else 0))
    return {"items": items, "note": "Puts are the highest strike at or below your buy price with open interest >= 100, "
                                    "on the listed expiry closest to 35 days (21-50). Premium uses the quoted midpoint; "
                                    "chance assigned is a model estimate."}


def _ex_dividend(ticker: str) -> str | None:
    def _fetch():
        import yfinance as yf
        value = (yf.Ticker(ticker).calendar or {}).get("Ex-Dividend Date")
        return value.isoformat() if hasattr(value, "isoformat") else None
    try:
        return get_or_fetch(f"exdiv:{ticker}", _fetch, ttl=12 * 3600)
    except Exception:
        return None


def event_week(user_id: int, days: int = 14) -> dict:
    """Earnings and ex-dividend dates in the next `days` days for watchlist and held tickers."""
    watch = set(database.get_user_watchlist(user_id))
    held = {h["ticker"] for h in database.get_user_holdings(user_id) if h["shares"] > 0}
    held |= {o["ticker"] for o in database.get_user_options(user_id)}
    tickers = sorted(watch | held)[:60]
    today, end = date.today(), date.today() + timedelta(days=days)

    def one(ticker):
        out = []
        try:
            info = oa.earnings_info(ticker)
            if info.get("next") and today.isoformat() <= info["next"] <= end.isoformat():
                out.append({"date": info["next"], "ticker": ticker, "kind": "earnings", "timing": info.get("next_timing"),
                            "confirmed": info.get("next_confirmed", False)})
        except Exception as error:
            log.info("Earnings unavailable for %s: %s", ticker, error)
        ex = _ex_dividend(ticker)
        if ex and today.isoformat() <= ex <= end.isoformat():
            out.append({"date": ex, "ticker": ticker, "kind": "ex_dividend"})
        return [{**e, "held": ticker in held, "watching": ticker in watch} for e in out]

    with ThreadPoolExecutor(max_workers=8) as pool:
        events = [e for batch in pool.map(one, tickers) for e in batch]
    events.sort(key=lambda e: (e["date"], e["ticker"]))
    return {"from": today.isoformat(), "to": end.isoformat(), "events": events, "checked": len(tickers)}
