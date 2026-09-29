"""Portfolio Doctor: deterministic risk metrics + AI narrative."""

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import llm
from providers import finnhub_earnings_calendar
from stock_data import get_stock_data, get_key_metrics

log = logging.getLogger(__name__)

TAX_LOSS_THRESHOLD_PCT = -10.0


def _risk_metrics(weights: dict[str, float]) -> dict:
    closes = {}
    for t in weights:
        try:
            closes[t] = get_stock_data(t, period="1y", interval="1d")["Close"]
        except Exception:
            continue
    if not closes:
        return {}
    # Normalize to calendar dates so tickers from different exchanges/timezones align
    df = pd.DataFrame({t: s.set_axis(pd.to_datetime(s.index.date)) for t, s in closes.items()}).dropna()
    rets = df.pct_change().dropna()
    if len(rets) < 30:
        return {}
    w = np.array([weights[t] for t in rets.columns])
    w = w / w.sum()
    port = rets.values @ w
    equity = np.cumprod(1 + port)
    drawdown = equity / np.maximum.accumulate(equity) - 1

    avg_corr = None
    if len(rets.columns) >= 2:
        c = rets.corr().values
        avg_corr = float(c[np.triu_indices_from(c, k=1)].mean())

    return {
        "annual_volatility_pct": round(float(np.std(port) * np.sqrt(252) * 100), 1),
        "max_drawdown_1y_pct": round(float(drawdown.min() * 100), 1),
        "return_1y_pct": round(float((equity[-1] - 1) * 100), 1),
        "avg_pairwise_correlation": None if avg_corr is None else round(avg_corr, 2),
        "tickers_covered": list(rets.columns),
    }


def analyze(summary: dict) -> dict:
    holdings = summary.get("holdings") or []
    total = sum(h["current_value"] for h in holdings)
    if not holdings or total <= 0:
        return {"empty": True}

    by_ticker: dict[str, dict] = {}
    for h in holdings:
        agg = by_ticker.setdefault(h["ticker"], {"ticker": h["ticker"], "value": 0.0, "invested": 0.0,
                                                  "sector": h.get("sector") or "Unknown"})
        agg["value"] += h["current_value"]
        agg["invested"] += h["invested"]
    positions = sorted(by_ticker.values(), key=lambda p: p["value"], reverse=True)
    for p in positions:
        p["weight_pct"] = round(p["value"] / total * 100, 1)
        p["pnl_pct"] = round((p["value"] / p["invested"] - 1) * 100, 1) if p["invested"] else 0.0

    sectors: dict[str, float] = {}
    for p in positions:
        sectors[p["sector"]] = sectors.get(p["sector"], 0) + p["weight_pct"]
    sectors = dict(sorted(((k, round(v, 1)) for k, v in sectors.items()), key=lambda kv: kv[1], reverse=True))

    weights = {p["ticker"]: p["value"] / total for p in positions}
    effective_n = round(1 / sum(w * w for w in weights.values()), 1)

    betas = {}
    for t in weights:
        try:
            b = get_key_metrics(t).get("beta")
            if b is not None:
                betas[t] = float(b)
        except Exception:
            pass
    covered = sum(weights[t] for t in betas)
    portfolio_beta = round(sum(weights[t] * b for t, b in betas.items()) / covered, 2) if covered else None

    tax_loss = [
        {"ticker": h["ticker"], "lot_id": h.get("id"), "pnl": h["pnl"], "pnl_pct": h["pnl_pct"]}
        for h in holdings if h.get("pnl_pct", 0) <= TAX_LOSS_THRESHOLD_PCT
    ]

    earnings = [
        {"ticker": e["symbol"], "date": e.get("date"), "eps_estimate": e.get("epsEstimate")}
        for e in finnhub_earnings_calendar(14) if e.get("symbol") in weights
    ]

    risk = _risk_metrics(weights)

    flags = []
    top = positions[0]
    if top["weight_pct"] > 25:
        flags.append(f"{top['ticker']} is {top['weight_pct']}% of the portfolio (single-stock concentration)")
    top_sector, top_sector_w = next(iter(sectors.items()))
    if top_sector_w > 40:
        flags.append(f"{top_sector} is {top_sector_w}% of the portfolio (sector concentration)")
    if effective_n < 5:
        flags.append(f"Effective number of positions is {effective_n} — limited diversification")
    if portfolio_beta and portfolio_beta > 1.3:
        flags.append(f"Portfolio beta {portfolio_beta} — amplified market swings")
    if risk.get("avg_pairwise_correlation") and risk["avg_pairwise_correlation"] > 0.6:
        flags.append(f"Holdings are highly correlated (avg {risk['avg_pairwise_correlation']})")
    if risk.get("annual_volatility_pct") and risk["annual_volatility_pct"] > 30:
        flags.append(f"Annualized volatility {risk['annual_volatility_pct']}% is high")

    facts = {
        "total_value": round(total, 2),
        "total_pnl_pct": summary.get("total_pnl_pct"),
        "positions": positions,
        "sectors": sectors,
        "effective_positions": effective_n,
        "portfolio_beta": portfolio_beta,
        "risk": risk,
        "tax_loss_candidates": tax_loss,
        "upcoming_earnings": earnings,
        "flags": flags,
    }

    narrative = _ai_narrative(facts) if llm.ai_enabled() else None
    if narrative is None:
        narrative = _rule_narrative(facts)
    return {**facts, **narrative, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def _rule_narrative(f: dict) -> dict:
    score = 100
    score -= 15 if f["positions"][0]["weight_pct"] > 25 else 0
    score -= 15 if next(iter(f["sectors"].values())) > 40 else 0
    score -= 10 if f["effective_positions"] < 5 else 0
    score -= 10 if (f["portfolio_beta"] or 0) > 1.3 else 0
    score -= 10 if (f["risk"].get("annual_volatility_pct") or 0) > 30 else 0
    strengths = []
    if f["effective_positions"] >= 8:
        strengths.append(f"Well spread across ~{f['effective_positions']} effective positions")
    if len(f["sectors"]) >= 4:
        strengths.append(f"Exposure across {len(f['sectors'])} sectors")
    actions = []
    if f["tax_loss_candidates"]:
        actions.append(f"Review {len(f['tax_loss_candidates'])} lot(s) down 10%+ for possible tax-loss harvesting")
    if f["upcoming_earnings"]:
        actions.append("Earnings in the next 2 weeks: " + ", ".join(e["ticker"] for e in f["upcoming_earnings"]))
    return {
        "health_score": max(0, score),
        "headline": "Rule-based check (add an AI key for a full review).",
        "strengths": strengths,
        "risks": f["flags"],
        "actions": actions,
        "ai": False,
    }


def _ai_narrative(f: dict) -> dict | None:
    system = (
        "You are a portfolio risk analyst. Use ONLY the facts given; do not invent data. "
        "Give educational observations, not personalized financial advice. Output JSON only."
    )
    user = f"""Portfolio facts (weights in %, returns in %):
{f}

Return JSON:
{{"health_score": integer 0-100 (diversification, concentration, volatility, correlation),
 "headline": "one sentence overall assessment",
 "strengths": ["1-3 items"],
 "risks": ["2-4 specific risks referencing tickers/sectors/numbers"],
 "actions": ["2-4 concrete things to consider, e.g. trimming, diversifying, tax-loss review, earnings prep"]}}"""
    try:
        raw = llm.chat_json(system, user, temperature=0.2, max_tokens=1800)
        score = int(raw.get("health_score", 50))

        def lst(k):
            v = raw.get(k)
            return [str(x).strip() for x in v if str(x).strip()][:4] if isinstance(v, list) else []

        return {
            "health_score": max(0, min(100, score)),
            "headline": str(raw.get("headline", "")).strip(),
            "strengths": lst("strengths"),
            "risks": lst("risks") or f["flags"],
            "actions": lst("actions"),
            "ai": True,
        }
    except Exception as e:
        log.warning("Portfolio doctor AI failed: %s", e)
        return None
