"""Day-trading tools: intraday key levels and a 'stocks in play' gap / relative-volume scanner."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

import yfinance as yf
from yfinance import EquityQuery

from cache import get_or_fetch
from providers import finnhub_company_news, finra_short_interest
from stock_data import get_stock_data

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
OPEN, CLOSE = dtime(9, 30), dtime(16, 0)


def _hl(df):
    return None if df.empty else {"high": round(float(df["High"].max()), 2), "low": round(float(df["Low"].min()), 2)}


def key_levels(ticker: str) -> dict:
    """Previous-day high/low/close, today's premarket range and 15/30-minute opening ranges."""
    def _fetch():
        df = get_stock_data(ticker, period="5d", interval="5m", prepost=True)
        idx = df.index.tz_convert(ET) if df.index.tz is not None else df.index.tz_localize(ET)
        df = df.set_axis(idx)
        t = df.index.time
        regular = df[(t >= OPEN) & (t < CLOSE)]
        days = sorted(set(df.index.date))
        if not days:
            raise ValueError("No intraday data")
        today = days[-1]
        reg_days = sorted(set(regular.index.date))
        prev_day = next((d for d in reversed(reg_days) if d < today), None)
        prev = regular[regular.index.date == prev_day] if prev_day else regular.iloc[0:0]
        tod = df[df.index.date == today]
        tod_reg = tod[(tod.index.time >= OPEN) & (tod.index.time < CLOSE)]
        pre = tod[tod.index.time < OPEN]
        start = datetime.combine(today, OPEN, tzinfo=ET)
        or15 = tod_reg[tod_reg.index < start.replace(minute=45)]
        or30 = tod_reg[tod_reg.index < start.replace(hour=10, minute=0)]
        levels = []

        def add(key, label, price):
            if price is not None:
                levels.append({"key": key, "label": label, "price": round(float(price), 2)})

        if not prev.empty:
            add("pdh", "Prev day high", prev["High"].max())
            add("pdl", "Prev day low", prev["Low"].min())
            add("pdc", "Prev close", prev["Close"].iloc[-1])
        if not pre.empty:
            add("pmh", "Premarket high", pre["High"].max())
            add("pml", "Premarket low", pre["Low"].min())
        # Only once the range is complete
        if len(or15) >= 3:
            add("or15h", "15-min OR high", or15["High"].max())
            add("or15l", "15-min OR low", or15["Low"].min())
        if len(or30) >= 6:
            add("or30h", "30-min OR high", or30["High"].max())
            add("or30l", "30-min OR low", or30["Low"].min())
        return {"ticker": ticker, "session": today.isoformat(), "prev_session": prev_day.isoformat() if prev_day else None,
                "levels": levels, "today": _hl(tod_reg), "premarket": _hl(pre)}
    return get_or_fetch(f"levels:{ticker}", _fetch, ttl=120)


# ── Stocks in play ───────────────────────────────────────────────────────

def _session_fraction(now: datetime) -> float:
    """Share of the regular session elapsed (for time-adjusted relative volume)."""
    minutes = (now.hour * 60 + now.minute) - (9 * 60 + 30)
    if now.weekday() >= 5 or minutes >= 390 or minutes < 0:
        return 1.0
    return max(minutes / 390, 0.05)


def _screen(direction: str) -> list[dict]:
    op = "gt" if direction == "up" else "lt"
    q = EquityQuery("and", [
        EquityQuery(op, ["percentchange", 3 if direction == "up" else -3]),
        EquityQuery("eq", ["region", "us"]),
        EquityQuery("gt", ["intradayprice", 2]),
        EquityQuery("gt", ["dayvolume", 300_000]),
    ])
    return yf.screen(q, sortField="percentchange", sortAsc=direction != "up", size=100).get("quotes", [])


_ROUNDUP = ("top gainers", "top movers", "what's going on", "stocks moving", "biggest movers", "mid-day movers",
            "premarket movers", "after hours movers", "stocks to watch", "most active stocks", "are moving",
            "movers in", "stocks making")


def _catalyst(sym: str, name: str, earnings_ts) -> dict | None:
    now = datetime.now(timezone.utc)
    if earnings_ts and abs(now.timestamp() - earnings_ts) < 36 * 3600:
        return {"headline": "Earnings report", "source": "calendar", "url": None, "kind": "earnings"}
    news = [a for a in finnhub_company_news(sym, days=2)
            if a.get("headline") and not any(g in a["headline"].lower() for g in _ROUNDUP)]
    if not news:
        return None
    word = next((w for w in (name or "").split() if len(w) >= 3), sym).lower()
    specific = [a for a in news if sym in a["headline"] or word in a["headline"].lower()]
    n = max(specific or news, key=lambda a: a.get("datetime") or 0)
    return {"headline": n.get("headline"), "source": n.get("source"), "url": n.get("url"), "kind": "news",
            "time": datetime.fromtimestamp(n["datetime"], timezone.utc).isoformat() if n.get("datetime") else None}


def stocks_in_play(limit: int = 40) -> dict:
    def _fetch():
        now = datetime.now(ET)
        frac = _session_fraction(now)
        quotes = {}
        for direction in ("up", "down"):
            try:
                for q in _screen(direction):
                    quotes[q["symbol"]] = q
            except Exception as e:
                log.warning("In-play screen %s failed: %s", direction, e)
        try:
            for q in yf.screen("most_actives", count=100).get("quotes", []):
                quotes.setdefault(q["symbol"], q)
        except Exception as e:
            log.info("most_actives failed: %s", e)

        rows = []
        for sym, q in quotes.items():
            if q.get("quoteType") not in (None, "EQUITY") or "." in sym:
                continue
            price, prev = q.get("regularMarketPrice"), q.get("regularMarketPreviousClose")
            vol = q.get("regularMarketVolume") or 0
            avg = q.get("averageDailyVolume10Day") or q.get("averageDailyVolume3Month") or 0
            if not price or not prev or avg < 50_000:
                continue
            rvol = vol / (avg * frac)
            gap = (q["regularMarketOpen"] / prev - 1) * 100 if q.get("regularMarketOpen") else None
            chg = q.get("regularMarketChangePercent") or 0
            pre = q.get("preMarketChangePercent")
            post = q.get("postMarketChangePercent")
            score = rvol * max(abs(chg), abs(pre or 0), abs(gap or 0))
            if rvol < 1.5 and abs(gap or 0) < 4 and abs(pre or 0) < 4:
                continue
            rows.append({
                "symbol": sym, "name": q.get("shortName") or sym, "price": round(price, 2),
                "change_pct": round(chg, 2), "gap_pct": None if gap is None else round(gap, 2),
                "premarket_pct": None if pre is None else round(pre, 2),
                "postmarket_pct": None if post is None else round(post, 2),
                "volume": vol, "avg_volume": avg, "rvol": round(rvol, 1),
                "market_cap": q.get("marketCap"), "shares_out": q.get("sharesOutstanding"),
                "day_high": q.get("regularMarketDayHigh"), "day_low": q.get("regularMarketDayLow"),
                "earnings_ts": q.get("earningsTimestamp"), "score": round(score, 1),
            })
        rows.sort(key=lambda r: r["score"], reverse=True)
        rows = rows[:limit]

        def enrich(ir):
            i, r = ir
            try:
                r["catalyst"] = _catalyst(r["symbol"], r["name"], r.pop("earnings_ts", None))
            except Exception:
                r["catalyst"] = None
            if i < 20:
                si = finra_short_interest(r["symbol"])
                if si and si[-1].get("short_shares") and r.get("shares_out"):
                    r["short_pct"] = round(si[-1]["short_shares"] / r["shares_out"] * 100, 1)
                    r["days_to_cover"] = si[-1].get("days_to_cover")
            return r

        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(enrich, enumerate(rows)))
        state = ("pre-market" if now.weekday() < 5 and dtime(4) <= now.time() < OPEN else
                 "open" if now.weekday() < 5 and OPEN <= now.time() < CLOSE else "closed")
        return {"rows": rows, "market_state": state, "session_elapsed_pct": round(frac * 100),
                "screened": len(quotes), "as_of": now.isoformat(timespec="seconds")}
    return get_or_fetch("in-play", _fetch, ttl=180)
