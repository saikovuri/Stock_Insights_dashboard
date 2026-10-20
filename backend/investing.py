"""Long-term investing: the long-term vs trading split, a monthly investing plan, sweeping trading profits into the
long-term side, and a scorecard of closed trades against simply holding SPY for the same time."""
import json
import logging
import math
from collections import defaultdict
from datetime import date, datetime, timezone

import accounts
import database
import risk_guard
from cache import get_or_fetch
from database import kv_get, kv_set

log = logging.getLogger(__name__)
PROJECTION_RATES = (0.04, 0.07, 0.10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _month(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def _previous_month(today: date) -> tuple[int, int]:
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


# ── Split ────────────────────────────────────────────────────────────────

def split(user_id: int, rules: dict) -> dict:
    roles = accounts.get_roles(user_id)
    values = risk_guard.account_values(user_id)
    names = sorted(set(values) | {a["name"] for a in accounts.list_accounts(user_id)["accounts"]})
    rows = [{"account": name, "role": accounts.role_of(roles, name), "role_set": name in roles,
             "stocks": round(values.get(name, {}).get("stocks", 0), 2), "cash": values.get(name, {}).get("cash"),
             "value": round(values.get(name, {}).get("value", 0), 2)} for name in names]
    total = sum(r["value"] for r in rows)
    by_role = {role: round(sum(r["value"] for r in rows if r["role"] == role), 2) for role in accounts.ROLES}
    year = date.today().year
    realized = defaultdict(float)
    for r in risk_guard.closed_results(user_id):
        if r["closed"] and r["closed"].year == year:
            realized[accounts.role_of(roles, r["account"])] += r["net"]
    target = rules.get("target_trading_pct")
    trading_pct = round(by_role["trading"] / total * 100, 1) if total > 0 else None
    drift = None if target is None or trading_pct is None else round(trading_pct - target, 1)
    move = None
    if drift is not None and abs(drift) >= 2:
        amount = abs(drift) / 100 * total
        move = {"from": "trading" if drift > 0 else "long_term", "to": "long_term" if drift > 0 else "trading",
                "amount": round(amount, 2)}
    return {"accounts": rows, "total": round(total, 2), "by_role": by_role, "trading_pct": trading_pct,
            "target_trading_pct": target, "drift_pct": drift, "rebalance": move,
            "realized_this_year": {role: round(realized[role], 2) for role in accounts.ROLES},
            "roles_set": bool(roles),
            "note": "Values are stock value (live quote, else cost) plus entered cash; option positions are not included. "
                    "Accounts without a role count as trading. App accounts are labels, so one broker account can be split "
                    "into a long-term and a trading label here."}


# ── Monthly plan ─────────────────────────────────────────────────────────

def get_plan(user_id: int) -> dict | None:
    row = database._run(f"SELECT plan FROM invest_plans WHERE user_id={database.PH}", (user_id,), "one")
    return json.loads(row["plan"]) if row else None


def save_plan(user_id: int, plan: dict) -> dict:
    total = sum(t["pct"] for t in plan["targets"])
    if abs(total - 100) > 0.01:
        raise ValueError(f"Target percentages add up to {total:g}%; they must add up to 100%")
    tickers = [t["ticker"] for t in plan["targets"]]
    if len(set(tickers)) != len(tickers):
        raise ValueError("Each ticker can appear once in the plan")
    PH = database.PH
    database._run(f"""INSERT INTO invest_plans (user_id, plan, updated_at) VALUES ({PH}, {PH}, {PH})
        ON CONFLICT (user_id) DO UPDATE SET plan=excluded.plan, updated_at=excluded.updated_at""",
                  (user_id, json.dumps(plan), _now()))
    return plan


def delete_plan(user_id: int) -> bool:
    return database._run(f"DELETE FROM invest_plans WHERE user_id={database.PH}", (user_id,)) > 0


def suggest_buys(targets: list[dict], values: dict[str, float], prices: dict[str, float | None], amount: float) -> list[dict]:
    """Split this month's amount across the targets, filling the most underweight first so the mix moves toward target."""
    total_after = sum(values.get(t["ticker"], 0) for t in targets) + amount
    gaps = {t["ticker"]: max(t["pct"] / 100 * total_after - values.get(t["ticker"], 0), 0) for t in targets}
    gap_total = sum(gaps.values())
    out = []
    for t in targets:
        share = gaps[t["ticker"]] / gap_total if gap_total > 0 else t["pct"] / 100
        dollars = round(amount * share, 2)
        price = prices.get(t["ticker"])
        out.append({"ticker": t["ticker"], "target_pct": t["pct"], "value": round(values.get(t["ticker"], 0), 2),
                    "current_pct": None if total_after - amount <= 0 else round(values.get(t["ticker"], 0) / (total_after - amount) * 100, 1),
                    "buy": dollars, "price": price,
                    "shares": None if not price else math.floor(dollars / price * 1000) / 1000})
    return out


def project(start: float, monthly: float, years: int, rate: float) -> float:
    r = rate / 12
    n = years * 12
    grown = start * (1 + r) ** n
    return grown + (monthly * (((1 + r) ** n - 1) / r) if r else monthly * n)


def years_to_goal(start: float, monthly: float, goal: float, rate: float) -> float | None:
    if goal <= start:
        return 0.0
    value, months = start, 0
    while value < goal and months < 600:
        value = value * (1 + rate / 12) + monthly
        months += 1
    return round(months / 12, 1) if value >= goal else None


def plan_status(user_id: int, today: date | None = None) -> dict | None:
    plan = get_plan(user_id)
    if not plan:
        return None
    today = today or date.today()
    account = plan.get("account") or database.DEFAULT_ACCOUNT
    prices, values = {}, defaultdict(float)
    invested = 0.0
    other = defaultdict(float)
    targets = {t["ticker"] for t in plan["targets"]}
    for h in database.get_user_holdings(user_id):
        if h["shares"] <= 0 or (h.get("account") or database.DEFAULT_ACCOUNT) != account:
            continue
        mark = risk_guard._price(h["ticker"], prices) or h["buy_price"]
        (values if h["ticker"] in targets else other)[h["ticker"]] += h["shares"] * mark
        added = risk_guard._day(h.get("date_added"))
        if added and (added.year, added.month) == (today.year, today.month):
            invested += h["shares"] * h["buy_price"]
    for t in targets:
        risk_guard._price(t, prices)
    monthly = float(plan["monthly"])
    remaining = max(monthly - invested, 0)
    buys = suggest_buys(plan["targets"], values, prices, remaining if remaining > 0 else monthly)
    cash = next((a["cash"] for a in accounts.list_accounts(user_id)["accounts"] if a["name"] == account), None)
    start = sum(values.values()) + sum(other.values()) + (cash or 0)
    goal = plan.get("goal")
    rates = sorted({*PROJECTION_RATES, float(plan.get("assumed_return_pct") or 7) / 100})
    projection = [{"rate_pct": round(rate * 100, 1), "years": {y: round(project(start, monthly, y, rate)) for y in (5, 10, 20)},
                   "years_to_goal": years_to_goal(start, monthly, goal, rate) if goal else None} for rate in rates]
    day = int(plan.get("day") or 1)
    return {"plan": plan, "account": account, "role": accounts.role_of(accounts.get_roles(user_id), account),
            "month": _month(today), "invested_this_month": round(invested, 2), "remaining": round(remaining, 2),
            "due": today.day >= day and remaining > 0, "buys": buys, "outside_plan": {k: round(v, 2) for k, v in other.items()},
            "start_value": round(start, 2), "projection": projection,
            "note": "Invested this month counts stock lots recorded in the plan account this month at their cost. Suggested buys fill "
                    "the most underweight targets first. Projections compound monthly at fixed rates: assumptions, not forecasts; "
                    "real returns vary a lot year to year and include losing years."}


# ── Profit sweep ─────────────────────────────────────────────────────────

def sweep_status(user_id: int, rules: dict, today: date | None = None) -> dict | None:
    pct = rules.get("profit_sweep_pct")
    if pct is None:
        return None
    today = today or date.today()
    year, month = _previous_month(today)
    roles = accounts.get_roles(user_id)
    net = sum(r["net"] for r in risk_guard.closed_results(user_id)
              if r["closed"] and (r["closed"].year, r["closed"].month) == (year, month)
              and accounts.role_of(roles, r["account"]) == "trading")
    key = f"{year}-{month:02d}"
    done = kv_get(f"sweep:{user_id}:{key}")
    return {"month": key, "trading_net": round(net, 2), "pct": pct, "amount": round(max(net, 0) * pct / 100, 2),
            "done": bool(done), "done_detail": done["data"] if done else None}


def record_sweep(user_id: int, from_account: str, to_account: str, amount: float, today: date | None = None) -> dict:
    today = today or date.today()
    year, month = _previous_month(today)
    key = f"{year}-{month:02d}"
    if kv_get(f"sweep:{user_id}:{key}"):
        raise ValueError(f"The move for {key} is already recorded")
    cash = {a["name"]: a["cash"] for a in accounts.list_accounts(user_id)["accounts"]}
    moved = []
    # Only when both sides have a balance, so the money is never removed from one side without arriving on the other
    if cash.get(from_account) is not None and cash.get(to_account) is not None:
        accounts.set_cash(user_id, from_account, cash[from_account] - amount)
        accounts.set_cash(user_id, to_account, cash[to_account] + amount)
        moved = [from_account, to_account]
    detail = {"from": from_account, "to": to_account, "amount": amount, "cash_updated": moved, "at": _now()}
    kv_set(f"sweep:{user_id}:{key}", detail)
    return {"month": key, **detail}


# ── Scorecard vs SPY ─────────────────────────────────────────────────────

def _spy_closes(start: date):
    import pandas as pd
    from stock_data import get_stock_data
    years = (date.today() - start).days / 365
    period = "2y" if years < 1.9 else "5y" if years < 4.9 else "10y"
    closes = get_stock_data("SPY", period=period, interval="1d")["Close"]
    closes.index = pd.to_datetime(closes.index.date)
    return closes.sort_index()


def scorecard(user_id: int, scope: str = "trading") -> dict:
    roles = accounts.get_roles(user_id)
    rows = [r for r in risk_guard.closed_results(user_id)
            if scope == "all" or accounts.role_of(roles, r["account"]) == scope]
    usable = [r for r in rows if r["opened"] and r["closed"] and r["closed"] >= r["opened"]]
    skipped = len(rows) - len(usable)
    if not usable:
        return {"scope": scope, "trades": 0, "skipped": skipped, "groups": [], "months": [], "totals": None,
                "note": "No closed trades with both an open and a close date yet."}
    import pandas as pd
    try:
        closes = _spy_closes(min(r["opened"] for r in usable))
    except Exception as error:
        log.info("SPY history unavailable for scorecard: %s", error)
        raise LookupError("SPY price history is unavailable right now; try again later")

    def close_on(day):
        prior = closes[closes.index <= pd.Timestamp(day)]
        return float(prior.iloc[-1]) if len(prior) else None

    scored = []
    for r in usable:
        start, end = close_on(r["opened"]), close_on(r["closed"])
        if not start or not end:
            skipped += 1
            continue
        spy = r["capital"] * (end / start - 1)
        scored.append({**r, "spy": spy, "days": (r["closed"] - r["opened"]).days})

    def summarize(items):
        net, spy = sum(i["net"] for i in items), sum(i["spy"] for i in items)
        capital = sum(i["capital"] for i in items)
        return {"trades": len(items), "net": round(net, 2), "spy": round(spy, 2), "edge": round(net - spy, 2),
                "win_rate": round(sum(i["net"] > 0 for i in items) / len(items) * 100) if items else None,
                "capital": round(capital, 2), "edge_pct_of_capital": round((net - spy) / capital * 100, 1) if capital else None,
                "avg_days": round(sum(i["days"] for i in items) / len(items), 1) if items else None}

    groups = defaultdict(list)
    months = defaultdict(list)
    for i in scored:
        groups[i["strategy"]].append(i)
        months[_month(i["closed"])].append(i)
    return {
        "scope": scope, "trades": len(scored), "skipped": skipped, "totals": summarize(scored),
        "groups": sorted(({"strategy": k, **summarize(v)} for k, v in groups.items()), key=lambda g: g["edge"]),
        "months": [{"month": k, **summarize(v)} for k, v in sorted(months.items())][-24:],
        "note": "For each closed trade, the SPY comparison is the money that trade tied up (stock cost, cash for a "
                "sold put, the amount at risk for spreads and bought options; nothing extra for a covered call) held in SPY "
                "from the day it opened to the day it closed, at daily closes, without dividends. Your P&L is after recorded "
                "fees. Time between trades, when money sits idle, is not counted: buy-and-hold SPY would also have earned "
                "then, so this flatters trading. Trades without an open date are skipped.",
    }


def scorecard_cached(user_id: int, scope: str) -> dict:
    version = database._run(f"""SELECT (SELECT COUNT(*) FROM closed_trades WHERE user_id={database.PH})
        + (SELECT COUNT(*) FROM closed_options WHERE user_id={database.PH}) AS n""", (user_id, user_id), "one")["n"]
    return get_or_fetch(f"scorecard:{user_id}:{scope}:{version}", lambda: scorecard(user_id, scope), ttl=600)


# ── Next steps items ─────────────────────────────────────────────────────

def next_step_items(user_id: int, rules: dict) -> list[dict]:
    items = []
    status = plan_status(user_id)
    if status and status["due"]:
        top = [b for b in status["buys"] if b["buy"] >= 1][:4]
        items.append({"level": "idea", "code": "plan_due",
                      "title": f"Monthly plan: ${status['remaining']:,.0f} of ${status['plan']['monthly']:,.0f} still to invest this month",
                      "points": [f"{b['ticker']}: about ${b['buy']:,.0f}" + (f" (~{b['shares']:g} sh at ${b['price']:,.2f})" if b["shares"] else "")
                                 for b in top],
                      "detail": f"Buy in {status['account']}. Suggested amounts fill your most underweight targets first.",
                      "link": {"kind": "plan"}})
    sweep = sweep_status(user_id, rules)
    if sweep and not sweep["done"] and sweep["amount"] >= 1:
        items.append({"level": "idea", "code": "sweep_due",
                      "title": f"Move ${sweep['amount']:,.0f} of last month's trading profit to long-term",
                      "detail": f"Trading accounts made ${sweep['trading_net']:,.0f} net in {sweep['month']}; your rule moves {sweep['pct']:g}%.",
                      "link": {"kind": "plan"}})
    target = rules.get("target_trading_pct")
    if target is not None:
        s = split(user_id, rules)
        if s["drift_pct"] is not None and s["drift_pct"] >= 5:
            items.append({"level": "warn", "code": "rule_split_drift",
                          "title": f"Rule: trading is {s['trading_pct']:g}% of your money (your target {target:g}%)",
                          "detail": f"About ${s['rebalance']['amount']:,.0f} more than your target sits on the trading side. "
                                    "Move it to long-term, or let monthly investing catch up.", "link": {"kind": "plan"}})
    return items
