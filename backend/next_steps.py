"""Rule-based next steps: the portfolio's open issues and opportunities gathered into one ranked list."""

import logging
from collections import defaultdict
from datetime import date, datetime, timezone

import accounts
import database
from portfolio_insights import _holding_terms
from stock_data import get_quote

log = logging.getLogger(__name__)
LEVELS = {"act": 0, "warn": 1, "idea": 2, "info": 3}
CONCENTRATION_PCT = 25
IDLE_CASH_MIN = 5000
LOSS_REVIEW_PCT = 10


def _usd(v: float) -> str:
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _prices(tickers) -> dict:
    out = {}
    for t in tickers:
        try:
            out[t] = get_quote(t).get("price") or None
        except Exception as e:
            log.info("No quote for %s: %s", t, e)
            out[t] = None
    return out


def _option_items(actions: dict) -> list[dict]:
    items = []
    for level, verb in (("act", "need action"), ("warn", "need a look")):
        hits = [(p, a) for p in actions.get("positions", []) for a in p["actions"][:1] if a["level"] == level]
        if hits:
            points = [f"{p['ticker']} ${p['strike']:g} {p['type']}: {a['text']}" for p, a in hits[:3]]
            more = f"{len(hits) - 3} more in Option alerts below." if len(hits) > 3 else "Details in Option alerts below."
            # Positions whose alerts offer a roll/repair get a direct button
            repairs = [{"id": p["id"], "label": f"{p['ticker']} ${p['strike']:g} {p['type']} {p['expiry']}"}
                       for p, _ in hits if p.get("position") == "short" and any(x.get("repair") for x in p["actions"])][:5]
            items.append({"level": level, "code": f"options_{level}", "title": f"{len(hits)} option position(s) {verb}",
                          "points": points, "detail": more, "link": {"kind": "alerts"}, "repairs": repairs})
    return items


def _earnings_items(holdings: list[dict]) -> list[dict]:
    """Stocks you hold that report within the next 7 days (options already have their own earnings alerts)."""
    import options_analytics
    shares = defaultdict(float)
    for h in holdings:
        shares[h["ticker"]] += h["shares"]
    today, hits = date.today(), []
    for ticker in sorted(shares):
        try:
            info = options_analytics.earnings_info(ticker)
        except Exception as e:
            log.info("Earnings lookup failed for %s: %s", ticker, e)
            continue
        nxt = info.get("next")
        if not nxt:
            continue
        days = (date.fromisoformat(nxt) - today).days
        if 0 <= days <= 7:
            when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
            timing = f", {info['next_timing']}" if info.get("next_timing") else ""
            confirmed = "" if info.get("next_confirmed") else " (est.)"
            hits.append((days, f"{ticker}: {nxt}{confirmed} ({when}{timing}), {shares[ticker]:g} shares"))
    if not hits:
        return []
    hits.sort()
    return [{"level": "warn", "code": "stock_earnings", "title": f"{len(hits)} stock(s) you hold report earnings within 7 days",
             "points": [text for _, text in hits[:5]],
             "detail": "Prices can gap on the report. Decide beforehand whether to hold, trim, or hedge (a protective put or collar); "
                       "the Earnings exposure section below shows typical past moves."}]


def _cash_items(user_id: int, account: str | None = None) -> list[dict]:
    items = []
    for a in accounts.list_accounts(user_id)["accounts"]:
        if account is not None and a["name"] != account:
            continue
        name, free, reserved = a["name"], a["free_cash"], a["put_collateral"]
        if free is None:
            if reserved > 0:
                items.append({"level": "warn", "code": "cash_unknown", "account": name,
                              "title": f"{name}: short puts reserve {_usd(reserved)} but no cash balance is recorded",
                              "detail": "Enter the account's cash under Portfolio → Holdings (account bar) so collateral and free cash can be checked."})
        elif free < 0:
            items.append({"level": "warn", "code": "over_committed", "account": name,
                          "title": f"{name}: short puts need {_usd(-free)} more cash than recorded",
                          "detail": f"Put collateral {_usd(reserved)} vs cash {_usd(a['cash'])}. Fine if the account uses margin "
                                    "and you accept that; otherwise add cash, or close or roll a put before assignment."})
        elif free >= IDLE_CASH_MIN:
            items.append({"level": "idea", "code": "idle_cash", "account": name,
                          "title": f"{name}: {_usd(free)} cash not committed to any short put",
                          "detail": "Cash-secured puts on stocks you would be happy to own can earn premium on part of it; "
                                    "Ideas → Wheel lists candidates. In a money-market fund it already earns yield meanwhile.",
                          "link": {"kind": "wheel"}})
    return items


def _covered_call_items(holdings: list[dict], options: list[dict]) -> list[dict]:
    shares, cost = defaultdict(float), defaultdict(float)
    for h in holdings:
        key = (h.get("account") or database.DEFAULT_ACCOUNT, h["ticker"])
        shares[key] += h["shares"]
        cost[key] += h["shares"] * h["buy_price"]
    calls = defaultdict(int)
    for o in options:
        if o["position"] == "short" and o["option_type"] == "call":
            calls[(o.get("account") or database.DEFAULT_ACCOUNT, o["ticker"])] += o["contracts"]
    items = []
    for key in sorted(shares, key=lambda k: -cost[k]):
        name, ticker = key
        blocks = int(shares[key] // 100) - calls[key]
        if blocks < 1:
            continue
        avg = cost[key] / shares[key]
        items.append({"level": "idea", "code": "covered_call", "account": name, "ticker": ticker,
                      "title": f"{ticker}: {blocks} uncovered 100-share block(s) in {name}",
                      "detail": f"Average cost ${avg:,.2f}. A covered call collects premium while you hold, "
                                "but caps the gain: the shares can be called away above the strike.",
                      "link": {"kind": "covered_calls", "ticker": ticker, "cost_basis": round(avg, 2), "shares": blocks * 100}})
    return items[:5]


def _concentration_items(holdings: list[dict], prices: dict, limit: float | None = None) -> list[dict]:
    threshold = limit if limit is not None else CONCENTRATION_PCT
    value = defaultdict(float)
    for h in holdings:
        if prices.get(h["ticker"]):
            value[h["ticker"]] += h["shares"] * prices[h["ticker"]]
    total = sum(value.values())
    if not total or len(value) < 2:
        return []
    suffix = f" (your limit {limit:g}%)" if limit is not None else ""
    return [{"level": "warn", "code": "rule_max_position" if limit is not None else "concentration", "ticker": t,
             "title": f"{'Rule: ' if limit is not None else ''}{t} is {v / total * 100:.0f}% of your stock value{suffix}",
             "detail": f"{_usd(v)} of {_usd(total)}. One stock's move swings the whole portfolio. To reduce it: trim or stop "
                       "adding, sell covered calls on part of it, or hedge with a protective put or collar. The trim planner below "
                       "sizes the sales.", "link": {"kind": "trim", "ticker": t}}
            for t, v in sorted(value.items(), key=lambda kv: -kv[1]) if v / total * 100 > threshold]


def _tax_items(holdings: list[dict], prices: dict) -> list[dict]:
    losers = []
    for h in holdings:
        px = prices.get(h["ticker"])
        if px and h["buy_price"] > 0 and (px / h["buy_price"] - 1) * 100 <= -LOSS_REVIEW_PCT:
            losers.append((h["ticker"], (px - h["buy_price"]) * h["shares"], (px / h["buy_price"] - 1) * 100))
    items = []
    if losers:
        losers.sort(key=lambda x: x[1])
        shown = ", ".join(f"{t} {_usd(p)} ({pct:.0f}%)" for t, p, pct in losers[:3])
        items.append({"level": "info", "code": "tax_loss", "title": f"Tax-loss review: {len(losers)} lot(s) down {LOSS_REVIEW_PCT}% or more",
                      "detail": f"{shown}. Selling realizes the loss; buying the same stock back within 30 days makes it a wash sale.",
                      "link": {"kind": "tax"}})
    soon = [r for r in _holding_terms(holdings, date.today()) if (r["note"] or "").startswith("Turns long-term")]
    if soon:
        shown = ", ".join(f"{r['ticker']} on {r['long_term_on']}" for r in soon[:3])
        items.append({"level": "info", "code": "long_term_soon", "title": f"{len(soon)} profitable lot(s) turn long-term within 60 days",
                      "detail": f"{shown}. Selling before then taxes the gain at short-term rates.", "link": {"kind": "tax"}})
    return items


def build(user_id: int, option_actions: dict, account: str | None = None) -> dict:
    """`account` limits every check to one brokerage account label; None covers all accounts."""
    import trading_rules
    holdings = [h for h in database.get_user_holdings(user_id) if h["shares"] > 0 and database.in_account(h, account)]
    options = [o for o in database.get_user_options(user_id) if database.in_account(o, account)]
    if account is not None:
        option_actions = {**option_actions, "positions": [p for p in option_actions.get("positions", [])
                                                          if (p.get("account") or database.DEFAULT_ACCOUNT) == account]}
    account_rows = [a for a in accounts.list_accounts(user_id)["accounts"] if account is None or a["name"] == account]
    prices = _prices(sorted({h["ticker"] for h in holdings}))
    rules = trading_rules.get_rules(user_id)
    items = (_option_items(option_actions) + _cash_items(user_id, account)
             + _concentration_items(holdings, prices, rules.get("max_position_pct"))
             + trading_rules.violations(rules, holdings, options, prices, option_actions, account_rows)
             + _earnings_items(holdings) + _covered_call_items(holdings, options) + _tax_items(holdings, prices))
    items.sort(key=lambda i: LEVELS[i["level"]])
    note = "Rule-based checks on the positions and cash recorded here. Not investment advice."
    if account is not None:
        note = f"Showing account {account} only. " + note
    return {"items": items, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "account": account, "note": note}
