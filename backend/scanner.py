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


def _signals(df: pd.DataFrame) -> pd.DataFrame:
    """Boolean column per setup for every bar (df must already have indicators)."""
    close, high = df["Close"], df["High"]
    prior_high = high.rolling(251, min_periods=200).max().shift(1)
    rvol = df["Volume"] / df["Volume"].rolling(50).mean().shift(1)
    uptrend = (close > df["sma_200"]) & (df["sma_50"] > df["sma_200"])
    ext = close / df["ema_21"] - 1
    width = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    above = df["sma_50"] > df["sma_200"]
    cross = above & (df["sma_50"].shift(1) <= df["sma_200"].shift(1))
    return pd.DataFrame({
        "breakout": (close >= prior_high * 0.995) & (rvol >= 1.5) & (close > close.shift(1)),
        "pullback": uptrend & ext.between(-0.02, 0.015) & df["rsi"].between(40, 60),
        "squeeze": (width <= width.rolling(126, min_periods=100).quantile(0.1)) & (close > df["sma_50"]),
        "oversold": (df["rsi"] < 35) & (close > df["sma_200"]),
        "golden_cross": cross.astype(int).rolling(10, min_periods=1).max().astype(bool),
    }, index=df.index).fillna(False)


def _analyze(sym: str, df: pd.DataFrame, events: list | None = None) -> dict | None:
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
    sma50, sma200 = float(last["sma_50"]), float(last["sma_200"])
    rsi = float(last["rsi"])
    uptrend = price > sma200 and sma50 > sma200

    sig = _signals(df)
    setups = [s for s in SETUPS if bool(sig[s].iloc[-1])]
    if events is not None:
        _record_events(sym, df, sig, events)

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


HORIZONS = (5, 10, 20)
BACKTEST_BARS = 252


def _record_events(sym: str, df: pd.DataFrame, sig: pd.DataFrame, events: list) -> None:
    """Each new setup signal in the past year with its forward returns (for the track record)."""
    close = df["Close"]
    fwd = {h: close.shift(-h) / close - 1 for h in HORIZONS}
    start = max(len(df) - BACKTEST_BARS, 0)
    for s in SETUPS:
        # A signal counts once; it must not have fired in the prior 10 bars
        recent = sig[s].shift(1, fill_value=False).astype(int).rolling(10, min_periods=1).max().astype(bool)
        fresh = sig[s] & ~recent
        for i in np.flatnonzero(fresh.values[start:]) + start:
            events.append((s, df.index[i], {h: (None if pd.isna(fwd[h].iloc[i]) else float(fwd[h].iloc[i]))
                                            for h in HORIZONS}))


def _track_record(events: list, spy: pd.Series | None) -> dict:
    spy_fwd = {h: spy.shift(-h) / spy - 1 for h in HORIZONS} if spy is not None else {}
    out = {}
    for s in SETUPS:
        ev = [e for e in events if e[0] == s]
        stats = {"signals": len(ev)}
        for h in HORIZONS:
            rets = [e[2][h] for e in ev if e[2][h] is not None]
            if not rets:
                continue
            stats[f"avg_{h}d"] = round(float(np.mean(rets)) * 100, 2)
            stats[f"win_{h}d"] = round(float(np.mean([r > 0 for r in rets])) * 100)
            stats[f"n_{h}d"] = len(rets)
            if h == 20:
                stats["median_20d"] = round(float(np.median(rets)) * 100, 2)
                stats["hit5_20d"] = round(float(np.mean([r >= 0.05 for r in rets])) * 100)
                if spy_fwd:
                    ex = [r - spy_fwd[20].get(e[1], np.nan) for e, r in zip([e for e in ev if e[2][20] is not None], rets)]
                    ex = [x for x in ex if not pd.isna(x)]
                    if ex:
                        stats["excess_20d"] = round(float(np.mean(ex)) * 100, 2)
        out[s] = stats
    return out


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
        rows, events = [], []
        for i in range(0, len(symbols), BATCH):
            batch = symbols[i:i + BATCH]
            try:
                data = yf.download(batch, period="2y", interval="1d", group_by="ticker",
                                   auto_adjust=True, threads=True, progress=False)
            except Exception as e:
                log.warning("Scan batch %d failed: %s", i, e)
                continue
            for sym in batch:
                try:
                    r = _analyze(sym, data[sym], events)
                except Exception:
                    r = None
                if r:
                    rows.append({**r, "name": meta[sym]["name"], "sector": meta[sym]["sector"]})
            del data
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

        try:
            spy = get_stock_data("SPY", period="2y", interval="1d")["Close"]
            spy.index = spy.index.tz_localize(None) if spy.index.tz is not None else spy.index
        except Exception:
            spy = None
        track = _track_record(events, spy)

        result = {"rows": rows, "sectors": sector_rows, "universe": "S&P 500", "rs_dist": rs_dist,
                  "track_record": track, "track_period_days": BACKTEST_BARS,
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
