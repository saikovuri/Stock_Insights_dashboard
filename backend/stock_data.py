import logging
from datetime import datetime, timezone

import yfinance as yf
import pandas as pd
import numpy as np
from cache import get_or_fetch
from providers import (
    finnhub_enabled, finnhub_quote, finnhub_profile, finnhub_basic_financials, twelvedata_history,
)

log = logging.getLogger(__name__)

# ── Cache TTLs (seconds) ─────────────────────────────────────────────────
METRICS_TTL = 300    # 5 minutes
HISTORY_TTL = 120    # 2 minutes


def get_stock_data(ticker: str, period: str = "6mo", interval: str = "1d",
                   prepost: bool = False) -> pd.DataFrame:
    """Fetch historical OHLCV data: Yahoo first, Twelve Data fallback (cached, deduplicated)."""
    key = f"history:{ticker}:{period}:{interval}:{prepost}"

    def _fetch():
        try:
            df = yf.Ticker(ticker).history(period=period, interval=interval, prepost=prepost)
        except Exception as e:
            log.warning("yfinance history failed for %s: %s", ticker, e)
            df = None
        if df is None or df.empty:
            df = twelvedata_history(ticker, period, interval)
        if df is not None and not df.empty:
            df = df.dropna(subset=["Open", "High", "Low", "Close"])
        if df is None or df.empty:
            raise ValueError(f"No data found for ticker '{ticker}'")
        return df

    return get_or_fetch(key, _fetch, ttl=HISTORY_TTL)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical indicators to a price DataFrame."""
    close = df["Close"]

    # Simple Moving Averages
    df["sma_10"] = close.rolling(10).mean()
    df["sma_20"] = close.rolling(20).mean()
    df["sma_50"] = close.rolling(50).mean()
    df["sma_100"] = close.rolling(100).mean()
    df["sma_200"] = close.rolling(200).mean()

    # Exponential Moving Averages
    df["ema_9"] = close.ewm(span=9, adjust=False).mean()
    df["ema_12"] = close.ewm(span=12, adjust=False).mean()
    df["ema_21"] = close.ewm(span=21, adjust=False).mean()
    df["ema_26"] = close.ewm(span=26, adjust=False).mean()
    df["ema_50"] = close.ewm(span=50, adjust=False).mean()

    # MACD
    df["macd"] = df["ema_12"] - df["ema_26"]
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # RSI (14-period)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # Bollinger Bands (20-period, 2 std)
    df["bb_mid"] = df["sma_20"]
    bb_std = close.rolling(20, min_periods=20).std(ddof=0)
    df["bb_upper"] = df["bb_mid"] + 2 * bb_std
    df["bb_lower"] = df["bb_mid"] - 2 * bb_std

    # VWAP resets each session, so it is only meaningful on intraday bars
    session = pd.Series(df.index.date, index=df.index)
    if session.duplicated().any():
        typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
        volume = df["Volume"].replace(0, np.nan)
        df["vwap"] = (typical_price * volume).groupby(session).cumsum() / volume.groupby(session).cumsum()
    else:
        df["vwap"] = np.nan

    # Stochastic Oscillator (%K 14, %D 3)
    low14 = df["Low"].rolling(14).min()
    high14 = df["High"].rolling(14).max()
    df["stoch_k"] = 100 * (close - low14) / (high14 - low14).replace(0, np.nan)
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()

    # ATR (14-period Average True Range)
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - close.shift()).abs()
    low_close = (df["Low"] - close.shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = true_range.ewm(span=14, adjust=False).mean()

    return df


def _yf_metrics(ticker: str) -> dict:
    info = yf.Ticker(ticker).info or {}
    price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
    if not price:
        raise ValueError(f"No data found for ticker '{ticker}'")
    prev_close = info.get("previousClose", 0)
    change = price - prev_close if price and prev_close else 0
    change_pct = (change / prev_close * 100) if prev_close else 0
    return {
        "name": info.get("shortName", ticker),
        "sector": info.get("sector") or info.get("category") or "N/A",
        "industry": info.get("industry", "N/A"),
        "price": price,
        "previous_close": prev_close,
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "open": info.get("open", 0),
        "day_high": info.get("dayHigh", 0),
        "day_low": info.get("dayLow", 0),
        "volume": info.get("volume", 0),
        "avg_volume": info.get("averageVolume", 0),
        "market_cap": info.get("marketCap", 0),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "eps": info.get("trailingEps"),
        "dividend_yield": info.get("dividendYield"),  # already a percent in yfinance >= 0.2.54
        "52w_high": info.get("fiftyTwoWeekHigh", 0),
        "52w_low": info.get("fiftyTwoWeekLow", 0),
        "50d_avg": info.get("fiftyDayAverage", 0),
        "200d_avg": info.get("twoHundredDayAverage", 0),
        "beta": info.get("beta"),
    }


def _finnhub_metrics(ticker: str) -> dict | None:
    q = finnhub_quote(ticker)
    p = finnhub_profile(ticker)
    if not q or not p:
        return None
    m = finnhub_basic_financials(ticker) or {}

    out = {
        "name": p.get("name", ticker),
        "sector": p.get("finnhubIndustry") or "N/A",
        "industry": p.get("finnhubIndustry") or "N/A",
        "price": q["c"],
        "previous_close": q.get("pc", 0),
        "change": round(q.get("d") or 0, 2),
        "change_pct": round(q.get("dp") or 0, 2),
        "open": q.get("o", 0),
        "day_high": q.get("h", 0),
        "day_low": q.get("l", 0),
        "volume": 0,
        "avg_volume": int((m.get("3MonthAverageTradingVolume") or 0) * 1_000_000),
        "market_cap": (p.get("marketCapitalization") or 0) * 1_000_000,
        "pe_ratio": m.get("peTTM") or m.get("peBasicExclExtraTTM"),
        "forward_pe": m.get("forwardPE"),
        "eps": m.get("epsTTM") or m.get("epsBasicExclExtraItemsTTM"),
        "dividend_yield": m.get("currentDividendYieldTTM"),
        "52w_high": m.get("52WeekHigh", 0),
        "52w_low": m.get("52WeekLow", 0),
        "50d_avg": 0,
        "200d_avg": 0,
        "beta": m.get("beta"),
    }

    # Volume and moving averages come from daily bars (not in Finnhub's free quote)
    try:
        hist = get_stock_data(ticker, period="1y", interval="1d")
        close = hist["Close"]
        out["volume"] = int(hist["Volume"].iloc[-1])
        if not out["avg_volume"]:
            out["avg_volume"] = int(hist["Volume"].tail(63).mean())
        out["50d_avg"] = round(float(close.tail(50).mean()), 2)
        out["200d_avg"] = round(float(close.tail(200).mean()), 2)
    except Exception as e:
        log.info("History unavailable for %s metrics: %s", ticker, e)
    return out


def get_key_metrics(ticker: str) -> dict:
    """Key metrics: Finnhub (real-time, reliable) with yfinance fallback. Cached 5 min."""
    def _fetch():
        metrics = None
        if finnhub_enabled():
            metrics = _finnhub_metrics(ticker)
        metrics = metrics or _yf_metrics(ticker)
        # Provider 52-week ranges can lag today's session; today's trading must stay inside the range.
        session = [v for v in (metrics.get("price"), metrics.get("day_high"), metrics.get("day_low")) if v]
        if session:
            if metrics.get("52w_high"):
                metrics["52w_high"] = max(metrics["52w_high"], *session)
            if metrics.get("52w_low"):
                metrics["52w_low"] = min(metrics["52w_low"], *session)
        metrics["as_of"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return metrics

    return get_or_fetch(f"metrics:{ticker}", _fetch, ttl=METRICS_TTL)


def get_quote(ticker: str) -> dict:
    """Lightweight price quote for batch views (one Finnhub call when cached profile exists)."""
    q = finnhub_quote(ticker) if finnhub_enabled() else None
    if q:
        p = finnhub_profile(ticker) or {}
        return {"ticker": ticker, "name": p.get("name", ticker), "price": q["c"],
                "change_pct": round(q.get("dp") or 0, 2), "previous_close": q.get("pc")}
    m = get_key_metrics(ticker)
    return {"ticker": ticker, "name": m.get("name", ticker), "price": m.get("price"),
            "change_pct": m.get("change_pct"), "previous_close": m.get("previous_close")}


def _r(v, nd=2):
    try:
        f = float(v)
        return None if np.isnan(f) else round(f, nd)
    except (TypeError, ValueError):
        return None


def get_daily_indicators(ticker: str) -> pd.DataFrame:
    """1y of daily bars with indicators (cached 10 min). Treat as read-only."""
    return get_or_fetch(f"daily-ind:{ticker}",
                        lambda: compute_indicators(get_stock_data(ticker, period="1y", interval="1d").copy()),
                        ttl=600)


def get_technical_snapshot(ticker: str) -> dict:
    """Latest indicator values + returns from 1y of daily bars, for AI prompts and alerts."""
    def _fetch():
        df = get_daily_indicators(ticker)
        last = df.iloc[-1]
        close = df["Close"]
        price = float(close.iloc[-1])

        def _ret(bars):
            return _r((price / float(close.iloc[-bars - 1]) - 1) * 100) if len(close) > bars else None

        log_ret = np.log(close / close.shift(1)).dropna()
        rv20 = _r(log_ret.tail(20).std() * np.sqrt(252) * 100, 1) if len(log_ret) >= 20 else None
        high_1y = float(close.max())
        sma50, sma200 = _r(last.get("sma_50")), _r(last.get("sma_200"))
        if sma50 and sma200:
            trend = "uptrend" if price > sma50 > sma200 else "downtrend" if price < sma50 < sma200 else "mixed"
        else:
            trend = "insufficient data"
        return {
            "price": _r(price),
            "rsi_14": _r(last.get("rsi"), 1),
            "macd": _r(last.get("macd"), 3),
            "macd_signal": _r(last.get("macd_signal"), 3),
            "macd_hist": _r(last.get("macd_hist"), 3),
            "sma_20": _r(last.get("sma_20")),
            "sma_50": sma50,
            "sma_200": sma200,
            "bb_upper": _r(last.get("bb_upper")),
            "bb_lower": _r(last.get("bb_lower")),
            "stoch_k": _r(last.get("stoch_k"), 1),
            "atr_14": _r(last.get("atr")),
            "atr_pct": _r(float(last.get("atr")) / price * 100) if _r(last.get("atr")) else None,
            "realized_vol_20d_pct": rv20,
            "return_1m_pct": _ret(21),
            "return_3m_pct": _ret(63),
            "return_6m_pct": _ret(126),
            "return_1y_pct": _ret(len(close) - 1) if len(close) > 200 else None,
            "pct_from_1y_high": _r((price / high_1y - 1) * 100),
            "trend": trend,
        }

    return get_or_fetch(f"tech:{ticker}", _fetch, ttl=600)


def format_large_number(num) -> str:
    """Format large numbers for display (e.g., 1.2B, 450M)."""
    if num is None:
        return "N/A"
    if num >= 1_000_000_000_000:
        return f"${num / 1_000_000_000_000:.2f}T"
    if num >= 1_000_000_000:
        return f"${num / 1_000_000_000:.2f}B"
    if num >= 1_000_000:
        return f"${num / 1_000_000:.2f}M"
    return f"${num:,.0f}"
