"""Free-tier market data providers: Finnhub, Alpaca, Twelve Data, SEC EDGAR.

Every function returns None / [] on failure so callers can fall back to yfinance.
"""

import logging
import math
import re
import threading
import time
from datetime import date, timedelta

import pandas as pd
import requests

from cache import get_or_fetch
from config import ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY, FINNHUB_API_KEY, FINNHUB_RATE_PER_MIN, TWELVEDATA_API_KEY, SEC_USER_AGENT

log = logging.getLogger(__name__)
_session = requests.Session()
_session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=32))


# ── Finnhub ──────────────────────────────────────────────────────────────

class _TokenBucket:
    """Non-blocking limiter: when empty, callers skip Finnhub and fall back."""

    def __init__(self, per_minute: int):
        self.capacity = max(1, per_minute)
        self.tokens = float(self.capacity)
        self.rate = self.capacity / 60.0
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def take(self) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False


_finnhub_bucket = _TokenBucket(FINNHUB_RATE_PER_MIN)


def finnhub_enabled() -> bool:
    return bool(FINNHUB_API_KEY)


def _finnhub(path: str, params: dict | None = None):
    if not FINNHUB_API_KEY or not _finnhub_bucket.take():
        return None
    try:
        resp = _session.get(
            f"https://finnhub.io/api/v1{path}",
            params=params or {},
            headers={"X-Finnhub-Token": FINNHUB_API_KEY},
            timeout=8,
        )
        if resp.status_code != 200:
            log.warning("Finnhub %s -> %s", path, resp.status_code)
            return None
        return resp.json()
    except Exception as e:
        log.warning("Finnhub %s failed: %s", path, e)
        return None


def _is_plain_equity(ticker: str) -> bool:
    # Finnhub free tier covers US equities; indices (^VIX) and futures (ES=F) are not included.
    return not any(c in ticker for c in "^=")


def _cached(key: str, ttl: int, fetch, default):
    """Cache successful fetches only; fetch raises LookupError when Finnhub is unavailable."""
    try:
        return get_or_fetch(key, fetch, ttl=ttl)
    except LookupError:
        return default


def finnhub_quote(ticker: str) -> dict | None:
    if not _is_plain_equity(ticker):
        return None

    def _fetch():
        q = _finnhub("/quote", {"symbol": ticker})
        # Finnhub returns zeros for unknown symbols
        if not q or not q.get("c"):
            raise LookupError(ticker)
        return q

    return _cached(f"fh:quote:{ticker}", 30, _fetch, None)


def finnhub_profile(ticker: str) -> dict | None:
    if not _is_plain_equity(ticker):
        return None

    def _fetch():
        p = _finnhub("/stock/profile2", {"symbol": ticker})
        if not p or not p.get("name"):
            raise LookupError(ticker)
        return p

    return _cached(f"fh:profile:{ticker}", 86400, _fetch, None)


def finnhub_basic_financials(ticker: str) -> dict | None:
    if not _is_plain_equity(ticker):
        return None

    def _fetch():
        m = _finnhub("/stock/metric", {"symbol": ticker, "metric": "all"})
        if not m or not m.get("metric"):
            raise LookupError(ticker)
        return m["metric"]

    return _cached(f"fh:metric:{ticker}", 3600, _fetch, None)


def _list_fetch(path: str, params: dict, transform=lambda d: d):
    def _fetch():
        data = _finnhub(path, params)
        if data is None:
            raise LookupError(path)
        return transform(data)
    return _fetch


def finnhub_company_news(ticker: str, days: int = 7) -> list[dict]:
    if not _is_plain_equity(ticker):
        return []
    today = date.today()
    params = {"symbol": ticker, "from": (today - timedelta(days=days)).isoformat(), "to": today.isoformat()}
    fetch = _list_fetch("/company-news", params, lambda d: d if isinstance(d, list) else [])
    return _cached(f"fh:news:{ticker}", 600, fetch, [])


def finnhub_recommendations(ticker: str) -> list[dict]:
    if not _is_plain_equity(ticker):
        return []
    fetch = _list_fetch("/stock/recommendation", {"symbol": ticker},
                        lambda d: d if isinstance(d, list) else [])
    return _cached(f"fh:recs:{ticker}", 21600, fetch, [])


def finnhub_peers(ticker: str) -> list[str]:
    if not _is_plain_equity(ticker):
        return []
    fetch = _list_fetch("/stock/peers", {"symbol": ticker},
                        lambda d: [p for p in d if isinstance(p, str)] if isinstance(d, list) else [])
    return _cached(f"fh:peers:{ticker}", 86400, fetch, [])


def finnhub_earnings_calendar(days_ahead: int = 14, ticker: str | None = None, days_back: int = 0) -> list[dict]:
    """Earnings in [today - days_back, today + days_ahead]. Without a ticker this returns the whole market in one call."""
    today = date.today()
    params = {"from": (today - timedelta(days=days_back)).isoformat(), "to": (today + timedelta(days=days_ahead)).isoformat()}
    if ticker:
        params["symbol"] = ticker
    fetch = _list_fetch("/calendar/earnings", params,
                        lambda d: (d or {}).get("earningsCalendar") or [] if isinstance(d, dict) else [])
    return _cached(f"fh:earnings:{ticker or '*'}:{days_ahead}:{days_back}", 21600, fetch, [])


# ── Twelve Data (history fallback) ───────────────────────────────────────

_TD_INTERVALS = {
    "1m": ("1min", 390), "5m": ("5min", 78), "15m": ("15min", 26), "30m": ("30min", 13),
    "1h": ("1h", 7), "1d": ("1day", 1), "1wk": ("1week", 0.2), "1mo": ("1month", 0.05),
}
_TD_PERIOD_DAYS = {
    "1d": 1, "5d": 5, "1mo": 22, "3mo": 66, "6mo": 130, "1y": 252, "2y": 504, "5y": 1260, "max": 5000,
}


def twelvedata_history(ticker: str, period: str, interval: str) -> pd.DataFrame | None:
    if not TWELVEDATA_API_KEY or interval not in _TD_INTERVALS or not _is_plain_equity(ticker):
        return None
    td_interval, bars_per_day = _TD_INTERVALS[interval]
    outputsize = min(5000, max(2, math.ceil(_TD_PERIOD_DAYS.get(period, 130) * bars_per_day)))
    try:
        resp = _session.get(
            "https://api.twelvedata.com/time_series",
            params={"symbol": ticker, "interval": td_interval, "outputsize": outputsize, "order": "ASC"},
            headers={"Authorization": f"apikey {TWELVEDATA_API_KEY}"},
            timeout=10,
        )
        data = resp.json()
        values = data.get("values") if data.get("status") == "ok" else None
        if not values:
            return None
        df = pd.DataFrame(values)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
        out = pd.DataFrame({
            "Open": df["open"].astype(float),
            "High": df["high"].astype(float),
            "Low": df["low"].astype(float),
            "Close": df["close"].astype(float),
            "Volume": df["volume"].astype(float) if "volume" in df else 0.0,
        })
        return out.sort_index()
    except Exception as e:
        log.warning("Twelve Data history failed for %s: %s", ticker, e)
        return None


# ── Alpaca (free Basic plan: full-market history up to 15 minutes ago, real-time IEX quotes) ──

_ALPACA_TIMEFRAMES = {
    "1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour", "60m": "1Hour",
    "1d": "1Day", "1wk": "1Week", "1mo": "1Month",
}
# Calendar days to look back for each yfinance-style period
_ALPACA_PERIOD_DAYS = {"1d": 4, "5d": 9, "1mo": 32, "3mo": 95, "6mo": 185, "1y": 370, "2y": 735, "5y": 1830, "10y": 3660, "max": 3660}
_ALPACA_URL = "https://data.alpaca.markets/v2"
_alpaca_bucket = _TokenBucket(180)  # Basic plan allows 200 requests a minute


def alpaca_enabled() -> bool:
    return bool(ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY)


def _alpaca(path: str, params: dict) -> tuple[int, dict | None]:
    if not alpaca_enabled() or not _alpaca_bucket.take():
        return 0, None
    try:
        resp = _session.get(f"{_ALPACA_URL}{path}", params=params, timeout=10,
                            headers={"APCA-API-KEY-ID": ALPACA_API_KEY_ID, "APCA-API-SECRET-KEY": ALPACA_API_SECRET_KEY})
        if resp.status_code != 200:
            log.warning("Alpaca %s -> %s", path, resp.status_code)
            return resp.status_code, None
        return 200, resp.json()
    except Exception as e:
        log.warning("Alpaca %s failed: %s", path, e)
        return 0, None


def alpaca_history(ticker: str, period: str, interval: str, prepost: bool = False) -> pd.DataFrame | None:
    """Split- and dividend-adjusted bars in New York time, shaped like yfinance history. Uses the full-market (SIP)
    feed, which the free plan serves up to 15 minutes ago, and falls back to IEX if SIP is refused."""
    timeframe = _ALPACA_TIMEFRAMES.get(interval)
    if not timeframe or not alpaca_enabled() or not _is_plain_equity(ticker):
        return None
    start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=_ALPACA_PERIOD_DAYS.get(period, 185))).strftime("%Y-%m-%dT%H:%M:%SZ")
    for feed in ("sip", "iex"):
        rows, token = [], None
        for _ in range(20):
            params = {"timeframe": timeframe, "start": start, "adjustment": "all", "feed": feed, "limit": 10000}
            if token:
                params["page_token"] = token
            status, data = _alpaca(f"/stocks/{ticker}/bars", params)
            if data is None:
                break
            rows += data.get("bars") or []
            token = data.get("next_page_token")
            if not token:
                break
        if status in (401, 429) or (status == 200 and not rows):
            return None
        if status == 200 and rows:
            break
    else:
        return None
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["t"], utc=True).dt.tz_convert("America/New_York")
    df.index.name = "Date"
    out = pd.DataFrame({"Open": df["o"].astype(float), "High": df["h"].astype(float), "Low": df["l"].astype(float),
                        "Close": df["c"].astype(float), "Volume": df["v"].astype(float)}).sort_index()
    if timeframe.endswith(("Min", "Hour")) and not prepost:
        minutes = out.index.hour * 60 + out.index.minute
        out = out[(minutes >= 570) & (minutes < 960)]
    return out if not out.empty else None


def alpaca_quote(ticker: str) -> dict | None:
    """Latest price from the free real-time IEX feed with the day's change versus the previous full-market close."""
    if not alpaca_enabled() or not _is_plain_equity(ticker):
        return None

    def _fetch():
        _, data = _alpaca(f"/stocks/{ticker}/snapshot", {"feed": "iex"})
        trade = (data or {}).get("latestTrade") or {}
        price = trade.get("p")
        if not price:
            raise LookupError(ticker)
        day, prev = data.get("dailyBar") or {}, data.get("prevDailyBar") or {}
        pc = prev.get("c")
        return {"c": price, "pc": pc, "d": price - pc if pc else None, "dp": (price / pc - 1) * 100 if pc else None,
                "o": day.get("o"), "h": day.get("h"), "l": day.get("l"), "t": trade.get("t"), "source": "Alpaca (IEX)"}

    return _cached(f"alpaca:quote:{ticker}", 30, _fetch, None)


# ── CBOE delayed options (free, no key; fallback when Yahoo blocks the host) ──

_OCC = re.compile(r"^([A-Z.]+)(\d{6})([CP])(\d{8})$")


def cboe_chains(ticker: str, cache: bool = True) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """All expirations for a ticker as {expiry: (calls, puts)} with yfinance-style columns."""
    if not _is_plain_equity(ticker):
        return {}

    def _fetch():
        sym = ticker.replace("-", ".")
        resp = _session.get(f"https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json",
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code != 200:
            raise LookupError(ticker)
        rows = {}
        for o in (resp.json().get("data") or {}).get("options") or []:
            m = _OCC.match(o.get("option") or "")
            # Skip adjusted contracts (root differs from the ticker, e.g. after a split); BRK.B -> BRKB
            if not m or m.group(1) != sym.replace(".", ""):
                continue
            ymd, cp = m.group(2), m.group(3)
            expiry = f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:]}"
            rows.setdefault((expiry, cp), []).append({
                "contractSymbol": o["option"],
                "strike": int(m.group(4)) / 1000,
                "lastPrice": o.get("last_trade_price") or 0.0,
                "bid": o.get("bid") or 0.0,
                "ask": o.get("ask") or 0.0,
                "volume": o.get("volume") or 0,
                "openInterest": o.get("open_interest") or 0,
                "impliedVolatility": o.get("iv") or 0.0,
            })
        if not rows:
            raise LookupError(ticker)
        chains = {}
        for expiry in sorted({k[0] for k in rows}):
            calls, puts = (pd.DataFrame(rows.get((expiry, cp), [])) for cp in "CP")
            chains[expiry] = tuple(df.sort_values("strike").reset_index(drop=True) if not df.empty else df
                                   for df in (calls, puts))
        return chains

    if not cache:
        try:
            return _fetch()
        except Exception:
            return {}
    return _cached(f"cboe:{ticker}", 300, _fetch, {})


def finnhub_insider_transactions(ticker: str) -> list[dict]:
    if not _is_plain_equity(ticker):
        return []
    fetch = _list_fetch("/stock/insider-transactions", {"symbol": ticker},
                        lambda d: (d or {}).get("data") or [] if isinstance(d, dict) else [])
    return _cached(f"fh:insiders:{ticker}", 21600, fetch, [])


def finnhub_market_insiders(day: date) -> list[dict]:
    """All insider transactions filed on one day (Finnhub returns the whole market without a symbol)."""
    params = {"from": day.isoformat(), "to": day.isoformat()}
    fetch = _list_fetch("/stock/insider-transactions", params,
                        lambda d: (d or {}).get("data") or [] if isinstance(d, dict) else [])
    return _cached(f"fh:insiders:*:{day.isoformat()}", 6 * 3600 if day >= date.today() - timedelta(days=1) else 7 * 86400,
                   fetch, [])


# ── FINRA short interest (free, no key; published twice a month) ─────────

def finra_short_interest(ticker: str) -> list[dict]:
    if not _is_plain_equity(ticker):
        return []

    def _fetch():
        resp = _session.post(
            "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest",
            json={"limit": 12,
                  "compareFilters": [{"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": ticker}],
                  "dateRangeFilters": [{"fieldName": "settlementDate",
                                        "startDate": (date.today() - timedelta(days=200)).isoformat(),
                                        "endDate": date.today().isoformat()}]},
            headers={"Accept": "application/json"}, timeout=15)
        if resp.status_code != 200:
            raise LookupError(ticker)
        rows = resp.json() if resp.text.strip() else []
        return sorted(({"date": r["settlementDate"], "short_shares": r.get("currentShortPositionQuantity"),
                        "days_to_cover": r.get("daysToCoverQuantity"), "change_pct": r.get("changePercent"),
                        "avg_volume": r.get("averageDailyVolumeQuantity")}
                       for r in rows if r.get("settlementDate")), key=lambda r: r["date"])

    return _cached(f"finra:si:{ticker}", 12 * 3600, _fetch, [])


# ── SEC EDGAR (free, no key) ─────────────────────────────────────────────

def _sec_get(url: str):
    resp = _session.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _cik_map() -> dict[str, int]:
    def _fetch():
        data = _sec_get("https://www.sec.gov/files/company_tickers.json")
        return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}
    return get_or_fetch("sec:cikmap", _fetch, ttl=86400)


def sec_recent_filings(ticker: str, forms: tuple = ("10-K", "10-Q", "8-K", "4"), limit: int = 10) -> list[dict]:
    def _fetch():
        cik = _cik_map().get(ticker.upper().replace(".", "-"))
        if not cik:
            return []
        data = _sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        recent = data.get("filings", {}).get("recent", {})
        out = []
        for form, filed, acc, doc, desc in zip(
            recent.get("form", []), recent.get("filingDate", []),
            recent.get("accessionNumber", []), recent.get("primaryDocument", []),
            recent.get("primaryDocDescription", []),
        ):
            if form not in forms:
                continue
            out.append({
                "form": form,
                "filed": filed,
                "description": desc or form,
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}",
            })
            if len(out) >= 40:
                break
        return out

    try:
        return get_or_fetch(f"sec:filings:{ticker}", _fetch, ttl=3600)[:limit]
    except Exception as e:
        log.warning("SEC filings failed for %s: %s", ticker, e)
        return []
