import yfinance as yf
import pandas as pd
import numpy as np
import time
import threading

# ── Simple TTL cache for metrics ─────────────────────────────────────────
_metrics_cache = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 60  # seconds


def get_stock_data(ticker: str, period: str = "6mo", interval: str = "1d",
                   prepost: bool = False) -> pd.DataFrame:
    """Fetch historical OHLCV data for a ticker."""
    stock = yf.Ticker(ticker)
    df = stock.history(period=period, interval=interval, prepost=prepost)
    if df.empty:
        raise ValueError(f"No data found for ticker '{ticker}'")
    return df


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

    # VWAP (cumulative intraday approximation)
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    df["vwap"] = (typical_price * df["Volume"]).cumsum() / df["Volume"].cumsum()

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


def get_key_metrics(ticker: str) -> dict:
    """Return key financial metrics for a ticker (cached for 60s)."""
    now = time.time()
    with _cache_lock:
        if ticker in _metrics_cache:
            cached, ts = _metrics_cache[ticker]
            if now - ts < _CACHE_TTL:
                return cached

    stock = yf.Ticker(ticker)
    info = stock.info

    price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
    prev_close = info.get("previousClose", 0)
    change = price - prev_close if price and prev_close else 0
    change_pct = (change / prev_close * 100) if prev_close else 0

    # Resolve sector: stocks have sector, ETFs have category
    raw_sector = info.get("sector") or info.get("category") or "N/A"
    result = {
        "name": info.get("shortName", ticker),
        "sector": raw_sector,
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
        "pe_ratio": info.get("trailingPE", None),
        "forward_pe": info.get("forwardPE", None),
        "eps": info.get("trailingEps", None),
        "dividend_yield": info.get("dividendYield", None),
        "52w_high": info.get("fiftyTwoWeekHigh", 0),
        "52w_low": info.get("fiftyTwoWeekLow", 0),
        "50d_avg": info.get("fiftyDayAverage", 0),
        "200d_avg": info.get("twoHundredDayAverage", 0),
        "beta": info.get("beta", None),
    }
    with _cache_lock:
        _metrics_cache[ticker] = (result, now)
    return result


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
