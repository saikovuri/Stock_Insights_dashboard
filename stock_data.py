import yfinance as yf
import pandas as pd


def get_stock_data(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """Fetch historical OHLCV data for a ticker."""
    stock = yf.Ticker(ticker)
    df = stock.history(period=period, interval=interval)
    if df.empty:
        raise ValueError(f"No data found for ticker '{ticker}'")
    return df


def get_key_metrics(ticker: str) -> dict:
    """Return key financial metrics for a ticker."""
    stock = yf.Ticker(ticker)
    info = stock.info

    price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
    prev_close = info.get("previousClose", 0)
    change = price - prev_close if price and prev_close else 0
    change_pct = (change / prev_close * 100) if prev_close else 0

    return {
        "name": info.get("shortName", ticker),
        "sector": info.get("sector", "N/A"),
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
