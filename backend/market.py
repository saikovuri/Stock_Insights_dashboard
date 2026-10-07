"""Market overview: indices, volatility, sector heatmap, top movers and market regime."""

import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import yfinance as yf

from cache import get_or_fetch
from stock_data import get_quote, get_stock_data

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

INDEXES = [("SPY", "S&P 500 (SPY)"), ("QQQ", "Nasdaq 100 (QQQ)"), ("DIA", "Dow 30 (DIA)"), ("IWM", "Russell 2000 (IWM)")]
SECTORS = [
    ("XLK", "Technology"), ("XLC", "Communication"), ("XLY", "Consumer Disc."), ("XLF", "Financials"),
    ("XLV", "Health Care"), ("XLI", "Industrials"), ("XLE", "Energy"), ("XLP", "Staples"),
    ("XLB", "Materials"), ("XLU", "Utilities"), ("XLRE", "Real Estate"),
]
SCREENS = {"gainers": "day_gainers", "losers": "day_losers", "active": "most_actives"}


def market_status() -> dict:
    now = datetime.now(ET)
    minutes = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        state = "closed"
    elif 4 * 60 <= minutes < 9 * 60 + 30:
        state = "pre-market"
    elif 9 * 60 + 30 <= minutes < 16 * 60:
        state = "open"
    elif 16 * 60 <= minutes < 20 * 60:
        state = "after-hours"
    else:
        state = "closed"
    return {"state": state, "time_et": now.strftime("%a %I:%M %p ET")}


def _returns(ticker: str) -> dict:
    try:
        close = get_stock_data(ticker, period="1y", interval="1d")["Close"]
        last = float(close.iloc[-1])
        out = {}
        for label, bars in (("r1w", 5), ("r1m", 21), ("r3m", 63)):
            if len(close) > bars:
                out[label] = round((last / float(close.iloc[-bars - 1]) - 1) * 100, 2)
        out["above_50d"] = last > float(close.tail(50).mean())
        out["above_200d"] = last > float(close.tail(200).mean()) if len(close) >= 200 else None
        return out
    except Exception:
        return {}


def _tile(sym: str, name: str, with_returns: bool = True) -> dict:
    try:
        q = get_quote(sym)
        tile = {"symbol": sym, "name": name, "price": q.get("price"), "change_pct": q.get("change_pct")}
    except Exception:
        tile = {"symbol": sym, "name": name, "price": None, "change_pct": None}
    if with_returns:
        tile.update(_returns(sym))
    return tile


def _yahoo_index(sym: str, name: str) -> dict:
    try:
        close = get_stock_data(sym, period="5d", interval="1d")["Close"]
        last, prev = float(close.iloc[-1]), float(close.iloc[-2])
        return {"symbol": sym, "name": name, "price": round(last, 2), "change_pct": round((last / prev - 1) * 100, 2)}
    except Exception:
        return {"symbol": sym, "name": name, "price": None, "change_pct": None}


def _regime(spy: dict, vix: dict) -> dict:
    v = vix.get("price")
    trend = ("uptrend" if spy.get("above_50d") and spy.get("above_200d")
             else "downtrend" if spy.get("above_50d") is False and spy.get("above_200d") is False else "mixed")
    fear = None if v is None else "calm" if v < 15 else "normal" if v < 20 else "elevated" if v < 30 else "high fear"
    tone = {
        "uptrend": "S&P 500 is above its 50 & 200-day averages — the path of least resistance is up.",
        "downtrend": "S&P 500 is below its 50 & 200-day averages — rallies tend to get sold; size down.",
        "mixed": "S&P 500 is between its key averages — expect choppier, range-bound action.",
    }[trend]
    if fear:
        tone += f" VIX {v:.1f} ({fear})."
    return {"trend": trend, "fear": fear, "summary": tone}


def overview() -> dict:
    def _fetch():
        with ThreadPoolExecutor(max_workers=8) as pool:
            idx = list(pool.map(lambda x: _tile(*x), INDEXES))
            sectors = list(pool.map(lambda x: _tile(*x), SECTORS))
            vix, tnx = pool.map(lambda x: _yahoo_index(*x), [("^VIX", "VIX"), ("^TNX", "10Y Yield")])
        spy = next(t for t in idx if t["symbol"] == "SPY")
        if tnx.get("price") is not None and tnx["price"] > 20:
            tnx["price"] = round(tnx["price"] / 10, 3)
        return {
            "status": market_status(),
            "indexes": idx,
            "vix": vix,
            "ten_year": tnx,
            "regime": _regime(spy, vix),
            "sectors": sorted(sectors, key=lambda s: s.get("change_pct") or 0, reverse=True),
            "updated_at": datetime.now(ET).isoformat(),
        }
    return get_or_fetch("market:overview", _fetch, ttl=90)


def search_symbols(query: str) -> list[dict]:
    """Ticker or company-name lookup: S&P 500 / Nasdaq-100 directory first, then Yahoo search for everything else."""
    q = query.strip()
    if not q:
        return []

    def _fetch():
        upper, lower = q.upper(), q.lower()
        ranked = []
        try:
            from intraday import _directory
            directory = _directory()
        except Exception as error:
            log.info("Symbol directory unavailable: %s", error)
            directory = {}
        for symbol, info in directory.items():
            name = info.get("name") or ""
            rank = (0 if symbol == upper else 1 if symbol.startswith(upper) else
                    2 if name.lower().startswith(lower) else 3 if lower in name.lower() else None)
            if rank is not None:
                ranked.append((rank, -(info.get("market_cap") or 0), {"symbol": symbol, "name": name or symbol,
                                                                       "exchange": None, "type": "EQUITY"}))
        results = [item for _, _, item in sorted(ranked, key=lambda r: (r[0], r[1]))][:8]
        if len(results) < 8:
            seen = {r["symbol"] for r in results}
            try:
                for quote in yf.Search(q, max_results=10, news_count=0).quotes:
                    symbol = quote.get("symbol")
                    if symbol and symbol not in seen and quote.get("quoteType") in ("EQUITY", "ETF"):
                        seen.add(symbol)
                        results.append({"symbol": symbol, "name": quote.get("shortname") or quote.get("longname") or symbol,
                                        "exchange": quote.get("exchDisp") or quote.get("exchange"),
                                        "type": quote.get("quoteType")})
            except Exception as error:
                log.info("Yahoo symbol search failed for %r: %s", q, error)
        return results[:10]
    return get_or_fetch(f"symbol-search:{q.lower()}", _fetch, ttl=24 * 3600)


def movers(kind: str) -> list[dict]:
    screen = SCREENS.get(kind)
    if not screen:
        return []

    def _fetch():
        res = yf.screen(screen, count=12)
        out = []
        for q in res.get("quotes", []):
            vol, avg = q.get("regularMarketVolume") or 0, q.get("averageDailyVolume3Month") or 0
            out.append({
                "symbol": q.get("symbol"),
                "name": q.get("shortName") or q.get("symbol"),
                "price": q.get("regularMarketPrice"),
                "change_pct": round(q.get("regularMarketChangePercent") or 0, 2),
                "volume": vol,
                "rvol": round(vol / avg, 1) if avg else None,
                "market_cap": q.get("marketCap"),
            })
        return out

    try:
        return get_or_fetch(f"market:movers:{kind}", _fetch, ttl=120)
    except Exception as e:
        log.warning("Movers screen %s failed: %s", kind, e)
        return []
