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
            more = f"{len(hits) - 3} more in Position alerts below." if len(hits) > 3 else "Details in Position alerts below."
            items.append({"level": level, "code": f"options_{level}", "title": f"{len(hits)} option position(s) {verb}",
                          "points": points, "detail": more, "link": {"kind": "alerts"}})
    return items


def _cash_items(user_id: int) -> list[dict]:
    items = []
    for a in accounts.list_accounts(user_id)["accounts"]:
        name, free, reserved = a["name"], a["free_cash"], a["put_collateral"]
        if free is None:
            if reserved > 0:
                items.append({"level": "warn", "code": "cash_unknown", "account": name,
                              "title": f"{name}: short puts reserve {_usd(reserved)} but no cash balance is recorded",
                              "detail": "Enter the account's cash in the account bar so collateral and free cash can be checked."})
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


def _concentration_items(holdings: list[dict], prices: dict) -> list[dict]:
    value = defaultdict(float)
    for h in holdings:
        if prices.get(h["ticker"]):
            value[h["ticker"]] += h["shares"] * prices[h["ticker"]]
    total = sum(value.values())
    if not total or len(value) < 2:
        return []
    return [{"level": "warn", "code": "concentration", "ticker": t,
             "title": f"{t} is {v / total * 100:.0f}% of your stock value",
             "detail": f"{_usd(v)} of {_usd(total)}. One stock's move swings the whole portfolio. To reduce it: trim or stop "
                       "adding, sell covered calls on part of it, or hedge with a protective put or collar."}
            for t, v in sorted(value.items(), key=lambda kv: -kv[1]) if v / total * 100 > CONCENTRATION_PCT]


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


def build(user_id: int, option_actions: dict) -> dict:
    holdings = [h for h in database.get_user_holdings(user_id) if h["shares"] > 0]
    options = database.get_user_options(user_id)
    prices = _prices(sorted({h["ticker"] for h in holdings}))
    items = (_option_items(option_actions) + _cash_items(user_id) + _concentration_items(holdings, prices)
             + _covered_call_items(holdings, options) + _tax_items(holdings, prices))
    items.sort(key=lambda i: LEVELS[i["level"]])
    return {"items": items, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "Rule-based checks on the positions and cash recorded here. Not investment advice."}
