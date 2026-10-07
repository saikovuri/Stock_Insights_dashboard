"""Expiration ladder: what each upcoming expiry could do to cash and shares if assigned, and which stock lots
a short call would deliver (oldest first vs. highest cost basis first)."""

import logging
from collections import defaultdict
from datetime import date, datetime, timezone

import accounts
import database
from portfolio_insights import _d
from stock_data import get_quote

log = logging.getLogger(__name__)
LONG_TERM_DAYS = 365


def _spot(ticker: str, cache: dict) -> float | None:
    if ticker not in cache:
        try:
            cache[ticker] = get_quote(ticker).get("price") or None
        except Exception as error:
            log.info("No quote for %s: %s", ticker, error)
            cache[ticker] = None
    return cache[ticker]


def _deliver(pool: list[dict], shares: float, strike: float, expiry: date) -> dict:
    """Take shares from the front of pool (mutating it) and report the realized gain split by holding period."""
    picked, left = [], shares
    while left > 1e-9 and pool:
        lot = pool[0]
        n = min(lot["left"], left)
        lot["left"] -= n
        left -= n
        if lot["left"] <= 1e-9:
            pool.pop(0)
        acquired = _d(lot.get("date_added"))
        long_term = bool(acquired and (expiry - acquired).days > LONG_TERM_DAYS)
        picked.append({"lot_id": lot["id"], "acquired": acquired.isoformat() if acquired else None, "shares": round(n, 6),
                       "basis": lot["buy_price"], "gain": round((strike - lot["buy_price"]) * n, 2), "long_term": long_term})
    return {"lots": picked, "uncovered_shares": round(left, 6),
            "gain": round(sum(p["gain"] for p in picked), 2),
            "short_term_gain": round(sum(p["gain"] for p in picked if not p["long_term"]), 2),
            "long_term_gain": round(sum(p["gain"] for p in picked if p["long_term"]), 2)}


def build(user_id: int, option_actions: dict) -> dict:
    today = date.today()
    deltas = {p["id"]: p.get("delta") for p in option_actions.get("positions", [])}
    options = sorted((o for o in database.get_user_options(user_id) if str(o["expiry"])[:10] >= today.isoformat()),
                     key=lambda o: (str(o["expiry"])[:10], o["ticker"], o["strike"]))
    lots = defaultdict(list)
    for h in database.get_user_holdings(user_id):
        if h["shares"] > 0:
            lots[(h.get("account") or database.DEFAULT_ACCOUNT, h["ticker"])].append({**h, "left": h["shares"]})
    # Two independent pools per account/ticker, so several short calls don't deliver the same shares twice.
    fifo_pools = {k: sorted((dict(l) for l in v), key=lambda l: (str(l.get("date_added")), l["id"])) for k, v in lots.items()}
    smart_pools = {k: sorted((dict(l) for l in v), key=lambda l: (-l["buy_price"], str(l.get("date_added")), l["id"]))
                   for k, v in lots.items()}
    free_cash = {a["name"]: a["free_cash"] for a in accounts.list_accounts(user_id)["accounts"]}
    spots, groups = {}, defaultdict(list)
    for o in options:
        account = o.get("account") or database.DEFAULT_ACCOUNT
        expiry = date.fromisoformat(str(o["expiry"])[:10])
        K, n, spot = float(o["strike"]), int(o["contracts"]), _spot(o["ticker"], spots)
        call = o["option_type"] == "call"
        itm = None if spot is None else (spot > K if call else spot < K)
        delta = deltas.get(o["id"])
        entry = {"id": o["id"], "ticker": o["ticker"], "account": account, "type": o["option_type"], "position": o["position"],
                 "strike": K, "contracts": n, "spot": spot, "itm": itm,
                 "distance_pct": None if spot is None else round((K - spot) / spot * 100, 1),
                 "chance_itm_pct": None if delta is None else round(abs(delta) * 100)}
        if o["position"] == "short" and not call:
            entry["cash_if_assigned"] = round(K * 100 * n, 2)
        elif o["position"] == "short":
            key = (account, o["ticker"])
            shares = 100 * n
            fifo = _deliver(fifo_pools.get(key, []), shares, K, expiry)
            smart = _deliver(smart_pools.get(key, []), shares, K, expiry)
            entry.update({"shares_if_assigned": shares, "proceeds_if_assigned": round(K * shares, 2),
                          "oldest_first": fifo, "highest_cost_first": smart,
                          "gain_difference": round(fifo["gain"] - smart["gain"], 2)})
        elif spot is not None:
            entry["intrinsic_now"] = round(max(0.0, (spot - K) if call else (K - spot)) * 100 * n, 2)
        groups[expiry.isoformat()].append(entry)

    ladder = []
    for expiry, rows in sorted(groups.items()):
        puts = [r for r in rows if "cash_if_assigned" in r]
        calls = [r for r in rows if "shares_if_assigned" in r]
        ladder.append({
            "expiry": expiry, "dte": (date.fromisoformat(expiry) - today).days, "positions": rows,
            "contracts": sum(r["contracts"] for r in rows),
            "cash_if_all_puts_assigned": round(sum(r["cash_if_assigned"] for r in puts), 2),
            "cash_if_itm_puts_assigned": round(sum(r["cash_if_assigned"] for r in puts if r["itm"]), 2),
            "shares_if_itm_calls_assigned": sum(r["shares_if_assigned"] for r in calls if r["itm"]),
            "proceeds_if_itm_calls_assigned": round(sum(r["proceeds_if_assigned"] for r in calls if r["itm"]), 2),
            "gain_if_itm_calls_assigned": round(sum(r["oldest_first"]["gain"] for r in calls if r["itm"]), 2),
        })
    return {"expiries": ladder, "free_cash": free_cash, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "In the money uses the latest quote; the chance is the option's |delta|, a model estimate. "
                    "Lot plans assume each short call is assigned in expiry order and share pools are not reused."}
