"""How well a candidate stock fits the user's current portfolio: correlation with the holdings, sector already heavy,
position already large, and whether the cash it needs fits recorded free cash. A 0-100 score with plain reasons."""

import hashlib
import json
import logging
from collections import defaultdict

import pandas as pd

import accounts
import database
from cache import get_or_fetch
from stock_data import get_key_metrics, get_quote, get_stock_data

log = logging.getLogger(__name__)
MAX_PORTFOLIO_TICKERS = 15
MIN_OBSERVATIONS = 40


def _returns(ticker: str) -> pd.Series | None:
    try:
        close = get_stock_data(ticker, period="6mo", interval="1d")["Close"]
        close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
        return close[~close.index.duplicated(keep="last")].pct_change().dropna()
    except Exception as error:
        log.info("No history for %s: %s", ticker, error)
        return None


def _sector(ticker: str) -> str | None:
    """Finnhub's industry for every ticker when available, so holdings and candidates use one classification."""
    try:
        from providers import finnhub_enabled, finnhub_profile
        if finnhub_enabled():
            industry = (finnhub_profile(ticker) or {}).get("finnhubIndustry")
            if industry:
                return industry
    except Exception as error:
        log.info("No Finnhub profile for %s: %s", ticker, error)
    try:
        sector = get_key_metrics(ticker).get("sector")
        return sector if sector and sector != "N/A" else None
    except Exception:
        return None


def _portfolio(user_id: int) -> dict | None:
    holdings = [h for h in database.get_user_holdings(user_id) if h["shares"] > 0]
    value = defaultdict(float)
    for h in holdings:
        try:
            price = get_quote(h["ticker"]).get("price")
        except Exception:
            price = None
        if price:
            value[h["ticker"]] += h["shares"] * price
    total = sum(value.values())
    if not total:
        return None
    weights = {t: v / total for t, v in value.items()}
    sectors = defaultdict(float)
    for t, w in weights.items():
        sectors[_sector(t) or "Unknown"] += w
    top = sorted(weights, key=lambda t: -weights[t])[:MAX_PORTFOLIO_TICKERS]
    series = {t: s for t in top if (s := _returns(t)) is not None}
    port = None
    if series:
        frame = pd.DataFrame(series).dropna()
        if len(frame) >= MIN_OBSERVATIONS:
            w = pd.Series({t: weights[t] for t in frame.columns})
            port = frame.mul(w / w.sum(), axis=1).sum(axis=1)
    free = [a["free_cash"] for a in accounts.list_accounts(user_id)["accounts"] if a["free_cash"] is not None]
    return {"weights": weights, "sectors": dict(sectors), "returns": port, "free_cash": max(free) if free else None}


def _score(ticker: str, cash_needed: float | None, p: dict) -> dict:
    score, reasons = 100, []
    held = p["weights"].get(ticker, 0) * 100
    if held > 20:
        score -= 30
        reasons.append(("bad", f"Already {held:.0f}% of your stock value"))
    elif held > 10:
        score -= 15
        reasons.append(("warn", f"Already {held:.0f}% of your stock value"))
    elif held:
        reasons.append(("info", f"You already hold some ({held:.0f}%)"))
    sector = _sector(ticker)
    weight = p["sectors"].get(sector, 0) * 100 if sector else 0
    if sector and weight > 40:
        score -= 25
        reasons.append(("bad", f"{sector} is already {weight:.0f}% of your stocks"))
    elif sector and weight > 25:
        score -= 10
        reasons.append(("warn", f"{sector} is already {weight:.0f}% of your stocks"))
    elif sector:
        reasons.append(("good", f"Adds {sector} ({weight:.0f}% today)"))
    corr = None
    if p["returns"] is not None and (r := _returns(ticker)) is not None:
        joined = pd.concat([r, p["returns"]], axis=1, join="inner").dropna()
        if len(joined) >= MIN_OBSERVATIONS:
            corr = round(float(joined.iloc[:, 0].corr(joined.iloc[:, 1])), 2)
    if corr is None:
        reasons.append(("info", "Correlation unavailable"))
    elif corr > 0.7:
        score -= 35
        reasons.append(("bad", f"Moves closely with your portfolio (correlation {corr})"))
    elif corr > 0.5:
        score -= 20
        reasons.append(("warn", f"Moves fairly closely with your portfolio (correlation {corr})"))
    elif corr > 0.3:
        score -= 10
        reasons.append(("info", f"Some overlap with your portfolio (correlation {corr})"))
    else:
        reasons.append(("good", f"Diversifies: low correlation with your portfolio ({corr})"))
    if cash_needed and p["free_cash"] is not None:
        if cash_needed > p["free_cash"]:
            score -= 20
            reasons.append(("bad", f"Needs ${cash_needed:,.0f}; your largest free cash is ${p['free_cash']:,.0f}"))
        else:
            reasons.append(("good", f"Cash fits (${cash_needed:,.0f} of ${p['free_cash']:,.0f} free)"))
    score = max(0, score)
    return {"ticker": ticker, "score": score, "label": "Good fit" if score >= 75 else "OK fit" if score >= 50 else "Poor fit",
            "correlation": corr, "sector": sector, "reasons": [{"tone": t, "text": x} for t, x in reasons]}


def account_value(user_id: int) -> dict:
    """Recorded stock value (live quote, else cost) plus entered cash, across every account."""
    def _fetch():
        stocks = 0.0
        for h in database.get_user_holdings(user_id):
            if h["shares"] <= 0:
                continue
            try:
                price = get_quote(h["ticker"]).get("price")
            except Exception:
                price = None
            stocks += h["shares"] * (price or h["buy_price"])
        cash_rows = [a["cash"] for a in accounts.list_accounts(user_id)["accounts"] if a["cash"] is not None]
        cash = sum(cash_rows)
        return {"value": round(stocks + cash, 2), "stocks": round(stocks, 2), "cash": round(cash, 2),
                "cash_entered": bool(cash_rows)}
    return get_or_fetch(f"account-value:{user_id}", _fetch, ttl=300)


def fit(user_id: int, items: list[dict]) -> dict:
    key = hashlib.sha256(json.dumps([user_id, items], sort_keys=True).encode()).hexdigest()[:24]

    def _fetch():
        p = _portfolio(user_id)
        if p is None:
            return {"empty": True, "items": []}
        return {"empty": False, "items": [_score(i["ticker"], i.get("cash_needed"), p) for i in items]}
    return get_or_fetch(f"fit:{key}", _fetch, ttl=600)
