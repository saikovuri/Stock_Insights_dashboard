"""Everything the signed-in user has recorded for one ticker: open lots and options, past results, and the
price levels that matter to them (cost basis, option strikes, price alerts) for the chart."""

from collections import defaultdict

import database


def _win_stats(values: list[float]) -> dict:
    wins = [v for v in values if v > 0]
    return {"count": len(values), "pnl": round(sum(values), 2),
            "win_rate": round(len(wins) / len(values) * 100) if values else None}


def summary(user_id: int, ticker: str) -> dict:
    ticker = ticker.upper()
    lots = [h for h in database.get_user_holdings(user_id) if h["ticker"] == ticker and h["shares"] > 0]
    options = [o for o in database.get_user_options(user_id) if o["ticker"] == ticker]
    closed_stocks = [t for t in database.get_closed_trades(user_id) if t["ticker"] == ticker]
    closed_options = [o for o in database.get_closed_options(user_id) if o["ticker"] == ticker]
    alerts = [a for a in database.list_user_alerts(user_id, ticker)
              if a.get("active") in (1, True) and a["kind"] in ("price_above", "price_below")]

    by_account = defaultdict(lambda: {"shares": 0.0, "cost": 0.0})
    for h in lots:
        entry = by_account[h.get("account") or database.DEFAULT_ACCOUNT]
        entry["shares"] += h["shares"]
        entry["cost"] += h["shares"] * h["buy_price"]
    accounts = [{"account": name, "shares": round(v["shares"], 6), "avg_cost": round(v["cost"] / v["shares"], 2)}
                for name, v in sorted(by_account.items())]
    shares = sum(a["shares"] for a in accounts)
    cost = sum(v["cost"] for v in by_account.values())

    levels = [{"price": a["avg_cost"], "kind": "cost",
               "label": f"Cost {a['account']}" if len(accounts) > 1 else "Your cost"} for a in accounts]
    for o in options:
        side = "Short" if o["position"] == "short" else "Long"
        levels.append({"price": float(o["strike"]), "kind": f"{o['position']}_{o['option_type']}",
                       "label": f"{side} {o['option_type'][0].upper()} {str(o['expiry'])[:10]}"})
    for a in alerts:
        levels.append({"price": float(a["value"]), "kind": "alert",
                       "label": f"Alert {'above' if a['kind'] == 'price_above' else 'below'}"})

    return {
        "ticker": ticker,
        "shares": round(shares, 6), "avg_cost": round(cost / shares, 2) if shares else None,
        "first_bought": min((str(h.get("date_added"))[:10] for h in lots), default=None),
        "accounts": accounts,
        "options": [{"id": o["id"], "type": o["option_type"], "position": o["position"], "strike": o["strike"],
                     "expiry": str(o["expiry"])[:10], "contracts": o["contracts"], "premium": o["premium"],
                     "account": o.get("account") or database.DEFAULT_ACCOUNT} for o in options],
        "closed_stock": _win_stats([t["pnl"] for t in closed_stocks if t.get("pnl") is not None]),
        "closed_options": _win_stats([o["pnl"] for o in closed_options if o.get("pnl") is not None]),
        "levels": sorted(levels, key=lambda level: -level["price"]),
        "empty": not (lots or options or closed_stocks or closed_options or alerts),
    }
