"""Wheel-strategy candidate scanner: quality S&P 500 stocks in steady uptrends, ranked by the premium a
conservative (~0.15 delta, 3-7 weeks out, liquid, pre-earnings) cash-secured put pays per unit of risk."""

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import options_analytics as oa
import yfinance as yf
from database import kv_get, kv_set
from providers import finnhub_earnings_calendar
from scanner import SCAN_KEY, _parse_ts

log = logging.getLogger(__name__)

WHEEL_KEY = "wheel:candidates"
TARGET_DELTA = 0.15  # roughly one expected move below the price
MAX_CANDIDATES = 60
MIN_ANNUALIZED = 7.0
STALE_SECONDS = 3 * 3600
_lock = threading.Lock()
_running = False


def _quality_pool(rows: list[dict]) -> list[dict]:
    """Stocks you'd be fine owning if assigned: steady uptrend, calm, near highs, not lagging the market."""
    pool = [r for r in rows
            if r.get("trend") == "uptrend" and (r.get("atr_pct") or 99) <= 3.5
            and (r.get("pct_from_high") or -99) >= -20 and (r.get("rs_rating") or 0) >= 40
            and 10 <= (r.get("price") or 0) <= 1000]
    # Prefer leaders that move least: high relative strength per unit of daily range
    pool.sort(key=lambda r: r["rs_rating"] / max(r["atr_pct"], 0.5), reverse=True)
    return pool[:MAX_CANDIDATES]


def _pick_expiry(exps: list[str], earnings: str | None) -> str | None:
    """Liquid monthly 21-50 DTE that ends before earnings when possible; nearest to ~35 DTE otherwise."""
    live = [e for e in exps if oa._live(e) and 21 <= oa._dte(e) <= 50]
    if not live:
        return None
    safe = [e for e in live if not earnings or e < earnings] or live
    monthly = [e for e in safe if oa._is_monthly(e)]
    return min(monthly or safe, key=lambda e: abs(oa._dte(e) - 35))


def _spots(symbols: list[str]) -> dict[str, float]:
    """Latest prices in one batched download (per-ticker quote APIs would hit rate limits)."""
    try:
        data = yf.download(symbols, period="5d", interval="15m", group_by="ticker", auto_adjust=True,
                           threads=True, progress=False)
        out = {}
        for s in symbols:
            closes = data[s]["Close"].dropna() if s in data.columns.get_level_values(0) else []
            if len(closes):
                out[s] = float(closes.iloc[-1])
        return out
    except Exception as e:
        log.info("Wheel spot download failed: %s", e)
        return {}


def _earnings_map() -> dict[str, str]:
    """Next earnings date per symbol from one market-wide calendar call."""
    out = {}
    for e in finnhub_earnings_calendar(60):
        s, d = e.get("symbol"), e.get("date")
        if s and d and (s not in out or d < out[s]):
            out[s] = d
    return out


def _candidate(r: dict, S: float, earnings: str | None) -> dict | None:
    t = r["symbol"]
    exps = oa._expirations(t)
    if not exps:
        return None
    exp = _pick_expiry(exps, earnings)
    if not exp:
        return None
    T, d = oa._years(exp), max(oa._dte(exp), 1)
    _, puts = oa._chain(t, exp)
    p = oa._pick(oa._otm_rows(puts, "put", S, T), TARGET_DELTA)
    if not p or p["delta"] > 0.22:  # no liquid strike far enough out of the money
        return None
    liq = oa._liquidity(p["oi"], oa._spread_pct(p["bid"], p["ask"]))
    if liq == "thin":
        return None
    K, mid = p["strike"], p["mid"]
    ann = mid / K * 365 / d * 100
    if ann < MIN_ANNUALIZED:
        return None
    atm = oa._atm_iv(t, exp, S)
    em = S * atm * math.sqrt(T) if atm else None
    rv = r["atr_pct"] / 1.25 * math.sqrt(252) / 100  # ATR% ≈ 1.25× daily σ
    earnings_before = bool(earnings and earnings <= exp)
    outside_em = em is not None and K < S - em
    iv_rich = bool(atm and atm > rv * 1.1)

    score = (min(ann, 40) / 40 * 45 + r["rs_rating"] / 99 * 20 + (15 if outside_em else 0)
             + {"good": 10, "ok": 5}.get(liq, 0) + (5 if iv_rich else 0) + (1 - p["p_itm"]) * 5
             - (30 if earnings_before else 0))
    flags = []
    if earnings_before:
        flags.append(f"Earnings {earnings} before expiry")
    if not outside_em:
        flags.append("Strike inside the expected move")
    return {
        "ticker": t, "name": r.get("name"), "sector": r.get("sector"), "price": round(S, 2),
        "rs_rating": r["rs_rating"], "atr_pct": r["atr_pct"], "pct_from_high": r["pct_from_high"],
        "r12m": r.get("r12m"),
        "expiry": exp, "dte": oa._dte(exp), "monthly": oa._is_monthly(exp),
        "strike": K, "delta": round(p["delta"], 2), "bid": round(p["bid"], 2), "ask": round(p["ask"], 2),
        "premium": round(mid * 100, 2), "annualized_pct": round(ann, 1), "return_pct": round(mid / K * 100, 2),
        "cushion_pct": round((S - K) / S * 100, 1), "breakeven": round(K - mid, 2),
        "capital": round(K * 100), "prob_assigned_pct": round(p["p_itm"] * 100),
        "open_interest": p["oi"], "liquidity": liq,
        "iv_pct": None if not atm else round(atm * 100, 1), "rv_pct": round(rv * 100, 1), "iv_rich": iv_rich,
        "expected_move_pct": None if not em else round(em / S * 100, 1), "outside_expected_move": outside_em,
        "earnings_date": earnings, "earnings_before_expiry": earnings_before,
        "flags": flags, "score": round(score, 1),
    }


def run_wheel_scan() -> dict:
    global _running
    with _lock:
        if _running:
            return {"status": "running"}
        _running = True
    started = time.time()
    try:
        scan = kv_get(SCAN_KEY)
        if not scan:
            raise RuntimeError("Setup scan not available yet")
        pool = _quality_pool(scan["data"]["rows"])
        spots = _spots([r["symbol"] for r in pool])
        earnings = _earnings_map()

        def safe(r):
            try:
                # The market-wide calendar is capped (~1,500 rows), so fall back to a per-ticker lookup
                er = earnings.get(r["symbol"]) or oa._earnings_date(r["symbol"])
                return _candidate(r, spots.get(r["symbol"]) or r["price"], er)
            except Exception as e:
                log.info("Wheel candidate %s failed: %s", r["symbol"], e)
                return None

        with ThreadPoolExecutor(max_workers=4) as ex:
            rows = [c for c in ex.map(safe, pool) if c]
        rows.sort(key=lambda c: c["score"], reverse=True)
        result = {"rows": rows, "screened": len(scan["data"]["rows"]), "quality_pool": len(pool),
                  "target_delta": TARGET_DELTA, "updated_at": datetime.now(timezone.utc).isoformat(),
                  "seconds": round(time.time() - started)}
        kv_set(WHEEL_KEY, result)
        log.info("Wheel scan: %d candidates from %d in %ds", len(rows), len(pool), result["seconds"])
        return result
    finally:
        with _lock:
            _running = False


def _safe_run():
    try:
        run_wheel_scan()
    except Exception as e:
        log.warning("Wheel scan failed: %s", e)


def get_wheel(start_if_stale: bool = True) -> dict:
    cached = kv_get(WHEEL_KEY)
    stale = not cached or (datetime.now(timezone.utc) - _parse_ts(cached["data"]["updated_at"])).total_seconds() > STALE_SECONDS
    if stale and start_if_stale and not _running:
        threading.Thread(target=_safe_run, daemon=True).start()
    if not cached:
        return {"status": "building", "rows": []}
    return {**cached["data"], "status": "running" if _running else "ready"}
