"""Personal trading rules a user sets for themselves. Violations appear in Next steps and as daily notifications."""

import json
from collections import defaultdict
from datetime import datetime, timezone

import database

DEFAULTS = {"max_position_pct": None, "min_free_cash_pct": None, "take_profit_pct": None, "stop_loss_multiple": None,
            "no_calls_below_cost": False, "no_short_through_earnings": False}


def get_rules(user_id: int) -> dict:
    row = database._run(f"SELECT rules FROM user_rules WHERE user_id={database.PH}", (user_id,), "one")
    return {**DEFAULTS, **(json.loads(row["rules"]) if row else {})}


def save_rules(user_id: int, rules: dict) -> dict:
    clean = {k: rules.get(k, DEFAULTS[k]) for k in DEFAULTS}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    database._run(f"""INSERT INTO user_rules (user_id, rules, updated_at) VALUES ({database.PH}, {database.PH}, {database.PH})
        ON CONFLICT (user_id) DO UPDATE SET rules=excluded.rules, updated_at=excluded.updated_at""",
                  (user_id, json.dumps(clean), now))
    return clean


def user_ids() -> list[int]:
    return [r["user_id"] for r in database._run("SELECT user_id FROM user_rules", (), "all")]


def violations(rules: dict, holdings: list[dict], options: list[dict], prices: dict, actions: dict,
               account_rows: list[dict]) -> list[dict]:
    items = []
    acct = lambda row: row.get("account") or database.DEFAULT_ACCOUNT  # noqa: E731
    if rules.get("min_free_cash_pct") is not None:
        stock_value = defaultdict(float)
        for h in holdings:
            if prices.get(h["ticker"]):
                stock_value[acct(h)] += h["shares"] * prices[h["ticker"]]
        for a in account_rows:
            if a["cash"] is None:
                continue
            total = a["cash"] + stock_value[a["name"]]
            pct = (a["free_cash"] or 0) / total * 100 if total > 0 else 0
            if pct < rules["min_free_cash_pct"]:
                items.append({"level": "warn", "code": "rule_free_cash", "account": a["name"],
                              "title": f"Rule: {a['name']} free cash is {pct:.0f}% of the account (your minimum {rules['min_free_cash_pct']:g}%)",
                              "detail": "Free cash is cash minus short-put collateral. Close or roll a put, add cash, or trim a position."})
    if rules.get("take_profit_pct") is not None:
        hits = [p for p in actions.get("positions", []) if p.get("position") == "short"
                and (p.get("profit_captured_pct") or 0) >= rules["take_profit_pct"]]
        if hits:
            items.append({"level": "act", "code": "rule_take_profit",
                          "title": f"Rule: {len(hits)} short option(s) reached your {rules['take_profit_pct']:g}% take-profit",
                          "points": [f"{p['ticker']} ${p['strike']:g} {p['type']} {p['expiry']}: {p['profit_captured_pct']}% captured" for p in hits[:5]],
                          "detail": "Buy to close to lock in the gain, or update the rule.", "link": {"kind": "alerts"}})
    if rules.get("stop_loss_multiple") is not None:
        hits = [p for p in actions.get("positions", []) if p.get("position") == "short"
                and p.get("loss_multiple") is not None and p["loss_multiple"] >= rules["stop_loss_multiple"]]
        if hits:
            items.append({"level": "act", "code": "rule_stop_loss",
                          "title": f"Rule: {len(hits)} short option(s) hit your {rules['stop_loss_multiple']:g}× credit stop",
                          "points": [f"{p['ticker']} ${p['strike']:g} {p['type']} {p['expiry']}: loss {p['loss_multiple']:g}× the credit"
                                     for p in hits[:5]],
                          "detail": "Your rule is to buy to close here rather than roll and hope.", "link": {"kind": "alerts"}})
    if rules.get("no_calls_below_cost"):
        cost, shares = defaultdict(float), defaultdict(float)
        for h in holdings:
            cost[(acct(h), h["ticker"])] += h["shares"] * h["buy_price"]
            shares[(acct(h), h["ticker"])] += h["shares"]
        for o in options:
            key = (acct(o), o["ticker"])
            if o["position"] == "short" and o["option_type"] == "call" and shares[key] and o["strike"] < cost[key] / shares[key]:
                avg = cost[key] / shares[key]
                items.append({"level": "warn", "code": "rule_call_below_cost", "account": key[0], "ticker": o["ticker"],
                              "title": f"Rule: {o['ticker']} ${o['strike']:g} call is below your ${avg:,.2f} average cost",
                              "detail": "Assignment would sell the shares at a loss. Consider rolling up and out."})
    if rules.get("no_short_through_earnings"):
        hits = [p for p in actions.get("positions", []) if p.get("position") == "short"
                and any(a["code"] == "earnings" for a in p.get("actions", []))]
        if hits:
            items.append({"level": "warn", "code": "rule_earnings",
                          "title": f"Rule: {len(hits)} short option(s) are open through earnings",
                          "points": [f"{p['ticker']} ${p['strike']:g} {p['type']} {p['expiry']}" for p in hits[:5]],
                          "detail": "Your rule is to avoid holding short options through a report.", "link": {"kind": "alerts"}})
    return items
