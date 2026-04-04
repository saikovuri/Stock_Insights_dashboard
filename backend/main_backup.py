from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from stock_data import get_stock_data, get_key_metrics, format_large_number, compute_indicators
from news_sentiment import fetch_news, aggregate_sentiment
from ai_summary import get_ai_summary
from portfolio import (add_holding, remove_holding, get_holdings, get_portfolio_summary,
                      get_history, add_option, remove_option, get_options, get_options_summary,
                      update_holding, delete_holding, update_option, delete_option)
from alerts import check_alerts

app = FastAPI(title="Stock Insights API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ───────────────────────────────────────────────

class HoldingRequest(BaseModel):
    ticker: str
    shares: float
    price: float


class OptionRequest(BaseModel):
    ticker: str
    option_type: str  # 'call' or 'put'
    strike: float
    expiry: str  # YYYY-MM-DD
    premium: float
    contracts: int = 1
    position: str = "long"  # 'long' or 'short'


class HoldingUpdateRequest(BaseModel):
    ticker: str
    shares: float
    price: float


class OptionUpdateRequest(BaseModel):
    ticker: str
    option_type: str
    strike: float
    expiry: str
    premium: float
    contracts: int = 1
    position: str = "long"


# ── Stock endpoints ─────────────────────────────────────────────────────────

@app.get("/api/stock/{ticker}/metrics")
def stock_metrics(ticker: str):
    try:
        metrics = get_key_metrics(ticker.upper())
        metrics["market_cap_fmt"] = format_large_number(metrics.get("market_cap"))
        return metrics
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/stock/{ticker}/history")
def stock_history(
    ticker: str,
    period: str = Query("6mo", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|max)$"),
    interval: str = Query("1d", pattern="^(1m|2m|5m|15m|30m|1h|1d|5d|1wk|1mo)$"),
    prepost: bool = Query(False),
):
    try:
        df = get_stock_data(ticker.upper(), period=period, interval=interval, prepost=prepost)
        df = compute_indicators(df)
        records = []
        indicator_keys = [
            "sma_10", "sma_20", "sma_50", "sma_100", "sma_200",
            "ema_9", "ema_12", "ema_21", "ema_26", "ema_50",
            "macd", "macd_signal", "macd_hist",
            "rsi",
            "bb_upper", "bb_mid", "bb_lower",
            "vwap",
            "stoch_k", "stoch_d",
            "atr",
        ]
        for ts, row in df.iterrows():
            date_fmt = "%Y-%m-%d %H:%M" if interval in ("1m","2m","5m","15m","30m","1h") else "%Y-%m-%d"
            rec = {
                "date": ts.strftime(date_fmt),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"]),
            }
            for k in indicator_keys:
                v = row.get(k)
                rec[k] = round(float(v), 2) if v is not None and not (isinstance(v, float) and (v != v)) else None
            records.append(rec)
        return records
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── News & sentiment ────────────────────────────────────────────────────────

@app.get("/api/stock/{ticker}/news")
def stock_news(ticker: str):
    try:
        metrics = get_key_metrics(ticker.upper())
        news = fetch_news(ticker.upper(), company_name=metrics.get("name", ""))
        sentiment = aggregate_sentiment(news)
        return {"articles": news, "sentiment": sentiment}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── AI summary ──────────────────────────────────────────────────────────────

@app.get("/api/stock/{ticker}/summary")
def stock_summary(ticker: str):
    try:
        metrics = get_key_metrics(ticker.upper())
        news = fetch_news(ticker.upper(), company_name=metrics.get("name", ""))
        sentiment = aggregate_sentiment(news)
        summary = get_ai_summary(metrics, sentiment, news)
        return {"summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Alerts ───────────────────────────────────────────────────────────────────

@app.get("/api/stock/{ticker}/alerts")
def stock_alerts(ticker: str):
    try:
        metrics = get_key_metrics(ticker.upper())
        alerts = check_alerts(metrics)
        return alerts
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Portfolio ────────────────────────────────────────────────────────────────

@app.get("/api/portfolio")
def portfolio_list():
    return get_holdings()


@app.get("/api/portfolio/summary")
def portfolio_summary_endpoint():
    holdings = get_holdings()
    if not holdings:
        return {
            "total_invested": 0, "total_current": 0,
            "total_pnl": 0, "total_pnl_pct": 0, "holdings": [],
        }

    current_prices = {}
    for h in holdings:
        try:
            m = get_key_metrics(h["ticker"])
            current_prices[h["ticker"]] = m["price"]
        except Exception:
            current_prices[h["ticker"]] = h["buy_price"]

    return get_portfolio_summary(current_prices)


@app.post("/api/portfolio/buy")
def portfolio_buy(req: HoldingRequest):
    holding = add_holding(req.ticker, req.shares, req.price)
    return holding


@app.post("/api/portfolio/sell")
def portfolio_sell(req: HoldingRequest):
    result = remove_holding(req.ticker, req.shares, req.price)
    if result is None:
        raise HTTPException(status_code=404, detail=f"{req.ticker} not found in portfolio")
    return result


@app.get("/api/portfolio/history")
def portfolio_history():
    return get_history()


@app.put("/api/portfolio/{index}")
def portfolio_edit(index: int, req: HoldingUpdateRequest):
    result = update_holding(index, req.ticker, req.shares, req.price)
    if result is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    return result


@app.delete("/api/portfolio/{index}")
def portfolio_delete(index: int):
    result = delete_holding(index)
    if result is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    return result


# ── Options ──────────────────────────────────────────────────────────────────

@app.get("/api/portfolio/options")
def options_list():
    return get_options()


@app.get("/api/portfolio/options/summary")
def options_summary_endpoint():
    options = get_options()
    if not options:
        return {"total_cost": 0, "total_value": 0, "total_pnl": 0, "total_pnl_pct": 0, "options": []}

    current_prices = {}
    for o in options:
        if o["ticker"] not in current_prices:
            try:
                m = get_key_metrics(o["ticker"])
                p = m.get("price", 0)
                if not p or p == 0:
                    # Try fast quote as fallback
                    import yfinance as yf
                    fast = yf.Ticker(o["ticker"]).fast_info
                    p = getattr(fast, "last_price", 0) or 0
                current_prices[o["ticker"]] = p if p else o["strike"]
            except Exception:
                # Last resort: use yfinance fast_info
                try:
                    import yfinance as yf
                    fast = yf.Ticker(o["ticker"]).fast_info
                    current_prices[o["ticker"]] = getattr(fast, "last_price", o["strike"]) or o["strike"]
                except Exception:
                    current_prices[o["ticker"]] = o["strike"]

    return get_options_summary(current_prices)


@app.post("/api/portfolio/options/buy")
def options_buy(req: OptionRequest):
    option = add_option(req.ticker, req.option_type, req.strike, req.expiry, req.premium, req.contracts, req.position)
    return option


@app.post("/api/portfolio/options/close")
def options_close(req: OptionRequest):
    result = remove_option(req.ticker, req.option_type, req.strike, req.expiry, req.premium, req.contracts, req.position)
    if result is None:
        raise HTTPException(status_code=404, detail="Option not found in portfolio")
    return result


@app.put("/api/portfolio/options/{index}")
def options_edit(index: int, req: OptionUpdateRequest):
    result = update_option(index, req.ticker, req.option_type, req.strike, req.expiry, req.premium, req.contracts, req.position)
    if result is None:
        raise HTTPException(status_code=404, detail="Option not found")
    return result


@app.delete("/api/portfolio/options/{index}")
def options_delete(index: int):
    result = delete_option(index)
    if result is None:
        raise HTTPException(status_code=404, detail="Option not found")
    return result
