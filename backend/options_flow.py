"""Options flow & positioning from free CBOE delayed quotes: put/call ratios, unusual activity,
max pain and dealer gamma levels. Falls back to Yahoo chains for the nearest expirations."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import numpy as np
import pandas as pd

from cache import get_or_fetch
from database import get_all_user_tickers
from options_analytics import RISK_FREE, _chain, _dte, _expirations, _mid
from providers import cboe_chains
from stock_data import get_quote

log = logging.getLogger(__name__)

MAX_DTE = 60
SCAN_TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO",
                "NFLX", "PLTR", "COIN", "MSTR", "SMCI", "INTC", "MU", "BA", "JPM", "BAC", "XOM", "CVX", "UNH",
                "LLY", "PFE", "DIS", "NKE", "WMT", "COST", "HD", "CRM", "ORCL", "UBER", "SHOP", "SOFI", "HOOD",
                "ARM", "TSM"]


def _chains(ticker: str, cache: bool = True) -> dict:
    chains = cboe_chains(ticker, cache=cache)
    if not chains:
        chains = {}
        for e in _expirations(ticker):
            if 0 <= _dte(e) <= MAX_DTE:
                try:
                    chains[e] = _chain(ticker, e)
                except Exception:
                    continue
    return {e: c for e, c in chains.items() if 0 <= _dte(e) <= MAX_DTE}


def _frame(chains: dict) -> pd.DataFrame:
    parts = []
    for expiry, (calls, puts) in chains.items():
        for df, kind in ((calls, "call"), (puts, "put")):
            if df is None or df.empty:
                continue
            d = df[["strike", "bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility"]].copy()
            d["kind"], d["expiry"], d["dte"] = kind, expiry, _dte(expiry)
            parts.append(d)
    if not parts:
        return pd.DataFrame()
    f = pd.concat(parts, ignore_index=True)
    for c in ("strike", "bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility"):
        f[c] = pd.to_numeric(f[c], errors="coerce").fillna(0.0)
    return f


def _unusual(f: pd.DataFrame, S: float, ticker: str, limit: int = 12) -> list[dict]:
    if f.empty:
        return []
    mid = np.where((f["bid"] > 0) & (f["ask"] > 0), (f["bid"] + f["ask"]) / 2, f["lastPrice"])
    f = f.assign(mid=mid, premium=f["volume"] * mid * 100)
    oi = f["openInterest"]
    otm = (f["strike"] / S - 1) * np.where(f["kind"] == "call", 1, -1)
    # Skip 0-1 DTE churn and deep ITM contracts (usually spreads or stock replacement, not directional bets)
    hits = f[(f["volume"] >= 100) & (f["premium"] >= 25_000) & (f["dte"] >= 2) & (otm >= -0.05)
             & (((oi > 0) & (f["volume"] > oi)) | ((oi == 0) & (f["volume"] >= 500)))]
    out = []
    for _, r in hits.sort_values("premium", ascending=False).head(limit).iterrows():
        last, bid, ask = r["lastPrice"], r["bid"], r["ask"]
        side = ("bought" if ask > 0 and last >= ask - 0.01 else
                "sold" if bid > 0 and last <= bid + 0.01 else "mid")
        out.append({
            "ticker": ticker, "kind": r["kind"], "strike": float(r["strike"]), "expiry": r["expiry"],
            "dte": int(r["dte"]), "volume": int(r["volume"]), "open_interest": int(r["openInterest"]),
            "vol_oi": round(r["volume"] / r["openInterest"], 1) if r["openInterest"] else None,
            "premium": round(float(r["premium"])), "iv_pct": round(float(r["impliedVolatility"]) * 100, 1),
            "otm_pct": round((r["strike"] / S - 1) * 100 * (1 if r["kind"] == "call" else -1), 1),
            "side": side,
        })
    return out


def _gamma(S: np.ndarray, K: np.ndarray, T: np.ndarray, iv: np.ndarray) -> np.ndarray:
    sqrtT = np.sqrt(T)
    d1 = (np.log(S / K) + (RISK_FREE + iv * iv / 2) * T) / (iv * sqrtT)
    return np.exp(-d1 * d1 / 2) / np.sqrt(2 * np.pi) / (S * iv * sqrtT)


def _gex(f: pd.DataFrame, spot: float) -> float:
    """Dealer gamma in $ per 1% move, assuming customers are net long puts and short calls."""
    g = _gamma(np.full(len(f), spot), f["strike"].values, f["T"].values, f["iv"].values)
    sign = np.where(f["kind"].values == "call", 1.0, -1.0)
    return float(np.sum(sign * g * f["openInterest"].values * 100 * spot * spot * 0.01))


def _max_pain(calls: pd.DataFrame, puts: pd.DataFrame) -> float | None:
    strikes = np.union1d(calls["strike"].values, puts["strike"].values)
    if len(strikes) == 0:
        return None
    cK, cOI = calls["strike"].values, calls["openInterest"].values
    pK, pOI = puts["strike"].values, puts["openInterest"].values
    pain = [np.sum(cOI * np.maximum(P - cK, 0)) + np.sum(pOI * np.maximum(pK - P, 0)) for P in strikes]
    return float(strikes[int(np.argmin(pain))])


def _is_monthly(expiry: str) -> bool:
    d = datetime.strptime(expiry, "%Y-%m-%d").date()
    return d.weekday() == 4 and 15 <= d.day <= 21


def _positioning(f: pd.DataFrame, chains: dict, S: float) -> dict:
    near = f[(f["strike"] > S * 0.8) & (f["strike"] < S * 1.2)]
    by_strike = near.groupby(["kind", "strike"])["openInterest"].sum()
    call_wall = float(by_strike["call"].idxmax()) if "call" in by_strike and by_strike["call"].max() > 0 else None
    put_wall = float(by_strike["put"].idxmax()) if "put" in by_strike and by_strike["put"].max() > 0 else None

    g = f[(f["openInterest"] > 0) & (f["impliedVolatility"] > 0.03) & (f["impliedVolatility"] < 3)]
    g = g.assign(T=np.maximum(g["dte"].values, 1) / 365, iv=g["impliedVolatility"].values)
    net_gex = _gex(g, S) if not g.empty else None
    flip = None
    if not g.empty:
        grid = np.linspace(S * 0.85, S * 1.15, 61)
        vals = np.array([_gex(g, x) for x in grid])
        cross = np.where(np.sign(vals[:-1]) != np.sign(vals[1:]))[0]
        if len(cross):
            i = cross[np.argmin(np.abs(grid[cross] - S))]
            x0, x1, y0, y1 = grid[i], grid[i + 1], vals[i], vals[i + 1]
            flip = round(float(x0 - y0 * (x1 - x0) / (y1 - y0)), 2)

    pains = []
    exps = sorted(chains)
    targets = exps[:1] + [e for e in exps if _is_monthly(e)][:1]
    for e in dict.fromkeys(targets):
        calls, puts = chains[e]
        mp = _max_pain(calls, puts)
        if mp is not None:
            pains.append({"expiry": e, "dte": _dte(e), "max_pain": mp, "vs_spot_pct": round((mp / S - 1) * 100, 1)})

    regime = None
    if net_gex is not None:
        regime = ("positive" if net_gex > 0 else "negative")
    return {"call_wall": call_wall, "put_wall": put_wall, "net_gex": None if net_gex is None else round(net_gex),
            "gamma_flip": flip, "gamma_regime": regime, "max_pain": pains}


def _summary(pc_vol, pos, S) -> str:
    parts = []
    if pc_vol is not None:
        parts.append("Put volume exceeds call volume; buyer intent cannot be inferred from volume alone." if pc_vol > 1.0 else
                 "Call volume dominates; this includes purchases, sales and spread legs." if pc_vol < 0.6 else
                     "Put and call volume are fairly balanced.")
    if pos.get("gamma_regime") == "positive":
        parts.append("The assumed-positioning gamma proxy is positive; actual dealer inventory is unknown.")
    elif pos.get("gamma_regime") == "negative":
        parts.append("The assumed-positioning gamma proxy is negative; actual dealer inventory is unknown.")
    if pos.get("call_wall") and pos.get("put_wall"):
        parts.append(f"Biggest open-interest strikes: ${pos['put_wall']:g} puts and ${pos['call_wall']:g} calls; not established support/resistance.")
    return " ".join(parts)


def options_flow(ticker: str) -> dict:
    def _fetch():
        S = float(get_quote(ticker).get("price") or 0)
        if not S:
            raise ValueError("Spot price unavailable")
        chains = _chains(ticker)
        if not chains:
            raise LookupError("No listed options")
        f = _frame(chains)
        call_vol, put_vol = f.loc[f["kind"] == "call", "volume"].sum(), f.loc[f["kind"] == "put", "volume"].sum()
        call_oi, put_oi = f.loc[f["kind"] == "call", "openInterest"].sum(), f.loc[f["kind"] == "put", "openInterest"].sum()
        pc_vol = round(put_vol / call_vol, 2) if call_vol else None
        pos = _positioning(f, chains, S)
        return {
            "ticker": ticker, "spot": S, "as_of": datetime.now().isoformat(timespec="minutes"),
            "call_volume": int(call_vol), "put_volume": int(put_vol), "pc_volume": pc_vol,
            "call_oi": int(call_oi), "put_oi": int(put_oi), "pc_oi": round(put_oi / call_oi, 2) if call_oi else None,
            "unusual": _unusual(f, S, ticker),
            **pos,
            "summary": _summary(pc_vol, pos, S),
            "note": f"Expirations within {MAX_DTE} days. Delayed quotes; gamma assumes customers are long puts / short calls.",
        }
    return get_or_fetch(f"flow:{ticker}", _fetch, ttl=600)


def _scan_one(t: str) -> tuple[list[dict], dict | None]:
    try:
        S = float(get_quote(t).get("price") or 0)
        chains = _chains(t, cache=False)
        if not S or not chains:
            return [], None
        f = _frame(chains)
        cv, pv = f.loc[f["kind"] == "call", "volume"].sum(), f.loc[f["kind"] == "put", "volume"].sum()
        return _unusual(f, S, t, limit=5), {"ticker": t, "pc_volume": round(pv / cv, 2) if cv else None,
                                            "volume": int(cv + pv)}
    except Exception as e:
        log.info("Flow scan failed for %s: %s", t, e)
        return [], None


def unusual_scan() -> dict:
    """Largest unusual contracts across liquid names plus everything users hold or watch."""
    def _fetch():
        user = sorted({t for ts in get_all_user_tickers().values() for t in ts})
        tickers = list(dict.fromkeys(SCAN_TICKERS + user))[:80]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_scan_one, tickers))
        trades = sorted((x for r, _ in results for x in r), key=lambda x: x["premium"], reverse=True)[:40]
        ratios = sorted((s for _, s in results if s and s["pc_volume"] is not None), key=lambda s: s["pc_volume"])
        call_prem = sum(x["premium"] for x in trades if x["kind"] == "call" and x["side"] == "bought")
        put_prem = sum(x["premium"] for x in trades if x["kind"] == "put" and x["side"] == "bought")
        return {"trades": trades, "most_bullish": ratios[:5], "most_bearish": ratios[::-1][:5],
                "bought_call_premium": call_prem, "bought_put_premium": put_prem,
                "scanned": len(tickers), "as_of": datetime.now().isoformat(timespec="minutes"),
                "date": date.today().isoformat()}
    return get_or_fetch("flow:scan", _fetch, ttl=900)
