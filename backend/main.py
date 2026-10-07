from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from pydantic import BaseModel
from typing import Optional
from contextlib import asynccontextmanager
from datetime import datetime, date as _date
import logging
import math
import re
from typing import Literal
from pydantic import Field
from portfolio_models import AccountingEntryRequest, HoldingRequest, HoldingUpdateRequest, OptionRequest, OptionUpdateRequest, ClosedOptionRequest, LifecycleRequest, ACCOUNT_PATTERN
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from api_common import limiter, get_current_user, valid_ticker as _valid_ticker, upstream_error as _upstream_error

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
import wheel
import options_desk
import next_steps
import track_record
from providers import finnhub_enabled, finnhub_quote, finnhub_peers, finnhub_profile, \
    finra_short_interest
from alerts import check_alerts, technical_events
from cache import get_or_fetch, stats as cache_stats
from database import (
    get_user_holdings, add_user_holding, update_user_holding, delete_user_holding, sell_user_holding,
    sell_user_holding_by_lot,
    get_user_options, add_user_option, close_user_option, update_user_option, delete_user_option,
    assign_user_option, kv_set,
    get_user_transactions, get_user_watchlist, get_closed_trades, get_closed_options, delete_closed_trade, delete_closed_option, record_closed_option,
    list_notifications, mark_notifications_read, get_ntfy_topic, set_ntfy_topic,
    get_trader_profile, set_trader_profile, list_user_alerts, add_user_alert, delete_user_alert,
    count_active_alerts, list_journal, add_journal, update_journal, delete_journal,
    get_thesis, list_theses, delete_thesis,
    in_account,
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


@asynccontextmanager
async def _lifespan(_app):
    if SCHEDULER_ENABLED:
        scheduler.start()
    yield


app = FastAPI(title="StockPilot API", version="3.0.0", lifespan=_lifespan)


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
def api_health_check():
    """Health check that pings the DB to keep Supabase alive."""
    conn = None
    try:
        from database import get_db, _release
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        return {"status": "ok", "db": "connected"}
    except Exception:
        log.error("Health check database unavailable")
        raise HTTPException(status_code=503, detail="Database unavailable")
    finally:
        if conn is not None:
            _release(conn)


@app.get("/api/status")
@limiter.limit("10/minute")
def system_status_endpoint(request: Request, user: dict = Depends(get_current_user)):
    """Configured services, provider reachability and scheduler activity. Never returns secret values."""
    import system_status
    return system_status.report()

# ── Rate limiting ───────────────────────────────────────────────────────────

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


# ── Route modules ───────────────────────────────────────────────────────────

import routes_accounts
import routes_auth
import routes_research
import routes_watchlist

app.include_router(routes_auth.router)
app.include_router(routes_watchlist.router)
app.include_router(routes_accounts.router)
app.include_router(routes_research.router)


@app.get("/api/cache/stats")
def cache_stats_endpoint(user: dict = Depends(get_current_user)):
    return cache_stats()


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
def portfolio_summary_endpoint(user: dict = Depends(get_current_user), account: Optional[str] = None):
    from datetime import timezone
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
    holdings = [h for h in get_user_holdings(user["user_id"]) if in_account(h, account)]
    if not holdings:
        return {"total_invested": 0, "total_current": 0, "total_pnl": 0, "total_pnl_pct": 0, "holdings": [], "as_of": as_of}

    # Real-time Finnhub quotes first; one batched yfinance download for anything left
    import yfinance as yf
    unique_tickers = list({h["ticker"] for h in holdings})
    current_prices = {}
    if finnhub_enabled():
        for t in unique_tickers:
            try:
                q = finnhub_quote(t)
                if q and math.isfinite(float(q["c"])) and float(q["c"]) > 0:
                    current_prices[t] = round(float(q["c"]), 2)
            except Exception:
                pass
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
        current = current_prices.get(ticker)
        current = float(current) if current is not None else None
        if current is not None and (not math.isfinite(current) or current <= 0):
            current = None
        invested = shares * buy_price
        current_val = shares * current if current is not None else None
        pnl = current_val - invested if current_val is not None else None
        pnl_pct = (pnl / invested * 100) if invested and pnl is not None else None
        total_invested += invested
        total_current += current_val or 0
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
            "invested": round(invested, 2), "current_value": round(current_val, 2) if current_val is not None else None,
            "pnl": round(pnl, 2) if pnl is not None else None, "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "sector": sector, "account": h.get("account") or "Default",
        })
    total_pnl = total_current - total_invested
    incomplete = any(holding["current_price"] is None for holding in details)
    return {
        "total_invested": round(total_invested, 2),
        "total_current": None if incomplete else round(total_current, 2),
        "total_pnl": None if incomplete else round(total_pnl, 2),
        "total_pnl_pct": None if incomplete else round((total_pnl / total_invested * 100) if total_invested else 0, 2),
        "incomplete": incomplete,
        "holdings": details,
        "as_of": as_of,
    }


@app.post("/api/portfolio/buy")
def portfolio_buy(req: HoldingRequest, user: dict = Depends(get_current_user)):
    return add_user_holding(user["user_id"], req.ticker, req.shares, req.price, account=req.account)


@app.post("/api/portfolio/sell")
def portfolio_sell(req: HoldingRequest, user: dict = Depends(get_current_user)):
    try:
        result = sell_user_holding(user["user_id"], req.ticker, req.shares, req.price, req.account)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    if result is None:
        raise HTTPException(status_code=404, detail=f"{req.ticker} not found in portfolio")
    return result


@app.post("/api/portfolio/sell-lot/{holding_id}")
def portfolio_sell_lot(holding_id: int, req: HoldingRequest, user: dict = Depends(get_current_user)):
    try:
        result = sell_user_holding_by_lot(user["user_id"], holding_id, req.shares, req.price)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    if result is None:
        raise HTTPException(status_code=404, detail="Lot not found")
    return result


@app.put("/api/portfolio/{holding_id:int}")
def portfolio_edit(holding_id: int, req: HoldingUpdateRequest, user: dict = Depends(get_current_user)):
    account = req.account if "account" in req.model_fields_set else ...
    result = update_user_holding(user["user_id"], holding_id, req.ticker, req.shares, req.price, account,
                                 req.acquired.isoformat() if req.acquired else None)
    if result is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    return result


@app.delete("/api/portfolio/{holding_id:int}")
def portfolio_delete(holding_id: int, user: dict = Depends(get_current_user)):
    result = delete_user_holding(user["user_id"], holding_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    return result


@app.get("/api/portfolio/history")
def portfolio_history(user: dict = Depends(get_current_user)):
    return get_user_transactions(user["user_id"])


@app.get("/api/accounting/events")
def accounting_events(after_id: int = 0, limit: int = 200, user: dict = Depends(get_current_user)):
    import accounting
    try:
        return {"events": accounting.list_events(user["user_id"], after_id, limit)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/accounting/report")
def accounting_report(user: dict = Depends(get_current_user)):
    import accounting
    return accounting.report(user["user_id"])


@app.get("/api/account-transfer/export")
def export_account_data(user: dict = Depends(get_current_user)):
    import account_transfer
    from fastapi.responses import JSONResponse
    try:
        return JSONResponse(account_transfer.export_account(user["user_id"]), headers={"Cache-Control": "no-store"})
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


async def _transfer_body(request):
    import account_transfer
    import json
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > account_transfer.MAX_BYTES:
            raise HTTPException(status_code=413, detail="Transfer file exceeds 10 MB")
    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        raise HTTPException(status_code=400, detail="Invalid transfer JSON file")


@app.post("/api/account-transfer/preview")
async def preview_account_data(request: Request, user: dict = Depends(get_current_user)):
    import account_transfer
    from starlette.concurrency import run_in_threadpool
    from fastapi.responses import JSONResponse
    body = await _transfer_body(request)
    try:
        result = await run_in_threadpool(account_transfer.preview_import, user["user_id"], body)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except (ValueError, RecursionError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/account-transfer/import")
async def import_account_data(request: Request, user: dict = Depends(get_current_user)):
    import account_transfer
    from starlette.concurrency import run_in_threadpool
    from fastapi.responses import JSONResponse
    body = await _transfer_body(request)
    if not isinstance(body, dict) or body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="Confirm import into the currently signed-in account")
    try:
        result = await run_in_threadpool(account_transfer.import_account, user["user_id"], body.get("package"))
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except (ValueError, KeyError, RecursionError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/accounting/entries")
def accounting_entry(req: AccountingEntryRequest, user: dict = Depends(get_current_user)):
    import accounting
    try:
        return accounting.record_entry(user["user_id"], req)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/portfolio/closed")
def closed_trades_endpoint(user: dict = Depends(get_current_user), account: Optional[str] = None):
    trades = [t for t in get_closed_trades(user["user_id"]) if in_account(t, account)]
    total_pnl = sum(t["pnl"] for t in trades)
    return {"total_realized_pnl": round(total_pnl, 2), "trades": trades}


@app.get("/api/portfolio/options/closed")
def closed_options_endpoint(user: dict = Depends(get_current_user), account: Optional[str] = None):
    trades = [t for t in get_closed_options(user["user_id"]) if in_account(t, account)]
    total_pnl = sum(t["pnl"] for t in trades)
    return {"total_realized_pnl": round(total_pnl, 2), "trades": trades,
            "total_fees": round(sum(t["fees"] for t in trades), 2),
            "total_net_pnl": round(sum(t["net_pnl"] for t in trades), 2)}


@app.post("/api/portfolio/options/closed")
def record_closed_option_endpoint(req: ClosedOptionRequest, user: dict = Depends(get_current_user)):
    try:
        return record_closed_option(user["user_id"], req)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))


@app.put("/api/portfolio/options/closed/{trade_id}")
def update_closed_option_endpoint(trade_id: int, req: ClosedOptionRequest, user: dict = Depends(get_current_user)):
    try:
        return record_closed_option(user["user_id"], req, trade_id=trade_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))


@app.delete("/api/portfolio/closed/{trade_id}")
def closed_trade_delete(trade_id: int, user: dict = Depends(get_current_user)):
    if not delete_closed_trade(int(user["user_id"]), trade_id):
        raise HTTPException(status_code=404, detail="Closed trade not found")
    return {"ok": True}


@app.delete("/api/portfolio/options/closed/{trade_id}")
def closed_option_delete(trade_id: int, user: dict = Depends(get_current_user)):
    if not delete_closed_option(int(user["user_id"]), trade_id):
        raise HTTPException(status_code=404, detail="Closed option not found")
    return {"ok": True}


# ── Options (auth required) ────────────────────────────────────────────────

@app.get("/api/portfolio/options/summary")
def options_summary_endpoint(user: dict = Depends(get_current_user), account: Optional[str] = None):
    import yfinance as yf
    from datetime import timezone
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
    options = [o for o in get_user_options(user["user_id"]) if in_account(o, account)]
    if not options:
        return {"total_cost": 0, "total_value": 0, "total_pnl": 0, "total_pnl_pct": 0, "options": [], "as_of": as_of}

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
                current_prices[o["ticker"]] = p if p and math.isfinite(p) and p > 0 else None
            except Exception:
                try:
                    price = getattr(yf.Ticker(yf_sym).fast_info, "last_price", None)
                    current_prices[o["ticker"]] = price if price and math.isfinite(price) and price > 0 else None
                except Exception:
                    current_prices[o["ticker"]] = None

    # Cache option chains per (ticker, expiry)
    chain_cache: dict[tuple[str, str], dict] = {}
    today = _date.today()

    def _get_market_price(ticker: str, opt_type: str, strike: float, expiry: str) -> dict:
        yf_sym = _yf_ticker(ticker)
        key = (yf_sym, expiry)
        if key not in chain_cache:
            try:
                # Only the exact contract counts: a neighbouring expiry or strike would give a wrong mark
                listed = expiry in options_analytics._expirations(yf_sym)
                calls, puts = options_analytics._chain(yf_sym, expiry) if listed else (None, None)
                chain_cache[key] = {"calls": calls, "puts": puts}
            except Exception:
                chain_cache[key] = {"calls": None, "puts": None}

        cached = chain_cache[key]
        df = cached["calls"] if opt_type == "call" else cached["puts"]
        if df is None or df.empty:
            return {}
        match = df[df["strike"] == strike]
        if match.empty:
            return {}
        row = match.iloc[0]
        def number(key):
            value = float(row.get(key, 0) or 0)
            return value if math.isfinite(value) else 0
        return {
            "last_price": number("lastPrice"), "bid": number("bid"), "ask": number("ask"),
            "iv": number("impliedVolatility"), "volume": int(number("volume")),
            "open_interest": int(number("openInterest")),
        }

    details = []
    for o in options:
        ticker = o["ticker"]
        contracts = o["contracts"]
        premium = o["premium"]
        strike = o["strike"]
        current = current_prices.get(ticker)
        position = o.get("position", "long")
        opt_type = o["option_type"]

        try:
            expiry_date = datetime.strptime(o["expiry"], "%Y-%m-%d").date()
            dte = max((expiry_date - today).days, 0)
        except (ValueError, KeyError):
            dte = 0

        intrinsic = (max(current - strike, 0) if opt_type == "call" else max(strike - current, 0)) if current else None

        market = _get_market_price(ticker, opt_type, strike, o["expiry"])
        quoted = bool(market and market["bid"] > 0 and market["ask"] >= market["bid"] and current)
        if quoted:
            bid, ask = market.get("bid", 0), market.get("ask", 0)
            market_price = (bid + ask) / 2 if bid > 0 and ask > 0 else market.get("last_price", 0)
            iv, volume, oi = market.get("iv", 0), market.get("volume", 0), market.get("open_interest", 0)
        else:
            market_price, iv, volume, oi = None, 0, 0, 0

        cost = premium * 100 * contracts
        current_value = market_price * 100 * contracts if quoted else None
        pnl = ((current_value - cost) if position == "long" else (cost - current_value)) if quoted else None
        pnl_pct = (pnl / cost * 100) if quoted and cost else None

        details.append({
            "id": o["id"], "ticker": ticker, "type": opt_type, "position": position,
            "strike": strike, "expiry": o["expiry"], "dte": dte,
            "time_to_expiry_years": options_analytics._years(o["expiry"]) if options_analytics._live(o["expiry"]) else 0,
            "contracts": contracts, "premium": premium, "cost": round(cost, 2),
            "current_price": current, "intrinsic": round(intrinsic, 2) if intrinsic is not None else None,
            "market_price": round(market_price, 2) if quoted else None, "quoted": quoted,
            "mark_status": "midpoint_estimate" if quoted else "unavailable",
            "bid": round(market.get("bid", 0), 2) if market else 0,
            "ask": round(market.get("ask", 0), 2) if market else 0,
            "iv": round(iv * 100, 1), "volume": volume, "open_interest": oi,
            "est_value": round(market_price, 2) if quoted else None,
            "pnl": round(pnl, 2) if pnl is not None else None, "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "account": o.get("account") or "Default", "expired": not options_analytics._live(o["expiry"]),
        })

    total_cost = sum(d["cost"] for d in details)
    incomplete = any(not detail["quoted"] for detail in details)
    total_pnl = sum(d["pnl"] or 0 for d in details)
    total_market = sum((d["market_price"] or 0) * d["contracts"] * 100 for d in details)
    return {
        "total_cost": round(total_cost, 2),
        "total_value": None if incomplete else round(total_market, 2),
        "total_pnl": None if incomplete else round(total_pnl, 2),
        "total_pnl_pct": None if incomplete else round((total_pnl / total_cost * 100) if total_cost else 0, 2),
        "incomplete": incomplete,
        "options": details,
        "as_of": as_of,
    }


def _link_cycle(user_id: int, result: dict, cycle: str | None) -> dict:
    """Link the new closed-option record to a wheel cycle; the close itself has already been recorded."""
    if cycle and result and result.get("closed_id"):
        import accounts
        try:
            accounts.link_closed_option(user_id, result["closed_id"], result["contracts"], cycle)
            result["cycle"] = cycle.strip()
        except (ValueError, LookupError) as error:
            result["cycle_error"] = f"Closed, but not linked to the cycle: {error}"
    return result


@app.post("/api/portfolio/options/buy")
def options_buy(req: OptionRequest, user: dict = Depends(get_current_user)):
    return add_user_option(user["user_id"], req.ticker, req.option_type, req.strike,
                          req.expiry, req.premium, req.contracts, req.position, account=req.account)


@app.post("/api/portfolio/options/close")
def options_close(req: OptionRequest, user: dict = Depends(get_current_user)):
    try:
        result = close_user_option(user["user_id"], req.ticker, req.option_type, req.strike,
                                   req.expiry, req.premium, req.contracts, req.position, option_id=req.option_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    if result is None:
        raise HTTPException(status_code=404, detail="Option not found in portfolio")
    return _link_cycle(int(user["user_id"]), result, req.cycle)


@app.post("/api/portfolio/options/{option_id}/expire")
def options_expire(option_id: int, req: Optional[LifecycleRequest] = None, user: dict = Depends(get_current_user)):
    """Record an expired contract as expired worthless: closed at $0 on its expiry date."""
    uid = int(user["user_id"])
    option = next((o for o in get_user_options(uid) if o["id"] == option_id), None)
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")
    if options_analytics._live(option["expiry"]):
        raise HTTPException(status_code=400, detail="This option hasn't expired yet")
    result = close_user_option(uid, option["ticker"], option["option_type"], option["strike"], option["expiry"], 0.0,
                               option["contracts"], option["position"], option_id=option_id,
                               closed_at=f"{option['expiry']} 20:00:00")
    return _link_cycle(uid, {**result, "action": "EXPIRED"}, req.cycle if req else None)


@app.put("/api/portfolio/options/{option_id}")
def options_edit(option_id: int, req: OptionUpdateRequest, user: dict = Depends(get_current_user)):
    account = req.account if "account" in req.model_fields_set else ...
    result = update_user_option(user["user_id"], option_id, req.ticker, req.option_type,
                                req.strike, req.expiry, req.premium, req.contracts, req.position, account)
    if result is None:
        raise HTTPException(status_code=404, detail="Option not found")
    return result


@app.delete("/api/portfolio/options/{option_id}")
def options_delete(option_id: int, user: dict = Depends(get_current_user)):
    result = delete_user_option(user["user_id"], option_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Option not found")
    return result


@app.post("/api/portfolio/options/{option_id}/assign")
def options_assign(option_id: int, req: Optional[LifecycleRequest] = None, user: dict = Depends(get_current_user)):
    """Short put assigned → shares bought at the strike; short call assigned → shares sold at the strike."""
    try:
        result = assign_user_option(int(user["user_id"]), option_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _link_cycle(int(user["user_id"]), result, req.cycle if req else None)


class IncomeGoal(BaseModel):
    goal: Optional[float] = Field(None, ge=0, le=10_000_000)


@app.get("/api/portfolio/premium-income")
@limiter.limit("30/minute")
def portfolio_premium_income(request: Request, user: dict = Depends(get_current_user)):
    return options_desk.premium_income(int(user["user_id"]))


@app.put("/api/portfolio/income-goal")
@limiter.limit("20/minute")
def portfolio_income_goal(request: Request, req: IncomeGoal, user: dict = Depends(get_current_user)):
    kv_set(f"income-goal:{int(user['user_id'])}", req.goal or None)
    return {"goal": req.goal or None}


# ── Screener (auth required; watchlist routes live in routes_watchlist.py) ──────

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
        info = options_analytics.earnings_info(ticker)
        earnings_date = info.get("next")

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
            "earnings_confirmed": info.get("next_confirmed"),
            "last_earnings": info.get("last"),
            "days_since_earnings": info.get("days_since_last"),
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


# ── Options analytics: IV rank, expected move, suggested structures ─────────


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


@app.get("/api/stock/{ticker}/option-expirations")
@limiter.limit("30/minute")
def stock_option_expirations(request: Request, ticker: str):
    ticker = _valid_ticker(ticker)
    return {"expirations": [
        {"date": expiry, "dte": options_analytics._dte(expiry)}
        for expiry in sorted(options_analytics._expirations(ticker))
        if options_analytics._live(expiry)
    ]}


@app.get("/api/stock/{ticker}/assigned-calls")
@limiter.limit("20/minute")
def stock_assigned_calls(request: Request, ticker: str,
                         cost_basis: float = Query(..., gt=0, le=100000),
                         shares: int = Query(100, ge=100, le=1000000),
                         cadence: str = Query("all", pattern="^(all|standard|weekly|leaps)$")):
    """Covered calls for assigned shares (wheel step 2), never below the cost basis."""
    ticker = _valid_ticker(ticker)
    try:
        return options_analytics.assigned_calls(ticker, cost_basis, shares, cadence)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/stock/{ticker}/roll")
@limiter.limit("20/minute")
def stock_roll(request: Request, ticker: str,
               strategy: str = Query(..., pattern="^(cc|csp|pcs)$"),
               expiry: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
               short_strike: float = Query(..., gt=0, le=100000),
               long_strike: Optional[float] = Query(None, gt=0, le=100000),
               credit: Optional[float] = Query(None, ge=0, le=100000)):
    """Credit rolls (out / out-and-away) and alternatives for a tested covered call, CSP or put credit spread."""
    ticker = _valid_ticker(ticker)
    try:
        return options_analytics.roll_ideas(ticker, strategy, expiry, short_strike, long_strike, credit)
    except LookupError:
        raise HTTPException(status_code=404, detail="No listed options for this ticker")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/stock/{ticker}/earnings-moves")
@limiter.limit("30/minute")
def stock_earnings_moves(request: Request, ticker: str):
    """Actual moves on past reports vs the move options price for the next one."""
    ticker = _valid_ticker(ticker)
    try:
        return options_analytics.earnings_moves(ticker)
    except Exception as e:
        raise _upstream_error(e)


# ── Options desk: position actions, earnings exposure, wheel ledger, reviews ──

def _options_version(uid: int) -> str:
    import hashlib
    import json
    payload = [get_user_options(uid), get_user_holdings(uid)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


@app.get("/api/portfolio/options/actions")
@limiter.limit("20/minute")
def portfolio_option_actions(request: Request, user: dict = Depends(get_current_user)):
    uid = int(user["user_id"])
    try:
        return get_or_fetch(f"opt-actions:{uid}:{_options_version(uid)}", lambda: options_desk.position_actions(uid), ttl=120)
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/portfolio/next-steps")
@limiter.limit("20/minute")
def portfolio_next_steps(request: Request, user: dict = Depends(get_current_user)):
    uid = int(user["user_id"])
    try:
        actions = get_or_fetch(f"opt-actions:{uid}:{_options_version(uid)}", lambda: options_desk.position_actions(uid), ttl=120)
        return next_steps.build(uid, actions)
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/portfolio/earnings")
@limiter.limit("20/minute")
def portfolio_earnings(request: Request, user: dict = Depends(get_current_user)):
    uid = int(user["user_id"])
    key = f"pearn:{uid}:{len(get_user_holdings(uid))}:{_options_version(uid)}"
    try:
        return get_or_fetch(key, lambda: options_desk.earnings_exposure(uid), ttl=1800)
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/portfolio/wheel-ledger")
@limiter.limit("20/minute")
def portfolio_wheel_ledger(request: Request, user: dict = Depends(get_current_user)):
    try:
        return options_desk.wheel_ledger(int(user["user_id"]))
    except Exception as e:
        raise _upstream_error(e)


@app.get("/api/portfolio/options/review")
@limiter.limit("20/minute")
def portfolio_options_review(request: Request, user: dict = Depends(get_current_user)):
    return options_desk.options_review(int(user["user_id"]))


@app.get("/api/portfolio/options/coach")
@limiter.limit("6/minute")
def portfolio_options_coach(request: Request, user: dict = Depends(get_current_user)):
    import hashlib
    import json
    uid = int(user["user_id"])
    closed = get_closed_options(uid)
    version = hashlib.sha256(json.dumps(closed, sort_keys=True, default=str).encode()).hexdigest()[:24]
    key = f"opt-coach:{uid}:{version}"
    try:
        return get_or_fetch(key, lambda: options_desk.options_coach(uid), ttl=3600)
    except Exception as e:
        log.warning("Options coach failed: %s", e)
        raise HTTPException(status_code=503, detail="AI review temporarily unavailable. Try again shortly.")


@app.get("/api/ideas/track-record")
@limiter.limit("20/minute")
def ideas_track_record(request: Request):
    return get_or_fetch("idea-track-record", track_record.summary, ttl=600)


@app.get("/api/ideas/wheel/plan")
@limiter.limit("20/minute")
def ideas_wheel_plan(request: Request, capital: float = Query(..., ge=1000, le=10_000_000),
                     max_pct: float = Query(25, ge=5, le=100), max_per_sector: int = Query(2, ge=1, le=10),
                     short_dated: bool = False,
                     user: dict = Depends(get_current_user)):
    return wheel.plan(capital, max_pct, max_per_sector, user_id=int(user["user_id"]), short_dated=short_dated)


@app.get("/api/stock/{ticker}/structures")
@limiter.limit("30/minute")
def stock_structures(
    request: Request,
    ticker: str,
    direction: str = Query("bull", pattern="^(bull|bear)$"),
    budget: float = Query(500.0, ge=50.0, le=1000000.0),
    risk: str = Query("moderate", pattern="^(extreme|high|moderate|low)$"),
):
    """Shares vs long option vs debit spread, sized to the budget, with the expiry set by risk appetite."""
    ticker = _valid_ticker(ticker)
    try:
        return options_analytics.directional_ideas(ticker, direction, budget, risk)
    except LookupError:
        raise HTTPException(status_code=404, detail="No listed options for this ticker")
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
    from datetime import date, timedelta
    tickers = get_all_user_tickers().get(int(user["user_id"]), set())
    items, unavailable = [], []
    today, end = date.today().isoformat(), (date.today() + timedelta(days=14)).isoformat()
    for ticker in sorted(tickers):
        info = options_analytics.earnings_info(ticker)
        upcoming = info.get("next")
        if not upcoming:
            unavailable.append(ticker)
        elif today <= upcoming <= end:
            items.append({"ticker": ticker, "date": upcoming, "eps_estimate": None,
                          "hour": {"before open": "bmo", "after close": "amc"}.get(info.get("next_timing"))})
    return {"items": sorted(items, key=lambda event: event["date"]), "unavailable": unavailable}


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
    account: Optional[str] = Field(None, pattern=ACCOUNT_PATTERN)


def _journal_payload(req: JournalEntry) -> dict:
    from database import account_name
    d = req.model_dump()
    d["ticker"] = _valid_ticker(req.ticker)
    d["setup"] = (req.setup or "").strip() or None
    d["account"] = account_name(req.account)
    return d


@app.get("/api/journal")
def journal_get(user: dict = Depends(get_current_user), account: Optional[str] = None):
    return journal.compute_stats([e for e in list_journal(int(user["user_id"])) if in_account(e, account)])


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


@app.get("/api/ideas/wheel")
@limiter.limit("20/minute")
def ideas_wheel(request: Request, short_dated: bool = False):
    """Quality stocks ranked by the risk-adjusted premium of a conservative cash-secured put."""
    return wheel.get_wheel(short_dated=short_dated)


@app.post("/api/ideas/wheel/ask/{ticker}")
@limiter.limit("6/minute")
def ideas_wheel_ask(request: Request, ticker: str, user: dict = Depends(get_current_user)):
    """Wheel suitability checks and put-strike ladder for any ticker, plus an AI verdict."""
    ticker = _valid_ticker(ticker)
    try:
        return wheel.ask(ticker)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
    kind: Literal["positions", "history", "activity"] = "positions"
    account: Optional[str] = Field(None, pattern=ACCOUNT_PATTERN)
    source_account: Optional[str] = Field(None, max_length=120)


@app.post("/api/portfolio/import")
@limiter.limit("10/minute")
def portfolio_import(request: Request, req: ImportRequest, user: dict = Depends(get_current_user)):
    try:
        if req.kind == "history":
            parsed = portfolio_insights.parse_history_csv(req.csv)
        elif req.kind == "activity":
            parsed = portfolio_insights.parse_activity_csv(req.csv, req.source_account)
        else:
            parsed = portfolio_insights.parse_broker_csv(req.csv, req.source_account)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if req.commit:
        uid = int(user["user_id"])
        if req.kind == "history":
            parsed["result"] = portfolio_insights.import_history(uid, parsed["rows"], req.account)
            parsed["imported"] = parsed["result"]["imported"]
        else:
            parsed["imported"] = portfolio_insights.import_rows(uid, parsed["rows"], req.account)
            parsed["cash"] = portfolio_insights.add_money_market_cash(uid, req.account, parsed.get("money_market_total"))
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


@app.get("/api/market/context/{kind}")
@limiter.limit("20/minute")
def external_market_context(request: Request, kind: Literal["attention", "predictions"]):
    from market_context import get_context
    return get_context(kind)


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
