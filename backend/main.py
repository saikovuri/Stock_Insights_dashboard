from fastapi import FastAPI, HTTPException, Query, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date as _date
import logging
import math
import re
from typing import Literal
from pydantic import Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from stock_data import get_stock_data, get_key_metrics, get_quote, format_large_number, compute_indicators, \
    get_daily_indicators
from news_sentiment import fetch_news, aggregate_sentiment
from ai_brief import get_ai_brief
from ai_chat import run_chat
import llm
import options_analytics
import portfolio_doctor
import market
import earnings_intel
import scanner
import journal
import fundamentals
import scheduler
import options_flow
import macro
import smart_money
import portfolio_insights
import thesis
import intraday
import backtester
from providers import finnhub_enabled, finnhub_quote, finnhub_peers, finnhub_recommendations, \
    finnhub_basic_financials, finnhub_earnings_calendar, finnhub_insider_transactions, finnhub_profile, \
    finra_short_interest
from alerts import check_alerts, technical_events
from cache import get_or_fetch, stats as cache_stats, clear as cache_clear
from auth import hash_password, verify_password, create_token, decode_token, create_refresh_token, REFRESH_EXPIRE_DAYS
from database import (
    create_user, get_user_by_username, get_user_by_username_by_id,
    get_user_holdings, add_user_holding, update_user_holding, delete_user_holding, sell_user_holding,
    sell_user_holding_by_lot,
    get_user_options, add_user_option, close_user_option, update_user_option, delete_user_option,
    get_user_transactions, get_user_watchlist, add_to_watchlist, remove_from_watchlist,
    get_closed_trades, get_closed_options,
    store_refresh_token, get_refresh_token, delete_refresh_token, delete_user_refresh_tokens,
    list_notifications, mark_notifications_read, get_ntfy_topic, set_ntfy_topic,
    get_trader_profile, set_trader_profile, list_user_alerts, add_user_alert, delete_user_alert,
    count_active_alerts, list_journal, add_journal, update_journal, delete_journal,
    get_thesis, list_theses, delete_thesis,
)
from config import CORS_ORIGINS, SCHEDULER_ENABLED, SENTRY_DSN, SENTRY_ENVIRONMENT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("api")

if SENTRY_DSN:
    import os
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import ignore_logger
    from sentry_sdk.integrations.starlette import StarletteIntegration

    # Only real crashes and ERROR logs (e.g. scheduler failures); HTTP error responses are expected
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=SENTRY_ENVIRONMENT,
        release=os.getenv("RENDER_GIT_COMMIT"),
        send_default_pii=False,
        traces_sample_rate=0.0,
        integrations=[StarletteIntegration(failed_request_status_codes=set()),
                      FastApiIntegration(failed_request_status_codes=set())],
    )
    ignore_logger("yfinance")

app = FastAPI(title="Stock Insights API", version="3.0.0")


@app.on_event("startup")
def _start_background_jobs():
    if SCHEDULER_ENABLED:
        scheduler.start()


def _upstream_error(e: Exception, status: int = 500) -> HTTPException:
    """Log the real error; return a generic message so internals aren't exposed."""
    log.warning("Request failed: %s: %s", type(e).__name__, e)
    if status == 404:
        return HTTPException(status_code=404, detail="Ticker not found or data unavailable")
    return HTTPException(status_code=status, detail="Data provider error. Please try again shortly.")


@app.exception_handler(Exception)
async def _unhandled_error(request: Request, exc: Exception):
    from fastapi.responses import JSONResponse
    log.exception("Unhandled error on %s", request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})

# ── Health check (used by UptimeRobot / monitoring) ─────────────────────────

@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    return {"status": "ok"}

@app.api_route("/api/health", methods=["GET", "HEAD"])
async def api_health_check():
    """Health check that pings the DB to keep Supabase alive."""
    try:
        from database import get_db, _release, USE_PG
        if USE_PG:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            _release(conn)
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        log.error("Health check DB error: %s", e)
        return {"status": "ok", "db": "error"}

# ── Rate limiting ───────────────────────────────────────────────────────────

def _get_real_ip(request: Request) -> str:
    """Use X-Forwarded-For behind reverse proxies (Render, etc.), else remote address."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)

limiter = Limiter(key_func=_get_real_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Security headers middleware ─────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response: Response = await call_next(request)
        except Exception as exc:
            # Handled here (inside CORS) so the browser sees the 500 instead of an opaque "Failed to fetch"
            from fastapi.responses import JSONResponse
            log.exception("Unhandled error on %s", request.url.path, exc_info=exc)
            if SENTRY_DSN:
                sentry_sdk.capture_exception(exc)
            response = JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
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


@app.get("/api/cache/stats")
def cache_stats_endpoint(user: dict = Depends(get_current_user)):
    return cache_stats()


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
@limiter.limit("200/minute")
def stock_metrics(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        metrics = get_key_metrics(ticker)
        metrics["market_cap_fmt"] = format_large_number(metrics.get("market_cap"))
        return metrics
    except Exception as e:
        raise _upstream_error(e, 404)


class BatchMetricsRequest(BaseModel):
    tickers: list[str]


@app.post("/api/stock/batch-metrics")
@limiter.limit("60/minute")
def batch_metrics(request: Request, req: BatchMetricsRequest):
    """Fetch metrics for multiple tickers in one request (max 30)."""
    from concurrent.futures import ThreadPoolExecutor
    tickers = [_valid_ticker(t) for t in req.tickers[:30]]
    def _fetch(t):
        try:
            q = get_quote(t)
            return {"ticker": t, "price": q.get("price"), "change_pct": q.get("change_pct"), "name": q.get("name", t)}
        except Exception:
            return {"ticker": t, "price": None, "change_pct": None, "name": t}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as pool:
        results = list(pool.map(_fetch, tickers))
    return {"quotes": {r["ticker"]: r for r in results}}


_INTRADAY = ("1m", "2m", "5m", "15m", "30m", "1h")
# Extra history so long averages (SMA 200 etc.) are populated from the first visible bar
_WARMUP = {
    ("1d", "1mo"): "2y", ("1d", "3mo"): "2y", ("1d", "6mo"): "2y", ("1d", "1y"): "2y",
    ("1d", "2y"): "5y", ("1d", "5y"): "max",
    ("1wk", "1y"): "max", ("1wk", "2y"): "max", ("1wk", "5y"): "max",
    ("1mo", "5y"): "max",
    ("5m", "1d"): "5d", ("15m", "1d"): "5d", ("30m", "1d"): "5d", ("1h", "1d"): "1mo",
    ("5m", "5d"): "1mo", ("15m", "5d"): "1mo", ("30m", "5d"): "1mo", ("1h", "5d"): "3mo",
    ("1h", "1mo"): "6mo",
}
_PERIOD_OFFSETS = {"1mo": {"months": 1}, "3mo": {"months": 3}, "6mo": {"months": 6},
                   "1y": {"years": 1}, "2y": {"years": 2}, "5y": {"years": 5}}


def _trim_to_period(df, period: str):
    import pandas as pd
    if period in ("1d", "5d"):
        sessions = sorted(set(df.index.date))[-(1 if period == "1d" else 5):]
        return df[pd.Index(df.index.date).isin(sessions)]
    if period in _PERIOD_OFFSETS:
        return df[df.index > df.index[-1] - pd.DateOffset(**_PERIOD_OFFSETS[period])]
    return df


@app.get("/api/stock/{ticker}/history")
@limiter.limit("120/minute")
def stock_history(
    request: Request,
    ticker: str,
    period: str = Query("6mo", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|max)$"),
    interval: str = Query("1d", pattern="^(1m|2m|5m|15m|30m|1h|1d|5d|1wk|1mo)$"),
    prepost: bool = Query(False),
):
    ticker = _valid_ticker(ticker)
    try:
        warm = _WARMUP.get((interval, period))
        try:
            df = get_stock_data(ticker, period=warm or period, interval=interval, prepost=prepost)
        except Exception:
            if not warm:
                raise
            warm, df = None, get_stock_data(ticker, period=period, interval=interval, prepost=prepost)
        # Yahoo occasionally returns bars with missing prices (holidays, halted sessions)
        df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
        df["Volume"] = df["Volume"].fillna(0)
        df = compute_indicators(df)
        if warm:
            df = _trim_to_period(df, period)
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
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            }
            for k in indicator_keys:
                v = row.get(k)
                try:
                    f = float(v)
                    rec[k] = round(f, 2) if math.isfinite(f) else None
                except (TypeError, ValueError):
                    rec[k] = None
            records.append(rec)
        return records
    except Exception as e:
        raise _upstream_error(e, 404)


@app.get("/api/stock/{ticker}/news")
@limiter.limit("60/minute")
def stock_news(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    def _fetch():
        metrics = get_key_metrics(ticker)
        news = fetch_news(ticker, company_name=metrics.get("name", ""))
        sentiment = aggregate_sentiment(news)
        return {"articles": news, "sentiment": sentiment}
    try:
        return get_or_fetch(f"news:{ticker}", _fetch, ttl=300)
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/stock/{ticker}/brief")
@limiter.limit("20/minute")
def stock_brief(request: Request, ticker: str, user: dict = Depends(get_current_user),
                profile: Optional[str] = Query(None, pattern="^(day|swing|long)$")):
    """One AI call: summary, why it's moving, bull/bear, risks, catalysts (cached 15 min per ticker+profile)."""
    ticker = _valid_ticker(ticker)
    profile = profile or get_trader_profile(int(user["user_id"])) or "swing"
    try:
        return get_ai_brief(ticker, profile)
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/stock/{ticker}/alerts")
@limiter.limit("60/minute")
def stock_alerts(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        metrics = get_key_metrics(ticker)
        alerts = check_alerts(metrics)
        try:
            alerts += technical_events(metrics.get("name", ticker), get_daily_indicators(ticker))
        except Exception as e:
            log.info("No technical events for %s: %s", ticker, e)
        return alerts
    except Exception as e:
        raise _upstream_error(e)


# ── Portfolio (auth required) ──────────────────────────────────────────────

@app.get("/api/portfolio/summary")
def portfolio_summary_endpoint(user: dict = Depends(get_current_user)):
    holdings = get_user_holdings(user["user_id"])
    if not holdings:
        return {"total_invested": 0, "total_current": 0, "total_pnl": 0, "total_pnl_pct": 0, "holdings": []}

    # Real-time Finnhub quotes first; one batched yfinance download for anything left
    import yfinance as yf
    unique_tickers = list({h["ticker"] for h in holdings})
    current_prices = {}
    if finnhub_enabled():
        for t in unique_tickers:
            q = finnhub_quote(t)
            if q:
                current_prices[t] = round(float(q["c"]), 2)
    remaining = [t for t in unique_tickers if t not in current_prices]
    try:
        if len(remaining) == 1:
            data = yf.download(remaining[0], period="1d", interval="1d", progress=False)
            if not data.empty:
                current_prices[remaining[0]] = round(float(data["Close"].iloc[-1]), 2)
        elif remaining:
            data = yf.download(remaining, period="1d", interval="1d", progress=False, group_by="ticker")
            for t in remaining:
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
        # Get sector from cached metrics
        sector = "Unknown"
        try:
            m = get_key_metrics(ticker)
            s = m.get("sector", "")
            sector = s if (s and s != "N/A") else "Unknown"
        except Exception:
            pass
        details.append({
            "id": h["id"], "ticker": ticker, "shares": shares,
            "buy_price": buy_price, "current_price": current,
            "invested": round(invested, 2), "current_value": round(current_val, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            "sector": sector,
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
                available = options_analytics._expirations(yf_sym)
                if expiry not in available:
                    expiry = min(available, key=lambda e: abs(
                        (datetime.strptime(e, "%Y-%m-%d").date() - datetime.strptime(expiry, "%Y-%m-%d").date()).days
                    )) if available else None
                calls, puts = options_analytics._chain(yf_sym, expiry) if expiry else (None, None)
                chain_cache[key] = {"calls": calls, "puts": puts}
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
    ticker = _valid_ticker(req.ticker)
    try:
        get_key_metrics(ticker)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")
    added = add_to_watchlist(user["user_id"], ticker)
    if not added:
        raise HTTPException(status_code=409, detail="Already in watchlist")
    return {"message": f"{ticker} added to watchlist"}


@app.delete("/api/watchlist/{ticker}")
def watchlist_remove(ticker: str, user: dict = Depends(get_current_user)):
    ticker = _valid_ticker(ticker)
    removed = remove_from_watchlist(user["user_id"], ticker)
    if not removed:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    return {"message": f"{ticker} removed from watchlist"}


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


# ── AI chat & portfolio doctor ───────────────────────────────────────────────

class ChatMessage(BaseModel):
    # Only user/assistant turns are accepted; the system prompt is always server-side
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=2000)

class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=20)


@app.post("/api/stock/{ticker}/chat")
@limiter.limit("20/minute")
def stock_chat(request: Request, ticker: str, req: ChatRequest, user: dict = Depends(get_current_user)):
    """Tool-calling AI assistant: the model fetches live data (quotes, news, filings, portfolio) itself."""
    ticker = _valid_ticker(ticker)
    if not llm.ai_enabled():
        return {"reply": "AI chat needs an AI key (GROQ_API_KEY or GEMINI_API_KEY) on the server.", "tools_used": []}
    history = [{"role": m.role, "content": m.content} for m in req.messages]
    try:
        return run_chat(ticker, history, lambda: portfolio_summary_endpoint(user))
    except Exception as e:
        log.warning("Chat failed for %s: %s", ticker, e)
        raise HTTPException(status_code=503, detail="AI is temporarily unavailable. Please try again shortly.")


@app.get("/api/portfolio/doctor")
@limiter.limit("10/minute")
def portfolio_doctor_endpoint(request: Request, user: dict = Depends(get_current_user)):
    """Concentration, correlation, volatility, tax-loss and earnings checks with an AI review."""
    try:
        return get_or_fetch(f"doctor:{user['user_id']}",
                            lambda: portfolio_doctor.analyze(portfolio_summary_endpoint(user)), ttl=1800)
    except Exception as e:
        raise _upstream_error(e)


# ── Notifications & daily briefing ───────────────────────────────────────────

_NTFY_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

class NotificationSettings(BaseModel):
    ntfy_topic: Optional[str] = None


@app.get("/api/notifications")
def notifications_list(user: dict = Depends(get_current_user)):
    items = list_notifications(user["user_id"])
    return {"items": items, "unread": sum(1 for n in items if not n.get("read_at"))}


@app.post("/api/notifications/read")
def notifications_read(user: dict = Depends(get_current_user)):
    mark_notifications_read(user["user_id"])
    return {"ok": True}


@app.get("/api/notifications/settings")
def notifications_settings_get(user: dict = Depends(get_current_user)):
    return {"ntfy_topic": get_ntfy_topic(user["user_id"])}


@app.put("/api/notifications/settings")
def notifications_settings_put(req: NotificationSettings, user: dict = Depends(get_current_user)):
    topic = (req.ntfy_topic or "").strip() or None
    if topic and not _NTFY_TOPIC_RE.match(topic):
        raise HTTPException(status_code=400, detail="Topic must be 8-64 letters, digits, '-' or '_'")
    set_ntfy_topic(user["user_id"], topic)
    return {"ntfy_topic": topic}


@app.get("/api/briefing")
@limiter.limit("6/minute")
def daily_briefing(request: Request, refresh: bool = False, user: dict = Depends(get_current_user)):
    """Today's briefing for the user's holdings + watchlist (generated on demand if missing)."""
    from database import get_all_user_tickers
    tickers = get_all_user_tickers().get(int(user["user_id"]), set())
    try:
        b = scheduler.get_or_create_briefing(int(user["user_id"]), tickers, force=refresh)
    except Exception as e:
        raise _upstream_error(e)
    return b or {"empty": True}


@app.get("/api/stock/{ticker}/peers")
@limiter.limit("60/minute")
def stock_peers(request: Request, ticker: str):
    """Return peer/competitor metrics for comparison."""
    ticker = _valid_ticker(ticker)
    def _fetch():
        peer_tickers = [p for p in finnhub_peers(ticker) if p.upper() != ticker][:4]

        try:
            if not peer_tickers:
                sector = get_key_metrics(ticker).get("sector", "")
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
    try:
        return get_or_fetch(f"peers:{ticker}", _fetch, ttl=600)
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/stock/{ticker}/events")
def stock_events(ticker: str):
    """Return upcoming earnings date, past earnings, dividends, and key macro events."""
    ticker = _valid_ticker(ticker)
    def _fetch():
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
        if not earnings_date:
            cal = finnhub_earnings_calendar(90, ticker)
            earnings_date = next((e.get("date") for e in cal if e.get("symbol") == ticker and e.get("date")), None)

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
    try:
        return get_or_fetch(f"events:{ticker}", _fetch, ttl=600)
    except Exception as e:
        raise _upstream_error(e)


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
        raise _upstream_error(e, 404)


# ── Analyst Ratings & Price Targets ─────────────────────────────────────────

@app.get("/api/stock/{ticker}/analyst")
@limiter.limit("120/minute")
def stock_analyst(request: Request, ticker: str):
    """Analyst recommendations, price targets, and upgrade/downgrade history."""
    ticker = _valid_ticker(ticker)
    def _fetch():
        import yfinance as yf
        import math
        stock = yf.Ticker(ticker)
        try:
            info = stock.info or {}
        except Exception:
            info = {}

        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        target_mean = info.get("targetMeanPrice")
        target_median = info.get("targetMedianPrice")
        num_analysts = info.get("numberOfAnalystOpinions", 0)
        recommendation = info.get("recommendationKey", "")
        recommendation_mean = info.get("recommendationMean")

        breakdown = {"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}
        fh_recs = finnhub_recommendations(ticker)
        if fh_recs:
            for col in breakdown:
                breakdown[col] = int(fh_recs[0].get(col) or 0)
        try:
            recs = None if fh_recs else stock.recommendations
            if recs is not None and not recs.empty:
                latest = recs.iloc[-1] if len(recs) > 0 else None
                if latest is not None:
                    for col in ["strongBuy", "buy", "hold", "sell", "strongSell"]:
                        val = latest.get(col)
                        if val is not None and not (isinstance(val, float) and math.isnan(val)):
                            breakdown[col] = int(val)
        except Exception:
            pass
        total = sum(breakdown.values())
        if not recommendation_mean and total:
            # Yahoo's 1 (strong buy) .. 5 (strong sell) scale, derived from the Finnhub breakdown
            recommendation_mean = round(sum(w * breakdown[k] for w, k in enumerate(breakdown, 1)) / total, 2)
            recommendation = ("strong_buy" if recommendation_mean <= 1.5 else "buy" if recommendation_mean <= 2.5
                              else "hold" if recommendation_mean <= 3.5 else "sell" if recommendation_mean <= 4.5
                              else "strong_sell")

        upgrades = []
        try:
            ug = stock.upgrades_downgrades
            if ug is not None and not ug.empty:
                recent = ug.head(10)
                for idx, row in recent.iterrows():
                    d = str(idx)[:10] if hasattr(idx, 'strftime') else str(idx)[:10]
                    cur_pt = row.get("currentPriceTarget")
                    prior_pt = row.get("priorPriceTarget")
                    upgrades.append({
                        "date": d,
                        "firm": str(row.get("Firm", "")),
                        "toGrade": str(row.get("ToGrade", "")),
                        "fromGrade": str(row.get("FromGrade", "")),
                        "action": str(row.get("Action", "")),
                        "priceTargetAction": str(row.get("priceTargetAction", "")),
                        "currentPriceTarget": None if (cur_pt is None or (isinstance(cur_pt, float) and math.isnan(cur_pt))) else float(cur_pt),
                        "priorPriceTarget": None if (prior_pt is None or (isinstance(prior_pt, float) and math.isnan(prior_pt))) else float(prior_pt),
                    })
        except Exception:
            pass

        return {
            "price_targets": {"high": target_high, "low": target_low, "mean": target_mean, "median": target_median, "num_analysts": num_analysts},
            "recommendation": recommendation,
            "recommendation_mean": recommendation_mean,
            "breakdown": breakdown,
            "upgrades_downgrades": upgrades[-10:],
        }
    try:
        return get_or_fetch(f"analyst:{ticker}", _fetch, ttl=600)
    except Exception as e:
        raise _upstream_error(e)


# ── Financial Statements ────────────────────────────────────────────────────

@app.get("/api/stock/{ticker}/financials")
@limiter.limit("60/minute")
def stock_financials(request: Request, ticker: str):
    """Income statement, balance sheet, cash flow (annual + quarterly)."""
    ticker = _valid_ticker(ticker)
    def _fetch():
        import yfinance as yf
        import math
        stock = yf.Ticker(ticker)

        def _df_to_dict(df):
            if df is None or df.empty:
                return {}
            result = {}
            for col in df.columns:
                period_key = str(col)[:10]
                items = {}
                for idx, val in df[col].items():
                    if val is not None and not (isinstance(val, float) and math.isnan(val)):
                        items[str(idx)] = float(val)
                if items:
                    result[period_key] = items
            return result

        return {
            "income_statement": _df_to_dict(stock.financials),
            "income_statement_quarterly": _df_to_dict(stock.quarterly_financials),
            "balance_sheet": _df_to_dict(stock.balance_sheet),
            "balance_sheet_quarterly": _df_to_dict(stock.quarterly_balance_sheet),
            "cash_flow": _df_to_dict(stock.cashflow),
            "cash_flow_quarterly": _df_to_dict(stock.quarterly_cashflow),
        }
    try:
        return get_or_fetch(f"financials:{ticker}", _fetch, ttl=600)
    except Exception as e:
        raise _upstream_error(e)


# ── Institutional & Insider Activity ────────────────────────────────────────

@app.get("/api/stock/{ticker}/ownership")
@limiter.limit("60/minute")
def stock_ownership(request: Request, ticker: str):
    """Top institutional holders and insider transactions."""
    ticker = _valid_ticker(ticker)
    def _fetch():
        import yfinance as yf
        import math
        stock = yf.Ticker(ticker)
        try:
            info = stock.info or {}
        except Exception:
            info = {}

        # Institutional holders
        institutions = []
        try:
            ih = stock.institutional_holders
            if ih is not None and not ih.empty:
                for _, row in ih.head(15).iterrows():
                    holder = {}
                    for col in ih.columns:
                        val = row[col]
                        if val is not None and not (isinstance(val, float) and math.isnan(val)):
                            if hasattr(val, 'strftime'):
                                holder[col] = val.strftime("%Y-%m-%d")
                            elif isinstance(val, (int, float)):
                                holder[col] = float(val)
                            else:
                                holder[col] = str(val)
                    institutions.append(holder)
        except Exception:
            pass

        # Insider transactions
        insiders = []
        try:
            it = stock.insider_transactions
            if it is not None and not it.empty:
                for _, row in it.head(20).iterrows():
                    txn = {}
                    for col in it.columns:
                        val = row[col]
                        if val is not None and not (isinstance(val, float) and math.isnan(val)):
                            if hasattr(val, 'strftime'):
                                txn[col] = val.strftime("%Y-%m-%d")
                            elif isinstance(val, (int, float)):
                                txn[col] = float(val)
                            else:
                                txn[col] = str(val)
                    insiders.append(txn)
        except Exception:
            pass
        if not insiders:
            # Finnhub fallback (Form 4 data); codes per SEC Form 4 instructions
            codes = {"P": "Purchase", "S": "Sale", "A": "Award/Grant", "M": "Option Exercise",
                     "F": "Tax Withholding", "G": "Gift", "C": "Conversion", "X": "Option Exercise"}
            for t in finnhub_insider_transactions(ticker)[:20]:
                change, price = t.get("change") or 0, t.get("transactionPrice") or 0
                insiders.append({
                    "Insider": t.get("name"),
                    "Transaction": codes.get(t.get("transactionCode"), t.get("transactionCode") or ""),
                    "Shares": change,
                    "Value": round(abs(change) * price, 2) if price else None,
                    "Date": t.get("transactionDate"),
                })

        # Summary stats
        held_pct_insiders = info.get("heldPercentInsiders")
        held_pct_institutions = info.get("heldPercentInstitutions")

        return {
            "held_pct_insiders": round(held_pct_insiders * 100, 2) if held_pct_insiders else None,
            "held_pct_institutions": round(held_pct_institutions * 100, 2) if held_pct_institutions else None,
            "institutional_holders": institutions,
            "insider_transactions": insiders,
        }
    try:
        return get_or_fetch(f"ownership:{ticker}", _fetch, ttl=600)
    except Exception as e:
        raise _upstream_error(e)


# ── Dividend Details ────────────────────────────────────────────────────────

@app.get("/api/stock/{ticker}/dividends")
@limiter.limit("60/minute")
def stock_dividends(request: Request, ticker: str):
    """Dividend history, yield, payout details."""
    ticker = _valid_ticker(ticker)
    def _fetch():
        import yfinance as yf
        stock = yf.Ticker(ticker)
        try:
            info = stock.info or {}
        except Exception:
            info = {}

        # Dividend info from info
        div_rate = info.get("dividendRate")
        div_yield = info.get("dividendYield")
        ex_date = info.get("exDividendDate")
        payout_ratio = info.get("payoutRatio")
        five_yr_avg = info.get("fiveYearAvgDividendYield")
        if div_yield is None:
            # Finnhub fallback (percent units, like yfinance's dividendYield)
            m = finnhub_basic_financials(ticker) or {}
            div_rate = m.get("dividendIndicatedAnnual") or m.get("dividendPerShareTTM")
            div_yield = m.get("currentDividendYieldTTM")
            if m.get("payoutRatioTTM") is not None:
                payout_ratio = m["payoutRatioTTM"] / 100

        # Convert epoch ex_date to readable
        ex_date_str = None
        if ex_date:
            try:
                from datetime import datetime as _dt
                ex_date_str = _dt.fromtimestamp(ex_date).strftime("%Y-%m-%d")
            except Exception:
                ex_date_str = str(ex_date)

        # Historical dividends
        history = []
        try:
            divs = stock.dividends
            if divs is not None and len(divs) > 0:
                for ts, amount in divs.items():
                    d = str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]
                    history.append({"date": d, "amount": round(float(amount), 4)})
        except Exception:
            pass
        if not ex_date_str and history:
            ex_date_str = history[-1]["date"]

        return {
            "dividend_rate": div_rate,
            "dividend_yield": round(div_yield, 2) if div_yield else None,  # yfinance already returns a percent
            "ex_dividend_date": ex_date_str,
            "payout_ratio": round(payout_ratio * 100, 1) if payout_ratio else None,
            "five_year_avg_yield": five_yr_avg,
            "history": history,
        }
    try:
        return get_or_fetch(f"dividends:{ticker}", _fetch, ttl=600)
    except Exception as e:
        raise _upstream_error(e)


# ── Sparkline data for watchlist ────────────────────────────────────────────

class SparklineRequest(BaseModel):
    tickers: list[str]

@app.post("/api/stock/batch-sparklines")
@limiter.limit("60/minute")
def batch_sparklines(request: Request, req: SparklineRequest):
    """Return 5-day close prices for tiny sparkline charts."""
    from concurrent.futures import ThreadPoolExecutor
    tickers = [_valid_ticker(t) for t in req.tickers[:30]]

    def _fetch_spark(t):
        try:
            df = get_stock_data(t, period="5d", interval="1d")
            closes = [round(float(row["Close"]), 2) for _, row in df.iterrows()]
            return {"ticker": t, "closes": closes}
        except Exception:
            return {"ticker": t, "closes": []}

    with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as pool:
        results = list(pool.map(_fetch_spark, tickers))
    return {"sparklines": {r["ticker"]: r["closes"] for r in results}}


# ── Options analytics: IV rank, expected move, suggested structures ─────────

def _nearest_expiry(expirations: list[str], min_days: int = 5, max_days: int = 60) -> Optional[str]:
    """Pick the soonest expiry within [min_days, max_days] days from today."""
    today = _date.today()
    candidates = []
    for e in expirations or []:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
            dte = (d - today).days
            if min_days <= dte <= max_days:
                candidates.append((dte, e))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _atm_row(df, target_strike: float):
    """Return the row in an option-chain dataframe whose strike is closest to target."""
    if df is None or df.empty:
        return None
    idx = (df["strike"] - target_strike).abs().idxmin()
    return df.loc[idx]


def _mid_price(row) -> Optional[float]:
    """Mid (or last) price for an option-chain row."""
    if row is None:
        return None
    try:
        bid = float(row.get("bid") or 0)
        ask = float(row.get("ask") or 0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        last = float(row.get("lastPrice") or 0)
        return last if last > 0 else None
    except Exception:
        return None


@app.get("/api/stock/{ticker}/iv-rank")
@limiter.limit("30/minute")
def stock_iv_rank(request: Request, ticker: str):
    """Implied vs realized volatility, IV rank (from our own daily IV snapshots) and expected moves."""
    ticker = _valid_ticker(ticker)
    try:
        return options_analytics.volatility_overview(ticker)
    except LookupError:
        raise HTTPException(status_code=404, detail="No listed options for this ticker")
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/stock/{ticker}/income")
@limiter.limit("30/minute")
def stock_income(request: Request, ticker: str,
                 expiry: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """Covered-call and cash-secured-put ideas at conservative/balanced/aggressive deltas."""
    ticker = _valid_ticker(ticker)
    try:
        return options_analytics.income_ideas(ticker, expiry)
    except LookupError:
        raise HTTPException(status_code=404, detail="No listed options for this ticker")
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/stock/{ticker}/structures")
@limiter.limit("30/minute")
def stock_structures(
    request: Request,
    ticker: str,
    direction: str = Query("bull"),
    budget: float = Query(500.0, ge=50.0, le=100000.0),
):
    """Compare a long single-leg trade against a defined-risk debit spread.

    Both legs use the soonest expiry between 14 and 45 days out.
    Structures returned: long ATM call/put, and an ATM/+5% debit call spread
    (or ATM/-5% debit put spread for bears).
    """
    ticker = _valid_ticker(ticker)
    direction = direction.lower().strip()
    if direction not in ("bull", "bear"):
        raise HTTPException(status_code=400, detail="direction must be 'bull' or 'bear'")

    def _fetch():
        spot = get_quote(ticker).get("price")
        if not spot:
            raise HTTPException(status_code=404, detail="Spot price unavailable")

        try:
            expirations = options_analytics._expirations(ticker)
        except Exception:
            expirations = []
        expiry = _nearest_expiry(expirations, min_days=14, max_days=45) or (expirations[0] if expirations else None)
        if not expiry:
            raise HTTPException(status_code=404, detail="No options available")

        try:
            calls, puts = options_analytics._chain(ticker, expiry)
        except Exception as e:
            log.warning("Option chain failed for %s: %s", ticker, e)
            raise HTTPException(status_code=502, detail="Option chain unavailable")

        df = calls if direction == "bull" else puts
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="Empty option chain")

        long_row = _atm_row(df, spot)
        long_strike = float(long_row.get("strike"))
        long_mid = _mid_price(long_row)

        short_target = spot * (1.05 if direction == "bull" else 0.95)
        short_row = _atm_row(df, short_target)
        short_strike = float(short_row.get("strike"))
        short_mid = _mid_price(short_row)

        exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        dte = (exp_date - _date.today()).days
        leg_label = "Call" if direction == "bull" else "Put"
        spread_label = "Bull Call" if direction == "bull" else "Bear Put"

        structures = []

        # 1) Long single-leg
        if long_mid:
            cost_per = long_mid * 100
            contracts = max(0, int(budget // cost_per))
            if contracts > 0:
                if direction == "bull":
                    breakeven = long_strike + long_mid
                    move_needed_pct = (breakeven - spot) / spot * 100
                    max_profit = "Unlimited"
                else:
                    breakeven = long_strike - long_mid
                    move_needed_pct = (spot - breakeven) / spot * 100
                    max_profit = round((long_strike - long_mid) * 100 * contracts, 2)
                structures.append({
                    "type": f"Long {leg_label}",
                    "legs": [{"action": "BUY", "strike": long_strike, "mid": round(long_mid, 2)}],
                    "contracts": contracts,
                    "cost": round(cost_per * contracts, 2),
                    "max_loss": round(cost_per * contracts, 2),
                    "max_profit": max_profit,
                    "breakeven": round(breakeven, 2),
                    "move_needed_pct": round(move_needed_pct, 2),
                    "notes": "Pure directional bet. Pays for full IV + theta. Needs direction AND timing.",
                })

        # 2) Debit spread (defined risk)
        if long_mid and short_mid and short_strike != long_strike:
            net_debit = long_mid - short_mid
            if net_debit > 0:
                width = abs(short_strike - long_strike)
                cost_per = net_debit * 100
                max_profit_per = (width - net_debit) * 100
                contracts = max(0, int(budget // cost_per))
                if contracts > 0:
                    if direction == "bull":
                        breakeven = long_strike + net_debit
                        move_needed_pct = (breakeven - spot) / spot * 100
                    else:
                        breakeven = long_strike - net_debit
                        move_needed_pct = (spot - breakeven) / spot * 100
                    structures.append({
                        "type": f"{spread_label} Debit Spread",
                        "legs": [
                            {"action": "BUY", "strike": long_strike, "mid": round(long_mid, 2)},
                            {"action": "SELL", "strike": short_strike, "mid": round(short_mid, 2)},
                        ],
                        "contracts": contracts,
                        "cost": round(cost_per * contracts, 2),
                        "max_loss": round(cost_per * contracts, 2),
                        "max_profit": round(max_profit_per * contracts, 2),
                        "breakeven": round(breakeven, 2),
                        "move_needed_pct": round(move_needed_pct, 2),
                        "notes": "Capped profit, but cheaper, lower theta bleed, and survives a sluggish move.",
                    })

        return {
            "ticker": ticker,
            "spot": round(float(spot), 2),
            "direction": direction,
            "expiry": expiry,
            "dte": dte,
            "budget": budget,
            "structures": structures,
        }

    try:
        return get_or_fetch(f"structures:{ticker}:{direction}:{int(budget)}", _fetch, ttl=120)
    except HTTPException:
        raise
    except Exception as e:
        raise _upstream_error(e)


# ── Trader profile ───────────────────────────────────────────────────────────

class ProfileRequest(BaseModel):
    profile: Literal["day", "swing", "long"]


@app.get("/api/profile")
def profile_get(user: dict = Depends(get_current_user)):
    return {"profile": get_trader_profile(int(user["user_id"]))}


@app.put("/api/profile")
def profile_put(req: ProfileRequest, user: dict = Depends(get_current_user)):
    set_trader_profile(int(user["user_id"]), req.profile)
    return {"profile": req.profile}


# ── Custom alerts ────────────────────────────────────────────────────────────

MAX_ACTIVE_ALERTS = 50

class CustomAlertRequest(BaseModel):
    ticker: str
    kind: Literal["price_above", "price_below", "change_up", "change_down", "rsi_above", "rsi_below", "below_high"]
    value: float = Field(..., gt=0, lt=1_000_000)
    note: Optional[str] = Field(None, max_length=200)


@app.get("/api/alerts/custom")
def custom_alerts_list(ticker: Optional[str] = None, user: dict = Depends(get_current_user)):
    t = _valid_ticker(ticker) if ticker else None
    items = list_user_alerts(int(user["user_id"]), t)
    for a in items:
        a["description"] = scheduler.describe_alert(a["kind"], float(a["value"]))
    return {"items": items}


@app.post("/api/alerts/custom")
@limiter.limit("30/minute")
def custom_alerts_add(request: Request, req: CustomAlertRequest, user: dict = Depends(get_current_user)):
    uid = int(user["user_id"])
    if count_active_alerts(uid) >= MAX_ACTIVE_ALERTS:
        raise HTTPException(status_code=400, detail=f"Limit of {MAX_ACTIVE_ALERTS} active alerts reached")
    if req.kind.startswith("rsi") and req.value >= 100:
        raise HTTPException(status_code=400, detail="RSI value must be between 0 and 100")
    add_user_alert(uid, _valid_ticker(req.ticker), req.kind, req.value, (req.note or "").strip() or None)
    return {"ok": True}


@app.delete("/api/alerts/custom/{alert_id}")
def custom_alerts_delete(alert_id: int, user: dict = Depends(get_current_user)):
    if not delete_user_alert(int(user["user_id"]), alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


# ── Market overview ──────────────────────────────────────────────────────────

@app.get("/api/market/overview")
@limiter.limit("60/minute")
def market_overview(request: Request):
    try:
        return market.overview()
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/market/movers")
@limiter.limit("60/minute")
def market_movers(request: Request, kind: str = Query("gainers", pattern="^(gainers|losers|active)$")):
    return {"kind": kind, "items": market.movers(kind)}


@app.get("/api/market/my-earnings")
def market_my_earnings(user: dict = Depends(get_current_user)):
    from database import get_all_user_tickers
    from providers import finnhub_earnings_calendar
    tickers = get_all_user_tickers().get(int(user["user_id"]), set())
    items = [{"ticker": e["symbol"], "date": e.get("date"), "hour": e.get("hour"), "eps_estimate": e.get("epsEstimate")}
             for e in finnhub_earnings_calendar(14) if e.get("symbol") in tickers]
    return {"items": sorted(items, key=lambda e: e["date"] or "")}


# ── Earnings intelligence ────────────────────────────────────────────────────

@app.get("/api/stock/{ticker}/earnings-intel")
@limiter.limit("30/minute")
def stock_earnings_intel(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        return earnings_intel.earnings_intel(ticker)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/stock/{ticker}/earnings-release")
@limiter.limit("10/minute")
def stock_earnings_release(request: Request, ticker: str, user: dict = Depends(get_current_user)):
    ticker = _valid_ticker(ticker)
    try:
        return earnings_intel.earnings_release_summary(ticker)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.warning("Earnings release summary failed for %s: %s", ticker, e)
        raise HTTPException(status_code=503, detail="Summary temporarily unavailable. Try again shortly.")


# ── Setup scanner & relative strength ────────────────────────────────────────

@app.get("/api/scanner")
@limiter.limit("30/minute")
def setup_scanner(request: Request):
    data = scanner.get_scan()
    return {**data, "setup_labels": scanner.SETUPS}


@app.get("/api/stock/{ticker}/rs")
@limiter.limit("60/minute")
def stock_relative_strength(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        return get_or_fetch(f"rs:{ticker}", lambda: scanner.relative_strength(ticker), ttl=900)
    except Exception as e:
        raise _upstream_error(e)


# ── Trade journal ────────────────────────────────────────────────────────────

class JournalEntry(BaseModel):
    ticker: str
    side: Literal["long", "short"] = "long"
    shares: float = Field(..., gt=0)
    entry_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    entry_price: float = Field(..., gt=0)
    exit_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    exit_price: Optional[float] = Field(None, gt=0)
    stop: Optional[float] = Field(None, gt=0)
    target: Optional[float] = Field(None, gt=0)
    setup: Optional[str] = Field(None, max_length=40)
    notes: Optional[str] = Field(None, max_length=1000)


def _journal_payload(req: JournalEntry) -> dict:
    d = req.model_dump()
    d["ticker"] = _valid_ticker(req.ticker)
    d["setup"] = (req.setup or "").strip() or None
    return d


@app.get("/api/journal")
def journal_get(user: dict = Depends(get_current_user)):
    return journal.compute_stats(list_journal(int(user["user_id"])))


@app.post("/api/journal")
def journal_add(req: JournalEntry, user: dict = Depends(get_current_user)):
    add_journal(int(user["user_id"]), _journal_payload(req))
    return {"ok": True}


@app.put("/api/journal/{entry_id}")
def journal_update(entry_id: int, req: JournalEntry, user: dict = Depends(get_current_user)):
    if not update_journal(int(user["user_id"]), entry_id, _journal_payload(req)):
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"ok": True}


@app.delete("/api/journal/{entry_id}")
def journal_delete(entry_id: int, user: dict = Depends(get_current_user)):
    if not delete_journal(int(user["user_id"]), entry_id):
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"ok": True}


@app.get("/api/journal/coach")
@limiter.limit("6/minute")
def journal_coach(request: Request, user: dict = Depends(get_current_user)):
    uid = int(user["user_id"])
    entries = list_journal(uid)
    closed = [e for e in entries if e.get("exit_price") is not None]
    # Re-coach only when the set of closed trades changes
    key = f"coach:{uid}:{len(closed)}:{max((e['id'] for e in closed), default=0)}"
    try:
        return get_or_fetch(key, lambda: journal.ai_coach(journal.compute_stats(entries)), ttl=3600)
    except Exception as e:
        log.warning("Journal coach failed: %s", e)
        raise HTTPException(status_code=503, detail="AI coach temporarily unavailable. Try again shortly.")


# ── Long-term fundamentals & valuation ───────────────────────────────────────

@app.get("/api/stock/{ticker}/longterm")
@limiter.limit("30/minute")
def stock_long_term(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        return fundamentals.long_term(ticker)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise _upstream_error(e)


# ── Options flow & positioning ───────────────────────────────────────────────

@app.get("/api/stock/{ticker}/flow")
@limiter.limit("30/minute")
def stock_options_flow(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        return options_flow.options_flow(ticker)
    except LookupError:
        raise HTTPException(status_code=404, detail="No listed options for this ticker")
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/ideas/unusual-options")
@limiter.limit("10/minute")
def ideas_unusual_options(request: Request):
    try:
        return options_flow.unusual_scan()
    except Exception as e:
        raise _upstream_error(e)


# ── Macro, short interest, smart money ───────────────────────────────────────

@app.get("/api/market/calendar")
@limiter.limit("30/minute")
def market_calendar(request: Request, days: int = Query(7, ge=1, le=21)):
    return macro.economic_calendar(days)


@app.get("/api/stock/{ticker}/short-interest")
@limiter.limit("60/minute")
def stock_short_interest(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    rows = finra_short_interest(ticker)
    if not rows:
        raise HTTPException(status_code=404, detail="No short interest data (FINRA covers US-listed stocks)")
    latest = rows[-1]
    shares_out = ((finnhub_profile(ticker) or {}).get("shareOutstanding") or 0) * 1e6
    return {"ticker": ticker, "history": rows, "latest": latest,
            "pct_of_shares": round(latest["short_shares"] / shares_out * 100, 2) if shares_out and latest.get("short_shares") else None,
            "source": "FINRA (settlement twice a month)"}


@app.get("/api/ideas/insiders")
@limiter.limit("20/minute")
def ideas_insiders(request: Request, days: int = Query(30, ge=7, le=60)):
    return smart_money.insider_buying(days)


@app.get("/api/ideas/superinvestors")
@limiter.limit("20/minute")
def ideas_superinvestors(request: Request):
    return smart_money.superinvestors()


@app.get("/api/stock/{ticker}/smart-money")
@limiter.limit("60/minute")
def stock_smart_money(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    clusters = smart_money.insider_buying(30)
    hit = next((c for c in clusters["clusters"] + clusters["big_buys"] if c["symbol"] == ticker), None)
    return {"ticker": ticker, "superinvestors": smart_money.held_by_superinvestors(ticker), "insider_buying": hit}


# ── Portfolio insights & CSV import ──────────────────────────────────────────

@app.get("/api/portfolio/performance")
@limiter.limit("10/minute")
def portfolio_performance(request: Request, user: dict = Depends(get_current_user)):
    uid = int(user["user_id"])
    try:
        return get_or_fetch(f"perf:{uid}:{len(get_user_holdings(uid))}", lambda: portfolio_insights.performance(uid), ttl=900)
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/portfolio/dividends")
@limiter.limit("10/minute")
def portfolio_dividends(request: Request, user: dict = Depends(get_current_user)):
    uid = int(user["user_id"])
    try:
        return get_or_fetch(f"pdiv:{uid}:{len(get_user_holdings(uid))}", lambda: portfolio_insights.dividend_income(uid), ttl=3600)
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/portfolio/tax")
@limiter.limit("20/minute")
def portfolio_tax(request: Request, user: dict = Depends(get_current_user)):
    try:
        return portfolio_insights.wash_sales(int(user["user_id"]))
    except Exception as e:
        raise _upstream_error(e)


class ImportRequest(BaseModel):
    csv: str = Field(..., min_length=10, max_length=1_000_000)
    commit: bool = False


@app.post("/api/portfolio/import")
@limiter.limit("10/minute")
def portfolio_import(request: Request, req: ImportRequest, user: dict = Depends(get_current_user)):
    try:
        parsed = portfolio_insights.parse_broker_csv(req.csv)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if req.commit:
        parsed["imported"] = portfolio_insights.import_rows(int(user["user_id"]), parsed["rows"])
    return parsed


@app.get("/api/weekly-review")
@limiter.limit("6/minute")
def weekly_review(request: Request, refresh: bool = False, user: dict = Depends(get_current_user)):
    from database import get_all_user_tickers
    tickers = get_all_user_tickers().get(int(user["user_id"]), set())
    try:
        r = scheduler.get_or_create_weekly(int(user["user_id"]), tickers, force=refresh)
    except Exception as e:
        raise _upstream_error(e)
    return r or {"empty": True}


# ── Investment theses ────────────────────────────────────────────────────────

class ThesisRequest(BaseModel):
    thesis: str = Field(..., min_length=10, max_length=2000)


@app.get("/api/thesis")
def thesis_list(user: dict = Depends(get_current_user)):
    return {"items": list_theses(int(user["user_id"]))}


@app.get("/api/thesis/{ticker}")
def thesis_get(ticker: str, user: dict = Depends(get_current_user)):
    return get_thesis(int(user["user_id"]), _valid_ticker(ticker)) or {"empty": True}


@app.put("/api/thesis/{ticker}")
def thesis_put(ticker: str, req: ThesisRequest, user: dict = Depends(get_current_user)):
    return thesis.upsert(int(user["user_id"]), _valid_ticker(ticker), req.thesis)


@app.delete("/api/thesis/{ticker}")
def thesis_delete(ticker: str, user: dict = Depends(get_current_user)):
    if not delete_thesis(int(user["user_id"]), _valid_ticker(ticker)):
        raise HTTPException(status_code=404, detail="No thesis for this ticker")
    return {"ok": True}


@app.post("/api/thesis/{ticker}/check")
@limiter.limit("6/minute")
def thesis_check(request: Request, ticker: str, user: dict = Depends(get_current_user)):
    try:
        return thesis.check(int(user["user_id"]), _valid_ticker(ticker))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.warning("Thesis check failed for %s: %s", ticker, e)
        raise HTTPException(status_code=503, detail="AI is temporarily unavailable. Try again shortly.")


# ── Day trading: key levels, stocks in play, strategy tester ─────────────────

@app.get("/api/stock/{ticker}/levels")
@limiter.limit("60/minute")
def stock_levels(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    try:
        return intraday.key_levels(ticker)
    except Exception as e:
        raise _upstream_error(e, 404)


@app.get("/api/ideas/in-play")
@limiter.limit("20/minute")
def ideas_in_play(request: Request, universe: Optional[Literal["all", "sp500", "ndx"]] = "all"):
    try:
        return intraday.stocks_in_play(None if universe == "all" else universe)
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/backtest/strategies")
def backtest_strategies():
    return {"strategies": backtester.STRATEGIES, "timeframes": list(backtester.TIMEFRAMES)}


def _bt_overrides(request: Request) -> dict:
    out = {}
    for k, v in request.query_params.items():
        if k.startswith("p_"):
            try:
                out[k[2:]] = float(v)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Parameter {k[2:]} must be a number")
            if not 0 <= out[k[2:]] <= 500:
                raise HTTPException(status_code=400, detail=f"Parameter {k[2:]} is out of range")
    return out


@app.get("/api/backtest")
@limiter.limit("20/minute")
def backtest_run(request: Request, ticker: str,
                 timeframe: Literal["1m", "3m", "5m", "15m", "1h", "1d"] = "5m",
                 strategy: str = "ema_cross",
                 side: Literal["both", "long", "short"] = "both",
                 cost_bps: float = Query(3.0, ge=0, le=50),
                 stop_pct: float = Query(0.0, ge=0, le=50),
                 target_pct: float = Query(0.0, ge=0, le=100)):
    ticker = _valid_ticker(ticker)
    if strategy not in backtester.STRATEGIES:
        raise HTTPException(status_code=400, detail="Unknown strategy")
    overrides = _bt_overrides(request)
    try:
        return backtester.run(ticker, timeframe, strategy, overrides, side, cost_bps, stop_pct, target_pct)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/backtest/compare")
@limiter.limit("10/minute")
def backtest_compare(request: Request, ticker: str,
                     timeframe: Literal["1m", "3m", "5m", "15m", "1h", "1d"] = "5m",
                     cost_bps: float = Query(3.0, ge=0, le=50)):
    ticker = _valid_ticker(ticker)
    try:
        return backtester.compare(ticker, timeframe, cost_bps)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise _upstream_error(e)
