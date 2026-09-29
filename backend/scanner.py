"""Nightly S&P 500 setup scanner with IBD-style relative strength ratings."""

import io
import logging
import threading
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from alerts import _cross_date
from database import kv_get, kv_set
from stock_data import compute_indicators, get_stock_data

log = logging.getLogger(__name__)

SCAN_KEY = "scan:sp500"
UNIVERSE_KEY = "universe:sp500"
BATCH = 100
_lock = threading.Lock()
_running = False

SETUPS = {
    "breakout": "Breakout to 52-week high on heavy volume",
    "pullback": "Pullback to the 21-day EMA in an uptrend",
    "squeeze": "Volatility squeeze (tightest Bollinger Bands in 6 months)",
    "oversold": "Oversold (RSI < 35) while above the 200-day",
    "golden_cross": "Fresh golden cross (50-day over 200-day)",
}

_FALLBACK = [("AAPL", "Apple", "Information Technology"), ("MSFT", "Microsoft", "Information Technology"),
             ("NVDA", "Nvidia", "Information Technology"), ("AMZN", "Amazon", "Consumer Discretionary"),
             ("GOOGL", "Alphabet", "Communication Services"), ("META", "Meta Platforms", "Communication Services"),
             ("JPM", "JPMorgan Chase", "Financials"), ("XOM", "ExxonMobil", "Energy"),
             ("UNH", "UnitedHealth", "Health Care"), ("CAT", "Caterpillar", "Industrials")]


def universe() -> list[dict]:
    cached = kv_get(UNIVERSE_KEY)
    if cached and (datetime.now(timezone.utc) - _parse_ts(cached["updated_at"])).days < 7:
        return cached["data"]
    try:
        html = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                            headers={"User-Agent": "Mozilla/5.0 StockInsights"}, timeout=20).text
        t = pd.read_html(io.StringIO(html))[0]
        data = [{"symbol": str(r["Symbol"]).replace(".", "-"), "name": r["Security"], "sector": r["GICS Sector"]}
                for _, r in t.iterrows()]
        kv_set(UNIVERSE_KEY, data)
        return data
    except Exception as e:
        log.warning("S&P 500 list unavailable: %s", e)
        return cached["data"] if cached else [{"symbol": s, "name": n, "sector": sec} for s, n, sec in _FALLBACK]


def _parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ret(close: pd.Series, bars: int) -> float | None:
    # A "1y" download has ~251 bars, so treat the 12-month lookback as "oldest available"
    if bars >= 250 and len(close) >= 240:
        bars = min(bars, len(close) - 1)
    return float(close.iloc[-1] / close.iloc[-bars - 1] - 1) if len(close) > bars else None


def _analyze(sym: str, df: pd.DataFrame) -> dict | None:
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < 210:
        return None
    df = compute_indicators(df.copy())
    last, close = df.iloc[-1], df["Close"]
    price = float(last["Close"])
    r3, r6, r9, r12 = (_ret(close, n) for n in (63, 126, 189, 252))
    rs_raw = sum(w * (r or 0) for w, r in ((0.4, r3), (0.2, r6), (0.2, r9), (0.2, r12)))
    vol50 = float(df["Volume"].tail(51).head(50).mean()) or None
    rvol = float(last["Volume"]) / vol50 if vol50 else None
    atr = float(last["atr"])
    sma50, sma200, ema21, rsi = float(last["sma_50"]), float(last["sma_200"]), float(last["ema_21"]), float(last["rsi"])
    prior_high = float(df["High"].iloc[-252:-1].max())
    uptrend = price > sma200 and sma50 > sma200

    width = ((df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]).dropna().tail(126)
    setups = []
    if price >= prior_high * 0.995 and (rvol or 0) >= 1.5 and price > float(df["Close"].iloc[-2]):
        setups.append("breakout")
    if uptrend and -0.02 <= price / ema21 - 1 <= 0.015 and 40 <= rsi <= 60:
        setups.append("pullback")
    if len(width) >= 100 and width.iloc[-1] <= width.quantile(0.1) and price > sma50:
        setups.append("squeeze")
    if rsi < 35 and price > sma200:
        setups.append("oversold")
    if _cross_date(df["sma_50"], df["sma_200"], 10, "up") is not None:
        setups.append("golden_cross")

    return {
        "symbol": sym,
        "price": round(price, 2),
        "change_pct": round((price / float(close.iloc[-2]) - 1) * 100, 2),
        "r1m": None if _ret(close, 21) is None else round(_ret(close, 21) * 100, 1),
        "r3m": None if r3 is None else round(r3 * 100, 1),
        "r12m": None if r12 is None else round(r12 * 100, 1),
        "rs_raw": rs_raw,
        "rsi": round(rsi, 1),
        "rvol": None if rvol is None else round(rvol, 2),
        "atr_pct": round(atr / price * 100, 2),
        "pct_from_high": round((price / float(df["High"].iloc[-252:].max()) - 1) * 100, 1),
        "trend": "uptrend" if uptrend else "downtrend" if price < sma200 and sma50 < sma200 else "mixed",
        "setups": setups,
        "stop": round(price - 1.5 * atr, 2),
        "target": round(price + 3 * atr, 2),
    }


def run_scan() -> dict:
    global _running
    with _lock:
        if _running:
            return {"status": "running"}
        _running = True
    started = time.time()
    try:
        uni = universe()
        meta = {u["symbol"]: u for u in uni}
        symbols = list(meta)
        rows = []
        for i in range(0, len(symbols), BATCH):
            batch = symbols[i:i + BATCH]
            try:
                data = yf.download(batch, period="1y", interval="1d", group_by="ticker",
                                   auto_adjust=True, threads=True, progress=False)
            except Exception as e:
                log.warning("Scan batch %d failed: %s", i, e)
                continue
            for sym in batch:
                try:
                    r = _analyze(sym, data[sym])
                except Exception:
                    r = None
                if r:
                    rows.append({**r, "name": meta[sym]["name"], "sector": meta[sym]["sector"]})
            time.sleep(1)

        if not rows:
            raise RuntimeError("Scan produced no results")
        ranks = pd.Series([r["rs_raw"] for r in rows]).rank(pct=True)
        rs_dist = sorted(round(r["rs_raw"], 4) for r in rows)
        for r, pct in zip(rows, ranks):
            r["rs_rating"] = int(round(1 + pct * 98))
            del r["rs_raw"]

        sectors = {}
        for r in rows:
            s = sectors.setdefault(r["sector"], {"sector": r["sector"], "rs": [], "r1m": []})
            s["rs"].append(r["rs_rating"])
            if r["r1m"] is not None:
                s["r1m"].append(r["r1m"])
        sector_rows = sorted(({"sector": k, "rs_rating": round(float(np.mean(v["rs"]))),
                               "r1m": round(float(np.mean(v["r1m"])), 1) if v["r1m"] else None,
                               "count": len(v["rs"])} for k, v in sectors.items()),
                             key=lambda s: s["rs_rating"], reverse=True)

        result = {"rows": rows, "sectors": sector_rows, "universe": "S&P 500", "rs_dist": rs_dist,
                  "updated_at": datetime.now(timezone.utc).isoformat(), "seconds": round(time.time() - started)}
        kv_set(SCAN_KEY, result)
        log.info("Setup scan complete: %d stocks in %ds", len(rows), result["seconds"])
        return result
    finally:
        with _lock:
            _running = False


def get_scan(start_if_stale: bool = True) -> dict:
    cached = kv_get(SCAN_KEY)
    stale = not cached or (datetime.now(timezone.utc) - _parse_ts(cached["data"]["updated_at"])).total_seconds() > 36 * 3600
    if stale and start_if_stale and not _running:
        threading.Thread(target=_safe_scan, daemon=True).start()
    if not cached:
        return {"status": "building", "rows": [], "sectors": []}
    return {**cached["data"], "status": "running" if _running else "ready"}


def _safe_scan():
    try:
        run_scan()
    except Exception as e:
        log.warning("Setup scan failed: %s", e)


def relative_strength(ticker: str) -> dict:
    """RS rating from the latest scan when available, else computed against the scan distribution / SPY."""
    scan = kv_get(SCAN_KEY)
    rows = scan["data"]["rows"] if scan else []
    hit = next((r for r in rows if r["symbol"] == ticker), None)

    close = get_stock_data(ticker, period="1y", interval="1d")["Close"]
    spy = get_stock_data("SPY", period="1y", interval="1d")["Close"]

    def rel(bars):
        a, b = _ret(close, bars), _ret(spy, bars)
        return None if a is None or b is None else round((a - b) * 100, 1)

    rating = hit["rs_rating"] if hit else None
    dist = scan["data"].get("rs_dist") if scan else None
    if rating is None and dist:
        r3, r6, r9, r12 = (_ret(close, n) for n in (63, 126, 189, 252))
        mine = sum(w * (r or 0) for w, r in ((0.4, r3), (0.2, r6), (0.2, r9), (0.2, r12)))
        rating = int(round(1 + np.searchsorted(dist, mine) / len(dist) * 98))

    sector_rank = None
    if hit and scan:
        sectors = scan["data"]["sectors"]
        sector_rank = next((i + 1 for i, s in enumerate(sectors) if s["sector"] == hit["sector"]), None)

    return {
        "ticker": ticker,
        "rs_rating": rating,
        "vs_spy": {"1m": rel(21), "3m": rel(63), "6m": rel(126), "12m": rel(252)},
        "sector": hit["sector"] if hit else None,
        "sector_rank": sector_rank,
        "sector_count": len(scan["data"]["sectors"]) if scan else None,
        "setups": hit["setups"] if hit else [],
        "in_universe": bool(hit),
    }
