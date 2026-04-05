from fastapi import FastAPI, HTTPException, Query, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date as _date
import re
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from stock_data import get_stock_data, get_key_metrics, format_large_number, compute_indicators
from news_sentiment import fetch_news, aggregate_sentiment
from ai_summary import get_ai_summary
from alerts import check_alerts
from auth import hash_password, verify_password, create_token, decode_token, create_refresh_token, REFRESH_EXPIRE_DAYS
from database import (
    create_user, get_user_by_username, get_user_by_username_by_id,
    get_user_holdings, add_user_holding, update_user_holding, delete_user_holding, sell_user_holding,
    sell_user_holding_by_lot,
    get_user_options, add_user_option, close_user_option, update_user_option, delete_user_option,
    get_user_transactions, get_user_watchlist, add_to_watchlist, remove_from_watchlist,
    get_closed_trades, get_closed_options,
    store_refresh_token, get_refresh_token, delete_refresh_token, delete_user_refresh_tokens,
)
from config import CORS_ORIGINS

app = FastAPI(title="Stock Insights API", version="2.0.0")

# ── Rate limiting ───────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Security headers middleware ─────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Ticker validation ───────────────────────────────────────────────────────

_TICKER_RE = re.compile(r"^[A-Za-z0-9\.\-\^]{1,10}$")

def _valid_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")
    return t


# ── Auth dependency ─────────────────────────────────────────────────────────

def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"user_id": payload["sub"], "username": payload["username"]}


# ── Request models ──────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str

class LoginRequest(BaseModel):
    username: str
    password: str

class HoldingRequest(BaseModel):
    ticker: str
    shares: float
    price: float

class OptionRequest(BaseModel):
    ticker: str
    option_type: str
    strike: float
    expiry: str
    premium: float
    contracts: int = 1
    position: str = "long"

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

class WatchlistRequest(BaseModel):
    ticker: str


# ── Auth endpoints ──────────────────────────────────────────────────────────

def _issue_tokens(user: dict) -> dict:
    """Create access + refresh tokens and return auth response."""
    from datetime import timedelta
    access = create_token(user["id"], user["username"])
    refresh = create_refresh_token()
    expires_at = (datetime.utcnow() + timedelta(days=REFRESH_EXPIRE_DAYS)).isoformat()
    store_refresh_token(user["id"], refresh, expires_at)
    return {
        "token": access,
        "refresh_token": refresh,
        "user": {"id": user["id"], "username": user["username"], "display_name": user["display_name"]},
    }


@app.post("/api/auth/register")
@limiter.limit("5/minute")
def register(request: Request, req: RegisterRequest):
    if len(req.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    hashed = hash_password(req.password)
    user = create_user(req.username.strip(), hashed, req.display_name.strip())
    if not user:
        raise HTTPException(status_code=409, detail="Username already taken")
    return _issue_tokens(user)


@app.post("/api/auth/login")
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest):
    user = get_user_by_username(req.username.strip())
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return _issue_tokens(user)


class RefreshRequest(BaseModel):
    refresh_token: str


@app.post("/api/auth/refresh")
@limiter.limit("30/minute")
def refresh(request: Request, req: RefreshRequest):
    stored = get_refresh_token(req.refresh_token)
    if not stored:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    # Check expiry
    expires = datetime.fromisoformat(str(stored["expires_at"]).replace("+00:00", "").replace("Z", ""))
    if datetime.utcnow() > expires:
        delete_refresh_token(req.refresh_token)
        raise HTTPException(status_code=401, detail="Refresh token expired")
    # Rotate: delete old, issue new pair
    user = get_user_by_username_by_id(stored["user_id"])
    if not user:
        delete_refresh_token(req.refresh_token)
        raise HTTPException(status_code=401, detail="User not found")
    delete_refresh_token(req.refresh_token)
    return _issue_tokens(user)


@app.post("/api/auth/logout")
def logout(user: dict = Depends(get_current_user)):
    delete_user_refresh_tokens(user["user_id"])
    return {"message": "Logged out"}


@app.get("/api/auth/me")
def auth_me(user: dict = Depends(get_current_user)):
    db_user = get_user_by_username(user["username"])
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": db_user["id"], "username": db_user["username"], "display_name": db_user["display_name"]}


# ── Stock endpoints (no auth needed) ───────────────────────────────────────

@app.get("/api/stock/{ticker}/metrics")
@limiter.limit("120/minute")
def stock_metrics(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        metrics = get_key_metrics(ticker)
        metrics["market_cap_fmt"] = format_large_number(metrics.get("market_cap"))
        return metrics
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


class BatchMetricsRequest(BaseModel):
    tickers: list[str]


@app.post("/api/stock/batch-metrics")
@limiter.limit("30/minute")
def batch_metrics(request: Request, req: BatchMetricsRequest):
    """Fetch metrics for multiple tickers in one request (max 30)."""
    from concurrent.futures import ThreadPoolExecutor
    tickers = [_valid_ticker(t) for t in req.tickers[:30]]
    def _fetch(t):
        try:
            m = get_key_metrics(t)
            return {"ticker": t, "price": m.get("price"), "change_pct": m.get("change_pct"), "name": m.get("name", t)}
        except Exception:
            return {"ticker": t, "price": None, "change_pct": None, "name": t}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as pool:
        results = list(pool.map(_fetch, tickers))
    return {"quotes": {r["ticker"]: r for r in results}}


@app.get("/api/stock/{ticker}/history")
@limiter.limit("60/minute")
def stock_history(
    request: Request,
    ticker: str,
    period: str = Query("6mo", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|max)$"),
    interval: str = Query("1d", pattern="^(1m|2m|5m|15m|30m|1h|1d|5d|1wk|1mo)$"),
    prepost: bool = Query(False),
):
    ticker = _valid_ticker(ticker)
    try:
        df = get_stock_data(ticker, period=period, interval=interval, prepost=prepost)
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


@app.get("/api/stock/{ticker}/news")
@limiter.limit("30/minute")
def stock_news(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        metrics = get_key_metrics(ticker)
        news = fetch_news(ticker, company_name=metrics.get("name", ""))
        sentiment = aggregate_sentiment(news)
        return {"articles": news, "sentiment": sentiment}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{ticker}/summary")
@limiter.limit("30/minute")
def stock_summary(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        metrics = get_key_metrics(ticker)
        news = fetch_news(ticker, company_name=metrics.get("name", ""))
        sentiment = aggregate_sentiment(news)
        summary = get_ai_summary(metrics, sentiment, news)
        return {"summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{ticker}/alerts")
def stock_alerts(ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        metrics = get_key_metrics(ticker)
        alerts = check_alerts(metrics)
        return alerts
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Portfolio (auth required) ──────────────────────────────────────────────

@app.get("/api/portfolio/summary")
def portfolio_summary_endpoint(user: dict = Depends(get_current_user)):
    holdings = get_user_holdings(user["user_id"])
    if not holdings:
        return {"total_invested": 0, "total_current": 0, "total_pnl": 0, "total_pnl_pct": 0, "holdings": []}

    # Batch fetch current prices — one yfinance call for all unique tickers
    import yfinance as yf
    unique_tickers = list({h["ticker"] for h in holdings})
    current_prices = {}
    try:
        if len(unique_tickers) == 1:
            data = yf.download(unique_tickers[0], period="1d", interval="1d", progress=False)
            if not data.empty:
                current_prices[unique_tickers[0]] = round(float(data["Close"].iloc[-1]), 2)
        else:
            data = yf.download(unique_tickers, period="1d", interval="1d", progress=False, group_by="ticker")
            for t in unique_tickers:
                try:
                    current_prices[t] = round(float(data[t]["Close"].iloc[-1]), 2)
                except Exception:
                    pass
    except Exception:
        pass
    # Fill any missing tickers with individual fallbacks
    for t in unique_tickers:
        if t not in current_prices:
            try:
                m = get_key_metrics(t)
                current_prices[t] = m["price"]
            except Exception:
                current_prices[t] = 0

    # Build summary from DB holdings
    total_invested = 0.0
    total_current = 0.0
    details = []
    for h in holdings:
        ticker = h["ticker"]
        shares = h["shares"]
        buy_price = h["buy_price"]
        current = current_prices.get(ticker, buy_price)
        invested = shares * buy_price
        current_val = shares * current
        pnl = current_val - invested
        pnl_pct = (pnl / invested * 100) if invested else 0
        total_invested += invested
        total_current += current_val
        details.append({
            "id": h["id"], "ticker": ticker, "shares": shares,
            "buy_price": buy_price, "current_price": current,
            "invested": round(invested, 2), "current_value": round(current_val, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
        })
    total_pnl = total_current - total_invested
    return {
        "total_invested": round(total_invested, 2),
        "total_current": round(total_current, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round((total_pnl / total_invested * 100) if total_invested else 0, 2),
        "holdings": details,
    }


@app.post("/api/portfolio/buy")
def portfolio_buy(req: HoldingRequest, user: dict = Depends(get_current_user)):
    return add_user_holding(user["user_id"], req.ticker, req.shares, req.price)


@app.post("/api/portfolio/sell")
def portfolio_sell(req: HoldingRequest, user: dict = Depends(get_current_user)):
    result = sell_user_holding(user["user_id"], req.ticker, req.shares, req.price)
    if result is None:
        raise HTTPException(status_code=404, detail=f"{req.ticker} not found in portfolio")
    return result


@app.post("/api/portfolio/sell-lot/{holding_id}")
def portfolio_sell_lot(holding_id: int, req: HoldingRequest, user: dict = Depends(get_current_user)):
    result = sell_user_holding_by_lot(user["user_id"], holding_id, req.shares, req.price)
    if result is None:
        raise HTTPException(status_code=404, detail="Lot not found")
    return result


@app.put("/api/portfolio/{holding_id}")
def portfolio_edit(holding_id: int, req: HoldingUpdateRequest, user: dict = Depends(get_current_user)):
    result = update_user_holding(user["user_id"], holding_id, req.ticker, req.shares, req.price)
    if result is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    return result


@app.delete("/api/portfolio/{holding_id}")
def portfolio_delete(holding_id: int, user: dict = Depends(get_current_user)):
    result = delete_user_holding(user["user_id"], holding_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    return result


@app.get("/api/portfolio/history")
def portfolio_history(user: dict = Depends(get_current_user)):
    return get_user_transactions(user["user_id"])


@app.get("/api/portfolio/closed")
def closed_trades_endpoint(user: dict = Depends(get_current_user)):
    trades = get_closed_trades(user["user_id"])
    total_pnl = sum(t["pnl"] for t in trades)
    return {"total_realized_pnl": round(total_pnl, 2), "trades": trades}


@app.get("/api/portfolio/options/closed")
def closed_options_endpoint(user: dict = Depends(get_current_user)):
    trades = get_closed_options(user["user_id"])
    total_pnl = sum(t["pnl"] for t in trades)
    return {"total_realized_pnl": round(total_pnl, 2), "trades": trades}


# ── Options (auth required) ────────────────────────────────────────────────

@app.get("/api/portfolio/options/summary")
def options_summary_endpoint(user: dict = Depends(get_current_user)):
    import yfinance as yf
    options = get_user_options(user["user_id"])
    if not options:
        return {"total_cost": 0, "total_value": 0, "total_pnl": 0, "total_pnl_pct": 0, "options": []}

    INDEX_MAP = {
        "SPX": "^SPX", "NDX": "^NDX", "RUT": "^RUT", "DJX": "^DJI",
        "VIX": "^VIX", "OEX": "^OEX", "XSP": "^XSP",
    }

    def _yf_ticker(ticker: str) -> str:
        return INDEX_MAP.get(ticker.upper(), ticker)

    # Fetch underlying prices (deduplicated)
    current_prices = {}
    for o in options:
        if o["ticker"] not in current_prices:
            yf_sym = _yf_ticker(o["ticker"])
            try:
                m = get_key_metrics(yf_sym)
                p = m.get("price", 0)
                if not p:
                    p = getattr(yf.Ticker(yf_sym).fast_info, "last_price", 0) or 0
                current_prices[o["ticker"]] = p if p else o["strike"]
            except Exception:
                try:
                    current_prices[o["ticker"]] = getattr(yf.Ticker(yf_sym).fast_info, "last_price", o["strike"]) or o["strike"]
                except Exception:
                    current_prices[o["ticker"]] = o["strike"]

    # Cache option chains per (ticker, expiry)
    chain_cache: dict[tuple[str, str], dict] = {}
    today = _date.today()

    def _get_market_price(ticker: str, opt_type: str, strike: float, expiry: str) -> dict:
        yf_sym = _yf_ticker(ticker)
        key = (yf_sym, expiry)
        if key not in chain_cache:
            try:
                t = yf.Ticker(yf_sym)
                available = t.options
                if expiry in available:
                    chain = t.option_chain(expiry)
                else:
                    nearest = min(available, key=lambda e: abs(
                        (datetime.strptime(e, "%Y-%m-%d").date() - datetime.strptime(expiry, "%Y-%m-%d").date()).days
                    )) if available else None
                    chain = t.option_chain(nearest) if nearest else None
                chain_cache[key] = {"calls": chain.calls if chain else None, "puts": chain.puts if chain else None}
            except Exception:
                chain_cache[key] = {"calls": None, "puts": None}

        cached = chain_cache[key]
        df = cached["calls"] if opt_type == "call" else cached["puts"]
        if df is None or df.empty:
            return {}
        match = df[df["strike"] == strike]
        if match.empty:
            closest_idx = (df["strike"] - strike).abs().idxmin()
            match = df.loc[[closest_idx]]
        row = match.iloc[0]
        return {
            "last_price": float(row.get("lastPrice", 0) or 0),
            "bid": float(row.get("bid", 0) or 0),
            "ask": float(row.get("ask", 0) or 0),
            "iv": float(row.get("impliedVolatility", 0) or 0),
            "volume": int(row.get("volume", 0) or 0),
            "open_interest": int(row.get("openInterest", 0) or 0),
        }

    details = []
    for o in options:
        ticker = o["ticker"]
        contracts = o["contracts"]
        premium = o["premium"]
        strike = o["strike"]
        current = current_prices.get(ticker, strike)
        position = o.get("position", "long")
        opt_type = o["option_type"]

        try:
            expiry_date = datetime.strptime(o["expiry"], "%Y-%m-%d").date()
            dte = max((expiry_date - today).days, 0)
        except (ValueError, KeyError):
            dte = 0

        intrinsic = max(current - strike, 0) if opt_type == "call" else max(strike - current, 0)

        market = _get_market_price(ticker, opt_type, strike, o["expiry"])
        if market:
            bid, ask = market.get("bid", 0), market.get("ask", 0)
            market_price = (bid + ask) / 2 if bid > 0 and ask > 0 else market.get("last_price", 0)
            iv, volume, oi = market.get("iv", 0), market.get("volume", 0), market.get("open_interest", 0)
        else:
            market_price, iv, volume, oi = intrinsic, 0, 0, 0

        cost = premium * 100 * contracts
        current_value = market_price * 100 * contracts
        pnl = (current_value - cost) if position == "long" else (cost - current_value)
        pnl_pct = (pnl / cost * 100) if cost else 0

        details.append({
            "id": o["id"], "ticker": ticker, "type": opt_type, "position": position,
            "strike": strike, "expiry": o["expiry"], "dte": dte,
            "contracts": contracts, "premium": premium, "cost": round(cost, 2),
            "current_price": current, "intrinsic": round(intrinsic, 2),
            "market_price": round(market_price, 2),
            "bid": round(market.get("bid", 0), 2) if market else 0,
            "ask": round(market.get("ask", 0), 2) if market else 0,
            "iv": round(iv * 100, 1), "volume": volume, "open_interest": oi,
            "est_value": round(market_price, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
        })

    total_cost = sum(d["cost"] for d in details)
    total_pnl = sum(d["pnl"] for d in details)
    total_market = sum(d["market_price"] * d["contracts"] * 100 for d in details)
    return {
        "total_cost": round(total_cost, 2),
        "total_value": round(total_market, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round((total_pnl / total_cost * 100) if total_cost else 0, 2),
        "options": details,
    }


@app.post("/api/portfolio/options/buy")
def options_buy(req: OptionRequest, user: dict = Depends(get_current_user)):
    return add_user_option(user["user_id"], req.ticker, req.option_type, req.strike,
                          req.expiry, req.premium, req.contracts, req.position)


@app.post("/api/portfolio/options/close")
def options_close(req: OptionRequest, user: dict = Depends(get_current_user)):
    result = close_user_option(user["user_id"], req.ticker, req.option_type, req.strike,
                               req.expiry, req.premium, req.contracts, req.position)
    if result is None:
        raise HTTPException(status_code=404, detail="Option not found in portfolio")
    return result


@app.put("/api/portfolio/options/{option_id}")
def options_edit(option_id: int, req: OptionUpdateRequest, user: dict = Depends(get_current_user)):
    result = update_user_option(user["user_id"], option_id, req.ticker, req.option_type,
                                req.strike, req.expiry, req.premium, req.contracts, req.position)
    if result is None:
        raise HTTPException(status_code=404, detail="Option not found")
    return result


@app.delete("/api/portfolio/options/{option_id}")
def options_delete(option_id: int, user: dict = Depends(get_current_user)):
    result = delete_user_option(user["user_id"], option_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Option not found")
    return result


# ── Screener / Watchlist (auth required) ────────────────────────────────────

@app.get("/api/watchlist")
def watchlist_get(user: dict = Depends(get_current_user)):
    tickers = get_user_watchlist(user["user_id"])
    return {"tickers": tickers}


@app.post("/api/watchlist")
def watchlist_add(req: WatchlistRequest, user: dict = Depends(get_current_user)):
    # Validate ticker exists
    try:
        get_key_metrics(req.ticker.upper())
    except Exception:
        raise HTTPException(status_code=404, detail=f"Ticker '{req.ticker}' not found")
    added = add_to_watchlist(user["user_id"], req.ticker)
    if not added:
        raise HTTPException(status_code=409, detail="Already in watchlist")
    return {"message": f"{req.ticker.upper()} added to watchlist"}


@app.delete("/api/watchlist/{ticker}")
def watchlist_remove(ticker: str, user: dict = Depends(get_current_user)):
    removed = remove_from_watchlist(user["user_id"], ticker)
    if not removed:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    return {"message": f"{ticker.upper()} removed from watchlist"}


@app.get("/api/screener")
def screener_data(user: dict = Depends(get_current_user)):
    """Fetch key metrics for all stocks in user's watchlist (batch-optimized)."""
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor
    tickers = get_user_watchlist(user["user_id"])
    if not tickers:
        return {"stocks": []}

    # Batch-fetch prices + basic data in one yf.download call
    batch_prices = {}
    try:
        if len(tickers) == 1:
            data = yf.download(tickers[0], period="1mo", interval="1d", progress=False)
            if not data.empty:
                batch_prices[tickers[0]] = data
        else:
            data = yf.download(tickers, period="1mo", interval="1d", progress=False, group_by="ticker")
            for t in tickers:
                try:
                    df = data[t].dropna(how="all")
                    if not df.empty:
                        batch_prices[t] = df
                except Exception:
                    pass
    except Exception:
        pass

    def _process_ticker(t):
        try:
            m = get_key_metrics(t)  # Uses 60s cache
            rsi = None
            df = batch_prices.get(t)
            if df is not None and len(df) >= 14:
                try:
                    df = compute_indicators(df)
                    rsi_col = df["rsi"].dropna()
                    if not rsi_col.empty:
                        rsi = round(float(rsi_col.iloc[-1]), 1)
                except Exception:
                    pass
            return {
                "ticker": t,
                "name": m.get("name", t),
                "price": m.get("price", 0),
                "change_pct": m.get("change_pct", 0),
                "high_52w": m.get("52w_high", 0),
                "low_52w": m.get("52w_low", 0),
                "pe_ratio": m.get("pe_ratio"),
                "eps": m.get("eps"),
                "market_cap": m.get("market_cap", 0),
                "market_cap_fmt": format_large_number(m.get("market_cap")),
                "volume": m.get("volume", 0),
                "avg_volume": m.get("avg_volume", 0),
                "dividend_yield": m.get("dividend_yield"),
                "beta": m.get("beta"),
                "sector": m.get("sector", "N/A"),
                "rsi": rsi,
            }
        except Exception:
            return {"ticker": t, "name": t, "error": True}

    with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as pool:
        results = list(pool.map(_process_ticker, tickers))
    return {"stocks": results}


# ── New AI / analytical endpoints ────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    context: Optional[dict] = None


@app.get("/api/stock/{ticker}/why-moving")
@limiter.limit("30/minute")
def why_moving(request: Request, ticker: str):
    """AI explanation of why a stock is moving today."""
    ticker = _valid_ticker(ticker)
    try:
        from openai import OpenAI
        from config import OPENAI_API_KEY
        metrics = get_key_metrics(ticker)
        news = fetch_news(ticker, company_name=metrics.get("name", ""))
        headlines = "\n".join(f"- {a['title']}" for a in news[:6])
        change_pct = metrics.get("change_pct", 0)
        direction = "up" if change_pct >= 0 else "down"
        if not OPENAI_API_KEY:
            direction = "up" if change_pct >= 0 else "down"
            top_headline = news[0]['title'] if news else None
            explanation = f"{metrics['name']} ({ticker.upper()}) is {direction} {abs(change_pct):.2f}% today at ${metrics['price']:.2f}."
            if top_headline:
                explanation += f" Most recent headline: \"{top_headline}\"."
            explanation += " No AI analysis available — add an OPENAI_API_KEY to your .env to enable full explanations."
            return {"explanation": explanation, "change_pct": change_pct}
        client = OpenAI(api_key=OPENAI_API_KEY)
        prompt = f"""{metrics['name']} ({ticker.upper()}) is {direction} {abs(change_pct):.2f}% today (price: ${metrics['price']}).

Recent headlines:
{headlines}

In 2-3 short sentences, explain the most likely reason for today's move using only the available context. Be specific. If no clear catalyst is visible, say so clearly. Do not fabricate reasons."""
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150, temperature=0.5,
        )
        return {"explanation": resp.choices[0].message.content.strip(), "change_pct": change_pct}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{ticker}/bull-bear")
@limiter.limit("30/minute")
def bull_bear(request: Request, ticker: str):
    """Structured bull vs bear case."""
    ticker = _valid_ticker(ticker)
    try:
        from openai import OpenAI
        from config import OPENAI_API_KEY
        import json
        metrics = get_key_metrics(ticker)
        news = fetch_news(ticker, company_name=metrics.get("name", ""))
        sentiment = aggregate_sentiment(news)
        headlines = "\n".join(f"- {a['title']}" for a in news[:8])
        if not OPENAI_API_KEY:
            # Build dynamic fallback from real metrics
            name = metrics.get('name', ticker.upper())
            price = metrics.get('price', 0)
            change = metrics.get('change_pct', 0)
            pe = metrics.get('pe_ratio')
            beta = metrics.get('beta')
            high_52 = metrics.get('52w_high')
            low_52 = metrics.get('52w_low')
            mktcap = metrics.get('market_cap', 0)
            div = metrics.get('dividend_yield')
            fwd_pe = metrics.get('forward_pe')
            sent_label = sentiment.get('label', 'Neutral')

            pct_from_high = ((price - high_52) / high_52 * 100) if high_52 else None
            pct_from_low = ((price - low_52) / low_52 * 100) if low_52 else None

            bull = []
            bear = []

            # Bull points
            if pct_from_low is not None and pct_from_low < 30:
                bull.append(f"Trading {pct_from_low:.1f}% above its 52-week low — potential value entry")
            elif pct_from_low is not None:
                bull.append(f"Strong momentum — up {pct_from_low:.1f}% from 52-week low at ${low_52:.2f}")
            if pe and pe < 20:
                bull.append(f"P/E of {pe:.1f} looks attractive vs typical market multiples")
            elif fwd_pe and fwd_pe < 18:
                bull.append(f"Forward P/E of {fwd_pe:.1f} suggests reasonable valuation on future earnings")
            else:
                bull.append(f"{'Profitable company' if pe else 'Growth-stage company'} in a large addressable market")
            if div and div > 0.01:
                bull.append(f"Pays a {div*100:.2f}% dividend yield, providing income alongside potential upside")
            elif sent_label in ('Positive', 'Very Bullish', 'Bullish'):
                bull.append(f"Recent news sentiment is {sent_label.lower()} — positive near-term momentum")
            else:
                bull.append("Established brand with scale advantages over smaller competitors")

            # Bear points
            if pct_from_high is not None and pct_from_high < -15:
                bear.append(f"Down {abs(pct_from_high):.1f}% from its 52-week high of ${high_52:.2f} — trend is weak")
            elif pct_from_high is not None and pct_from_high > -5:
                bear.append(f"Near 52-week high (${high_52:.2f}) — limited near-term upside, potential resistance")
            else:
                bear.append(f"Price has pulled back from highs — unclear if this is a reversal or a dip")
            if pe and pe > 30:
                bear.append(f"P/E of {pe:.1f} demands continued growth execution — leaves little margin for error")
            elif pe and pe < 0:
                bear.append("Currently unprofitable — relies on future growth to justify valuation")
            else:
                bear.append("Valuation depends on growth assumptions that may be challenged in a rising-rate environment")
            if beta and beta > 1.3:
                bear.append(f"High beta of {beta:.2f} means amplified downside in broader market sell-offs")
            elif sent_label in ('Negative', 'Bearish', 'Very Bearish'):
                bear.append(f"Recent news sentiment is {sent_label.lower()} — near-term headwinds possible")
            else:
                bear.append("Macro uncertainty and sector rotation could weigh on the stock near-term")

            verdict = (
                f"{name} shows {'positive' if change >= 0 else 'negative'} momentum today "
                f"({change:+.2f}%). Weigh the above factors against your own risk tolerance."
            )
            return {"bull": bull[:3], "bear": bear[:3], "verdict": verdict}
        client = OpenAI(api_key=OPENAI_API_KEY)
        prompt = f"""Analyze {metrics['name']} ({ticker.upper()}) and return a JSON object with exactly this structure:
{{
  "bull": ["point 1", "point 2", "point 3"],
  "bear": ["point 1", "point 2", "point 3"],
  "verdict": "one sentence synthesis"
}}

Data:
- Price: ${metrics['price']} ({metrics.get('change_pct',0):+.2f}% today)
- P/E: {metrics.get('pe_ratio','N/A')}, Forward P/E: {metrics.get('forward_pe','N/A')}
- Beta: {metrics.get('beta','N/A')}, Market Cap: {metrics.get('market_cap',0):,.0f}
- 52W: ${metrics.get('52w_low',0):.2f} – ${metrics.get('52w_high',0):.2f}
- News sentiment: {sentiment['label']} ({sentiment['positive']} pos, {sentiment['negative']} neg)
- Headlines: {headlines}

Return ONLY valid JSON, no markdown fences."""
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300, temperature=0.6,
        )
        text = resp.choices[0].message.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/stock/{ticker}/chat")
@limiter.limit("30/minute")
def stock_chat(request: Request, ticker: str, req: ChatRequest):
    """AI chat with per-ticker context."""
    ticker = _valid_ticker(ticker)
    try:
        from openai import OpenAI
        from config import OPENAI_API_KEY
        if not OPENAI_API_KEY:
            metrics = get_key_metrics(ticker)
            last_q = req.messages[-1].content if req.messages else ""
            reply = (
                f"AI Chat requires an OpenAI API key (add OPENAI_API_KEY to your .env file). "
                f"Here's what I can tell you about {ticker.upper()} from live data: "
                f"Price ${metrics.get('price','N/A')}, {metrics.get('change_pct',0):+.2f}% today, "
                f"P/E {metrics.get('pe_ratio','N/A')}, Market Cap {metrics.get('market_cap_fmt','N/A')}, "
                f"Sector: {metrics.get('sector','N/A')}."
            )
            return {"reply": reply}
        client = OpenAI(api_key=OPENAI_API_KEY)
        ctx = req.context or {}
        sys_prompt = f"""You are a financial analyst assistant for {ticker.upper()}.
Available context: Price=${ctx.get('price','N/A')}, Change={ctx.get('change_pct','N/A')}%, P/E={ctx.get('pe_ratio','N/A')}, Market Cap={ctx.get('market_cap','N/A')}, Sector={ctx.get('sector','N/A')}, News sentiment={ctx.get('sentiment_label','N/A')}.
Answer questions about this stock concisely. Always add a disclaimer that this is not financial advice."""
        messages = [{"role": "system", "content": sys_prompt}]
        messages += [{"role": m.role, "content": m.content} for m in req.messages]
        resp = client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, max_tokens=400, temperature=0.7,
        )
        return {"reply": resp.choices[0].message.content.strip()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{ticker}/peers")
@limiter.limit("30/minute")
def stock_peers(request: Request, ticker: str):
    """Return peer/competitor metrics for comparison."""
    ticker = _valid_ticker(ticker)
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info

        # Try to discover peers dynamically from yfinance
        peer_tickers = []

        # 1. Check if yfinance exposes a recommendations or peers field
        try:
            # Some yfinance versions expose info["companyOfficers"] or sector peers
            # Try the screener approach: find tickers in same industry
            industry = info.get("industry", "")
            sector = info.get("sector", "")
            if industry:
                # Use yfinance Screener to find peers in same industry
                try:
                    import yfinance.screener as screener
                    s = yf.Screener()
                    s.set_default_body({"query": {"operator": "AND", "operands": [
                        {"operator": "eq", "operands": ["industry", industry]}
                    ]}, "size": 10, "sortField": "intradaymarketcap", "sortType": "DESC"})
                    results = s.response.get("finance", {}).get("result", [{}])[0].get("quotes", [])
                    peer_tickers = [q["symbol"] for q in results if q.get("symbol", "").upper() != ticker.upper()][:4]
                except Exception:
                    pass

            # 2. Fallback: use well-known sector ETF constituents or manual lookup
            if not peer_tickers:
                sector_peers = {
                    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMZN", "CRM", "ADBE", "ORCL", "INTC", "AMD", "QCOM", "AVGO", "TSM", "IBM"],
                    "Communication Services": ["GOOGL", "META", "DIS", "NFLX", "CMCSA", "T", "VZ", "SNAP", "PINS"],
                    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "NKE", "SBUX", "MCD", "TGT", "LULU", "BKNG", "ABNB"],
                    "Financial Services": ["JPM", "BAC", "GS", "MS", "WFC", "C", "BLK", "SCHW", "AXP", "V", "MA"],
                    "Healthcare": ["JNJ", "UNH", "PFE", "MRK", "ABBV", "LLY", "BMY", "TMO", "ABT", "AMGN"],
                    "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "GIS"],
                    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "VLO", "PSX"],
                    "Industrials": ["BA", "CAT", "GE", "HON", "UPS", "RTX", "LMT", "DE", "MMM"],
                    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "SPG", "O", "DLR", "PSA"],
                    "Utilities": ["NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL"],
                    "Basic Materials": ["LIN", "APD", "SHW", "ECL", "NEM", "FCX", "NUE", "DOW"],
                }
                pool = sector_peers.get(sector, [])
                peer_tickers = [t for t in pool if t.upper() != ticker.upper()][:4]
        except Exception:
            pass

        if not peer_tickers:
            return {"peers": [], "base": None}

        base = get_key_metrics(ticker.upper())
        base["ticker"] = ticker.upper()
        peers_out = []
        for pt in peer_tickers[:4]:
            try:
                m = get_key_metrics(pt)
                peers_out.append({
                    "ticker": pt, "name": m.get("name", pt),
                    "price": m.get("price"), "change_pct": m.get("change_pct"),
                    "pe_ratio": m.get("pe_ratio"), "market_cap": m.get("market_cap"),
                    "market_cap_fmt": format_large_number(m.get("market_cap")),
                    "eps": m.get("eps"), "beta": m.get("beta"),
                    "dividend_yield": m.get("dividend_yield"),
                })
            except Exception:
                pass
        return {"base": {"ticker": ticker.upper(), "name": base.get("name"), "price": base.get("price"),
                         "change_pct": base.get("change_pct"), "pe_ratio": base.get("pe_ratio"),
                         "market_cap": base.get("market_cap"), "market_cap_fmt": format_large_number(base.get("market_cap")),
                         "eps": base.get("eps"), "beta": base.get("beta"), "dividend_yield": base.get("dividend_yield")},
                "peers": peers_out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{ticker}/events")
def stock_events(ticker: str):
    """Return upcoming earnings date, past earnings, dividends, and key macro events."""
    ticker = _valid_ticker(ticker)
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        earnings_date = None
        try:
            cal = stock.calendar
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed:
                    val = ed[0] if isinstance(ed, list) else ed
                    earnings_date = str(val)[:10]
            elif cal is not None and hasattr(cal, 'empty') and not cal.empty:
                ed = cal.get("Earnings Date")
                if ed is not None and len(ed) > 0:
                    earnings_date = str(ed.iloc[0].date()) if hasattr(ed.iloc[0], "date") else str(ed.iloc[0])[:10]
        except Exception:
            pass

        # ── Past earnings with surprise ──────────────────────
        past_earnings = []
        try:
            import math
            eh = stock.earnings_dates
            if eh is not None and not eh.empty:
                for idx, row in eh.iterrows():
                    d = str(idx.date()) if hasattr(idx, "date") else str(idx)[:10]
                    surprise = None
                    raw = row.get("Surprise(%)")
                    if raw is not None:
                        try:
                            val = float(raw)
                            if not math.isnan(val):
                                surprise = val
                        except (ValueError, TypeError):
                            pass
                    past_earnings.append({"date": d, "surprise": surprise})
        except Exception:
            pass

        # ── Dividends ────────────────────────────────────────
        dividends = []
        try:
            divs = stock.dividends
            if divs is not None and len(divs) > 0:
                for ts, amount in divs.items():
                    d = str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]
                    dividends.append({"date": d, "amount": round(float(amount), 4)})
        except Exception:
            pass

        return {
            "earnings_date": earnings_date,
            "past_earnings": past_earnings,
            "dividends": dividends,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{ticker}/history-returns")
def stock_history_returns(ticker: str, period: str = Query("3mo")):
    """Return daily close prices for correlation computation."""
    ticker = _valid_ticker(ticker)
    try:
        df = get_stock_data(ticker, period=period, interval="1d")
        records = [{"date": ts.strftime("%Y-%m-%d"), "close": round(float(row["Close"]), 4)}
                   for ts, row in df.iterrows()]
        return records
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
