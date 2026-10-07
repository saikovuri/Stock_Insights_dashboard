"""Trim planner: how much of an over-weight stock to sell to reach a target weight, split into price steps,
with the gain each step would realize when the highest-cost lots are sold first."""

from collections import defaultdict
from datetime import date

import database
from portfolio_insights import _d
from stock_data import get_quote

LONG_TERM_DAYS = 365


def plan(user_id: int, ticker: str, target_pct: float, steps: int = 4, spacing_pct: float = 5.0) -> dict:
    holdings = [h for h in database.get_user_holdings(user_id) if h["shares"] > 0]
    tickers = sorted({h["ticker"] for h in holdings})
    if ticker not in tickers:
        raise LookupError(f"{ticker} is not in your recorded holdings")
    prices = {}
    for t in tickers:
        try:
            prices[t] = get_quote(t).get("price") or None
        except Exception:
            prices[t] = None
    if not prices[ticker]:
        raise LookupError(f"No current quote for {ticker}")
    if any(p is None for p in prices.values()):
        raise LookupError("Some holdings have no quote, so weights can't be computed")
    value = defaultdict(float)
    for h in holdings:
        value[h["ticker"]] += h["shares"] * prices[h["ticker"]]
    total, price = sum(value.values()), prices[ticker]
    held = sum(h["shares"] for h in holdings if h["ticker"] == ticker)
    others = total - value[ticker]
    current = value[ticker] / total * 100
    result = {"ticker": ticker, "price": price, "shares_held": round(held, 6), "current_pct": round(current, 1),
              "target_pct": target_pct, "tranches": [],
              "note": "Weights are of recorded stock value (cash excluded); other holdings are held at today's prices. "
                      "Gains use highest-cost lots first across all accounts; brokers use the account's cost-basis method. Not tax advice."}
    if current <= target_pct:
        result["shares_to_sell"] = 0
        return result
    lots = sorted(({"basis": h["buy_price"], "left": h["shares"], "acquired": _d(h.get("date_added"))}
                   for h in holdings if h["ticker"] == ticker), key=lambda lot: -lot["basis"])
    remaining, today = held, date.today()
    for i in range(steps):
        step_price = round(price * (1 + spacing_pct / 100 * i), 2)
        # Each step lowers the weight evenly toward the target, valued at that step's own price.
        weight = (current - (current - target_pct) * (i + 1) / steps) / 100
        keep = min(remaining, weight * others / ((1 - weight) * step_price))
        shares = round(remaining - keep, 2)
        gain_st = gain_lt = 0.0
        need = shares
        while need > 1e-9 and lots:
            lot = lots[0]
            n = min(lot["left"], need)
            gain = (step_price - lot["basis"]) * n
            if lot["acquired"] and (today - lot["acquired"]).days > LONG_TERM_DAYS:
                gain_lt += gain
            else:
                gain_st += gain
            lot["left"] -= n
            need -= n
            if lot["left"] <= 1e-9:
                lots.pop(0)
        remaining -= shares
        weight = remaining * step_price / (others + remaining * step_price) * 100 if others + remaining * step_price else 0
        result["tranches"].append({"step": i + 1, "price": step_price, "shares": shares, "proceeds": round(shares * step_price, 2),
                                   "covered_call_contracts": int(shares // 100),
                                   "short_term_gain": round(gain_st, 2), "long_term_gain": round(gain_lt, 2),
                                   "weight_after_pct": round(weight, 1)})
    result["shares_to_sell"] = round(sum(s["shares"] for s in result["tranches"]), 2)
    result["total_proceeds"] = round(sum(s["proceeds"] for s in result["tranches"]), 2)
    result["total_short_term_gain"] = round(sum(s["short_term_gain"] for s in result["tranches"]), 2)
    result["total_long_term_gain"] = round(sum(s["long_term_gain"] for s in result["tranches"]), 2)
    return result
