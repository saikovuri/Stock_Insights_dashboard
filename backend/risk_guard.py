"""Risk guard: how much each open trade can lose, the total open risk (portfolio heat), a pre-trade check against the
user's rules, and a loss circuit breaker.

"Risk" is the loss if the trade's planned exit is hit, or its worst case when there is no planned exit:
- stocks: down to your stop for that ticker, or the whole position without one;
- bought options and debit structures: what was paid;
- credit structures (spreads, condors): their max loss;
- sold puts/calls on their own: your stop-loss multiple of the credit when that rule is set; otherwise a sold put's
  loss if assigned and the stock went to zero, and an uncovered call is unlimited (not summed, flagged instead).
Covered calls add no risk of their own: the shares carry it.
Only trading accounts count; long-term accounts are managed by allocation, not stops.
"""
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import accounts
import database
from stock_data import get_quote

log = logging.getLogger(__name__)
DEFAULT_COOLDOWN_DAYS = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _acct(row: dict) -> str:
    return row.get("account") or database.DEFAULT_ACCOUNT


def _price(ticker: str, cache: dict) -> float | None:
    if ticker not in cache:
        try:
            cache[ticker] = get_quote(ticker).get("price") or None
        except Exception as error:
            log.info("No quote for %s: %s", ticker, error)
            cache[ticker] = None
    return cache[ticker]


# ── Stops ────────────────────────────────────────────────────────────────

def get_stops(user_id: int) -> dict[tuple[str, str], float]:
    rows = database._run(f"SELECT account, ticker, stop FROM position_stops WHERE user_id={database.PH}", (user_id,), "all")
    return {(r["account"], r["ticker"]): r["stop"] for r in rows}


def prune_stops(user_id: int) -> int:
    """Delete stops for positions that no longer have shares, so a later re-buy doesn't inherit an old stop."""
    held = {(_acct(h), h["ticker"]) for h in database.get_user_holdings(user_id) if h["shares"] > 0}
    stale = [key for key in get_stops(user_id) if key not in held]
    for account, ticker in stale:
        database._run(f"DELETE FROM position_stops WHERE user_id={database.PH} AND account={database.PH} AND ticker={database.PH}",
                      (user_id, account, ticker))
    return len(stale)


def set_stop(user_id: int, account: str | None, ticker: str, stop: float | None) -> dict:
    name, ticker = database.account_name(account) or database.DEFAULT_ACCOUNT, ticker.upper()
    PH = database.PH
    if stop is None:
        database._run(f"DELETE FROM position_stops WHERE user_id={PH} AND account={PH} AND ticker={PH}", (user_id, name, ticker))
    else:
        database._run(f"""INSERT INTO position_stops (user_id, account, ticker, stop, updated_at) VALUES ({', '.join([PH] * 5)})
            ON CONFLICT (user_id, account, ticker) DO UPDATE SET stop=excluded.stop, updated_at=excluded.updated_at""",
                      (user_id, name, ticker, float(stop), _now()))
    return {"account": name, "ticker": ticker, "stop": stop}


# ── Account values ───────────────────────────────────────────────────────

def account_values(user_id: int, prices: dict | None = None) -> dict[str, dict]:
    """Per account: stock value (live quote, else cost), entered cash and their sum. Options are not included."""
    prices = {} if prices is None else prices
    out = defaultdict(lambda: {"stocks": 0.0, "cash": None, "value": 0.0})
    for h in database.get_user_holdings(user_id):
        if h["shares"] > 0:
            out[_acct(h)]["stocks"] += h["shares"] * (_price(h["ticker"], prices) or h["buy_price"])
    for a in accounts.list_accounts(user_id)["accounts"]:
        out[a["name"]]["cash"] = a["cash"]
    for row in out.values():
        row["value"] = row["stocks"] + (row["cash"] or 0)
    return dict(out)


# ── Position risk ────────────────────────────────────────────────────────

def _option_risk(o: dict, covered: bool, rules: dict) -> tuple[float | None, str, list[str]]:
    n, prem, mult = o["contracts"], o["premium"], rules.get("stop_loss_multiple")
    if o["position"] == "long":
        return prem * 100 * n, "the premium paid", []
    if o["option_type"] == "call" and covered:
        return 0.0, "covered by your shares (the shares carry the risk)", []
    if mult:
        return prem * mult * 100 * n, f"to your {mult:g}× credit stop", [] if o["option_type"] == "put" else ["uncovered"]
    if o["option_type"] == "put":
        return max(o["strike"] - prem, 0) * 100 * n, "if assigned and the stock went to zero", ["no_planned_exit"]
    return None, "unlimited: an uncovered call has no ceiling", ["unlimited"]


def positions(user_id: int, rules: dict, prices: dict | None = None, roles: dict | None = None) -> list[dict]:
    """Every open position with its risk, grouped by account and ticker for stocks and by structure for spreads."""
    import spreads
    prices = {} if prices is None else prices
    roles = accounts.get_roles(user_id) if roles is None else roles
    stops = get_stops(user_id)
    rows = []
    shares = defaultdict(float)
    lots = defaultdict(list)
    for h in database.get_user_holdings(user_id):
        if h["shares"] > 0:
            lots[(_acct(h), h["ticker"])].append(h)
            shares[(_acct(h), h["ticker"])] += h["shares"]
    for (account, ticker), group in sorted(lots.items()):
        qty = sum(h["shares"] for h in group)
        cost = sum(h["shares"] * h["buy_price"] for h in group) / qty
        price = _price(ticker, prices)
        mark = price or cost
        stop = stops.get((account, ticker))
        if stop is not None and stop < mark:
            risk, basis, flags = (mark - stop) * qty, f"down to your ${stop:g} stop", []
        elif stop is not None:
            risk, basis, flags = mark * qty, f"price is at or below your ${stop:g} stop: exit or reset it", ["stop_breached"]
        else:
            risk, basis, flags = mark * qty, "no stop: the whole position", ["no_stop"]
        rows.append({"kind": "stock", "account": account, "ticker": ticker, "label": f"{qty:g} shares",
                     "value": round(mark * qty, 2), "price": price, "avg_cost": round(cost, 2), "stop": stop,
                     "risk": round(risk, 2), "basis": basis, "flags": flags})
    options = database.get_user_options(user_id)
    groups = spreads.group_open(options)
    in_group = {leg["id"] for legs in groups.values() for leg in legs}
    for spread_id, legs in groups.items():
        info = spreads.describe_open(legs)
        rows.append({"kind": "structure", "account": _acct(legs[0]), "ticker": legs[0]["ticker"],
                     "label": f"{info['label']} {info['strikes']} × {spreads.units_of(legs)}", "spread_id": spread_id,
                     "risk": round(info["max_loss"], 2), "basis": "its max loss" + (" (bound)" if info["multi_expiry"] else ""),
                     "flags": []})
    remaining = dict(shares)
    for o in sorted((o for o in options if o["id"] not in in_group), key=lambda o: o["id"]):
        key = (_acct(o), o["ticker"])
        covered = False
        if o["position"] == "short" and o["option_type"] == "call" and remaining.get(key, 0) >= 100 * o["contracts"]:
            remaining[key] -= 100 * o["contracts"]
            covered = True
        risk, basis, flags = _option_risk(o, covered, rules)
        rows.append({"kind": "option", "account": key[0], "ticker": o["ticker"], "option_id": o["id"],
                     "label": f"{o['position']} ${o['strike']:g} {o['option_type']} {o['expiry']} × {o['contracts']}",
                     "risk": None if risk is None else round(risk, 2), "basis": basis, "flags": flags})
    for row in rows:
        row["role"] = accounts.role_of(roles, row["account"])
    return rows


def heat(user_id: int, rules: dict | None = None) -> dict:
    """Total risk of open positions in trading accounts as a % of their value, with the breakdown."""
    import trading_rules
    rules = trading_rules.get_rules(user_id) if rules is None else rules
    # Also catches positions closed outside the sell routes (call assignment, cash mergers)
    prune_stops(user_id)
    prices, roles = {}, accounts.get_roles(user_id)
    values = account_values(user_id, prices)
    rows = [r for r in positions(user_id, rules, prices, roles) if r["role"] == "trading"]
    trading_value = sum(v["value"] for name, v in values.items() if accounts.role_of(roles, name) == "trading")
    total = sum(r["risk"] for r in rows if r["risk"] is not None)
    unlimited = [r for r in rows if r["risk"] is None]
    limit = rules.get("max_open_risk_pct")
    pct = round(total / trading_value * 100, 1) if trading_value > 0 else None
    return {
        "positions": sorted(rows, key=lambda r: -(r["risk"] if r["risk"] is not None else float("inf"))),
        "total_risk": round(total, 2), "trading_value": round(trading_value, 2), "pct": pct, "limit_pct": limit,
        "over_limit": bool(limit is not None and pct is not None and pct > limit),
        "unlimited": len(unlimited), "no_stop": sum("no_stop" in r["flags"] for r in rows),
        "roles_set": bool(roles), "cash_missing": any(v["cash"] is None for name, v in values.items()
                                                      if accounts.role_of(roles, name) == "trading"),
        "circuit": circuit(user_id, rules, trading_value, roles),
        "note": "Risk is the loss if each trade's planned exit is hit (your stop, or your stop-loss multiple for sold "
                "options), otherwise its worst case. Trading capital is stock value plus entered cash in trading "
                "accounts; option values are not included. Not broker margin.",
    }


# ── Closed results (shared with the scorecard) ──────────────────────────

def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def closed_results(user_id: int) -> list[dict]:
    """Closed stock trades and closed option trades (structures merged) with net P&L, dates, strategy and the
    capital they tied up."""
    import spreads
    out = []
    for t in database.get_closed_trades(user_id):
        net = t.get("net_pnl") if t.get("net_pnl") is not None else t["pnl"]
        out.append({"account": _acct(t), "ticker": t["ticker"], "strategy": "Stocks", "net": net,
                    "opened": _day(t.get("acquired_at")), "closed": _day(t.get("closed_at")),
                    "capital": t["buy_price"] * t["shares"]})
    for c in spreads.merge_closed(database.get_closed_options(user_id)):
        net = c.get("net_pnl") if c.get("net_pnl") is not None else c["pnl"]
        n = c["contracts"]
        if c.get("spread"):
            credit = c["spread"]["style"] == "credit"
            strategy = "Credit spreads & condors" if credit else "Debit spreads & other structures"
            capital = c["spread"]["max_loss"]
        elif c["position"] == "long":
            strategy, capital = "Long options", c["open_premium"] * 100 * n
        elif c["option_type"] == "put":
            strategy, capital = "Short puts", c["strike"] * 100 * n
        else:
            strategy, capital = "Short calls", 0.0
        out.append({"account": _acct(c), "ticker": c["ticker"], "strategy": strategy, "net": net,
                    "opened": _day(c.get("opened_at")), "closed": _day(c.get("closed_at")), "capital": capital})
    return out


# ── Circuit breaker ──────────────────────────────────────────────────────

def circuit(user_id: int, rules: dict, trading_value: float | None = None, roles: dict | None = None,
            today: date | None = None) -> dict:
    """Month-to-date realized loss in trading accounts against the monthly limit, and the current losing streak
    against the cooldown rule. Active means: stop opening new trades until `until`."""
    today = today or date.today()
    roles = accounts.get_roles(user_id) if roles is None else roles
    if trading_value is None:
        trading_value = sum(v["value"] for name, v in account_values(user_id).items() if accounts.role_of(roles, name) == "trading")
    results = [r for r in closed_results(user_id) if r["closed"] and accounts.role_of(roles, r["account"]) == "trading"]
    month = [r for r in results if (r["closed"].year, r["closed"].month) == (today.year, today.month)]
    month_net = round(sum(r["net"] for r in month), 2)
    loss_pct = round(-month_net / trading_value * 100, 1) if trading_value > 0 and month_net < 0 else 0.0
    streak, last_loss = 0, None
    for r in sorted(results, key=lambda r: r["closed"], reverse=True):
        if r["net"] >= 0:
            break
        streak += 1
        last_loss = last_loss or r["closed"]
    reasons, until = [], None
    limit = rules.get("max_monthly_loss_pct")
    if limit is not None and loss_pct >= limit:
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        reasons.append(f"Down {loss_pct:g}% of trading capital this month (your limit {limit:g}%)")
        until = nxt
    streak_limit = rules.get("loss_streak")
    if streak_limit and streak >= streak_limit and last_loss:
        days = int(rules.get("cooldown_days") or DEFAULT_COOLDOWN_DAYS)
        end = last_loss + timedelta(days=days)
        if end > today:
            reasons.append(f"{streak} losing trades in a row (your cooldown starts at {streak_limit:g})")
            until = max(until or end, end)
    return {"active": bool(reasons), "reasons": reasons, "until": until.isoformat() if until else None,
            "month_net": month_net, "month_loss_pct": loss_pct, "monthly_limit_pct": limit,
            "streak": streak, "streak_limit": streak_limit, "trades_this_month": len(month)}


# ── Pre-trade check ──────────────────────────────────────────────────────

def check(user_id: int, proposal: dict) -> dict:
    """Risk of a proposed trade and the rules it would break. Warnings only: nothing is blocked."""
    import spreads
    import trading_rules
    rules = trading_rules.get_rules(user_id)
    roles = accounts.get_roles(user_id)
    account = database.account_name(proposal.get("account")) or database.DEFAULT_ACCOUNT
    role = accounts.role_of(roles, account)
    ticker = proposal["ticker"].upper()
    prices = {}
    kind = proposal["kind"]
    warnings, notes = [], []
    unit_risk, size, basis, value = None, None, "", None
    if kind == "stock":
        price, size = float(proposal["price"]), float(proposal["shares"])
        stop = proposal.get("stop")
        if stop is None:
            stop = get_stops(user_id).get((account, ticker))
        value = price * size
        if stop is not None and stop < price:
            unit_risk, basis = price - stop, f"down to a ${stop:g} stop"
        else:
            unit_risk, basis = price, "no stop: the whole position"
            if role == "trading":
                notes.append("No stop set: the whole position counts as at risk. Add a stop to size this properly.")
    elif kind == "option":
        o = {"position": proposal["position"], "option_type": proposal["option_type"], "strike": float(proposal["strike"]),
             "premium": float(proposal["premium"]), "contracts": 1}
        size = int(proposal["contracts"])
        have = sum(h["shares"] for h in database.get_user_holdings(user_id) if _acct(h) == account and h["ticker"] == ticker)
        open_options = database.get_user_options(user_id)
        in_structure = {leg["id"] for legs in spreads.group_open(open_options).values() for leg in legs}
        # Shares already covering other sold calls can't cover this one too (same order as positions())
        for x in sorted(open_options, key=lambda x: x["id"]):
            if (x["id"] not in in_structure and x["position"] == "short" and x["option_type"] == "call" and _acct(x) == account
                    and x["ticker"] == ticker and have >= 100 * x["contracts"]):
                have -= 100 * x["contracts"]
        covered = o["position"] == "short" and o["option_type"] == "call" and have >= 100 * size
        one, basis, flags = _option_risk(o, covered, rules)
        unit_risk = None if one is None else one / 100  # per share, like the other kinds
        if "unlimited" in flags:
            warnings.append({"code": "unlimited", "text": "An uncovered short call has unlimited risk. Set a stop-loss "
                             "multiple rule or own the shares first."})
    else:
        legs = [{**leg, "ratio": int(leg.get("ratio") or 1)} for leg in proposal["legs"]]
        size = int(proposal["contracts"])
        info = spreads.describe(legs, 1)
        unit_risk, basis = info["max_loss"] / 100, "its max loss"
    risk = None if unit_risk is None else round(unit_risk * (size if kind == "stock" else 100 * size), 2)
    values = account_values(user_id, prices)
    trading_value = sum(v["value"] for name, v in values.items() if accounts.role_of(roles, name) == "trading")
    result = {"risk": risk, "basis": basis, "role": role, "account": account, "trading_value": round(trading_value, 2),
              "risk_pct": None, "heat_pct_before": None, "heat_pct_after": None, "warnings": warnings, "notes": notes,
              "max_size": None}
    if role == "long_term":
        notes.append("Long-term account: per-trade risk and open-risk limits apply to trading accounts only. "
                     "Check it against your monthly plan's target mix instead.")
        return result
    current = heat(user_id, rules)
    if trading_value > 0 and risk is not None:
        result["risk_pct"] = round(risk / trading_value * 100, 2)
        result["heat_pct_before"] = current["pct"]
        result["heat_pct_after"] = round((current["total_risk"] + risk) / trading_value * 100, 1)
        per_trade = rules.get("max_trade_risk_pct")
        if per_trade is not None and result["risk_pct"] > per_trade:
            per_unit = unit_risk if kind == "stock" else unit_risk * 100
            fit = int((per_trade / 100 * trading_value) // per_unit) if per_unit > 0 else None
            result["max_size"] = fit
            unit = "shares" if kind == "stock" else "contracts"
            warnings.append({"code": "trade_risk", "text": f"Risks {result['risk_pct']:g}% of trading capital; your limit is "
                             f"{per_trade:g}%. That limit allows about {fit} {unit}" + (" (or set a tighter stop)." if kind == "stock" else ".")})
        open_limit = rules.get("max_open_risk_pct")
        if open_limit is not None and result["heat_pct_after"] > open_limit:
            warnings.append({"code": "open_risk", "text": f"Total open risk would be {result['heat_pct_after']:g}% of trading "
                             f"capital; your limit is {open_limit:g}%. Close or tighten something first."})
    elif trading_value <= 0:
        notes.append("Enter cash for your trading accounts (Portfolio → Holdings) to measure risk as a % of capital.")
    if current["circuit"]["active"]:
        warnings.insert(0, {"code": "circuit", "text": f"Your circuit breaker is on until {current['circuit']['until']}: "
                            + "; ".join(current["circuit"]["reasons"]) + ". Your rule says no new trades until then."})
    position_limit = rules.get("max_position_pct")
    if kind == "stock" and position_limit is not None:
        stock_total = sum(v["stocks"] for v in values.values()) + value
        held = sum(h["shares"] * (_price(ticker, prices) or h["buy_price"]) for h in database.get_user_holdings(user_id)
                   if h["ticker"] == ticker and h["shares"] > 0)
        pct = (held + value) / stock_total * 100 if stock_total > 0 else 0
        if pct > position_limit:
            warnings.append({"code": "position", "text": f"{ticker} would be {pct:.0f}% of your stock value; your limit is {position_limit:g}%."})
    return result


# ── Next steps items ─────────────────────────────────────────────────────

def next_step_items(user_id: int, rules: dict) -> list[dict]:
    """Rule items about open risk, missing stops and the circuit breaker (codes start with rule_ so they are pushed)."""
    if not any(rules.get(k) is not None for k in ("max_open_risk_pct", "max_trade_risk_pct", "max_monthly_loss_pct", "loss_streak")):
        return []
    h = heat(user_id, rules)
    items = []
    c = h["circuit"]
    if c["active"]:
        items.append({"level": "act", "code": "rule_circuit_breaker", "title": f"Rule: stop opening new trades until {c['until']}",
                      "points": c["reasons"],
                      "detail": "Your circuit breaker is on. Manage or close what is open; review the losing trades in the Journal "
                                "before the next one. Long-term monthly investing can continue."})
    if h["over_limit"]:
        items.append({"level": "act", "code": "rule_open_risk",
                      "title": f"Rule: open risk is {h['pct']:g}% of trading capital (your limit {h['limit_pct']:g}%)",
                      "points": [f"{r['ticker']} {r['label']}: ${r['risk']:,.0f} ({r['basis']})" for r in h["positions"][:5] if r["risk"]],
                      "detail": "Set or tighten stops, close a position, or size down new trades. See Risk guard.", "link": {"kind": "risk_guard"}})
    breached = [r for r in h["positions"] if "stop_breached" in r["flags"]]
    if breached:
        items.append({"level": "act", "code": "rule_stop_breached", "title": f"Rule: {len(breached)} stock(s) are at or below your stop",
                      "points": [f"{r['ticker']} ({r['account']}): {r['basis']}" for r in breached[:5]],
                      "detail": "Your plan was to exit here. Sell, or reset the stop deliberately in Risk guard.", "link": {"kind": "risk_guard"}})
    no_stop = [r for r in h["positions"] if "no_stop" in r["flags"]]
    if rules.get("max_trade_risk_pct") is not None and no_stop:
        items.append({"level": "warn", "code": "rule_no_stop",
                      "title": f"Rule: {len(no_stop)} trading stock position(s) have no stop",
                      "points": [f"{r['ticker']} ({r['account']}): ${r['value']:,.0f} at risk" for r in no_stop[:5]],
                      "detail": "Without a stop the whole position is at risk. Set one in Risk guard, or mark the account long-term "
                                "if these are investments.", "link": {"kind": "risk_guard"}})
    if h["unlimited"]:
        items.append({"level": "act", "code": "rule_unlimited", "title": f"{h['unlimited']} uncovered short call(s) with unlimited risk",
                      "detail": "Buy a higher call to cap it, own the shares, or close it.", "link": {"kind": "risk_guard"}})
    return items
