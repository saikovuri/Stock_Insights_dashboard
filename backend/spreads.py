"""Two-leg vertical spreads. Each leg is a normal option row; the legs share a spread_id.

Bull spreads buy the lower strike and sell the higher one; bear spreads sell the lower strike and buy the higher one.
Calls/puts and bull/bear decide whether the spread is opened for a debit or a credit.
"""
from collections import defaultdict

KINDS = {
    "bull_call": {"type": "call", "style": "debit", "label": "Bull call"},
    "bear_put": {"type": "put", "style": "debit", "label": "Bear put"},
    "bull_put": {"type": "put", "style": "credit", "label": "Bull put"},
    "bear_call": {"type": "call", "style": "credit", "label": "Bear call"},
}


def kind_of(option_type: str, long_strike: float, short_strike: float) -> str:
    bull = long_strike < short_strike
    return f"{'bull' if bull else 'bear'}_{option_type}"


def validate_strikes(kind: str, long_strike: float, short_strike: float) -> None:
    if kind not in KINDS:
        raise ValueError("Unknown spread type")
    if long_strike == short_strike:
        raise ValueError("Spread strikes must differ")
    bull = kind.startswith("bull")
    if bull != (long_strike < short_strike):
        raise ValueError(f"A {KINDS[kind]['label'].lower()} spread buys the "
                         f"{'lower' if bull else 'higher'} strike and sells the {'higher' if bull else 'lower'} one")


def net_premium(kind: str, long_premium: float, short_premium: float) -> float:
    """Per-share debit paid (debit spreads) or credit received (credit spreads)."""
    return short_premium - long_premium if KINDS[kind]["style"] == "credit" else long_premium - short_premium


def metrics(kind: str, long_strike: float, short_strike: float, net: float, contracts: int) -> dict:
    """Max profit/loss and breakeven at expiry for the given per-share net debit or credit."""
    lower, upper = sorted((long_strike, short_strike))
    width = upper - lower
    credit = KINDS[kind]["style"] == "credit"
    per_share_profit, per_share_loss = (net, width - net) if credit else (width - net, net)
    if kind in ("bull_put", "bear_put"):
        breakeven = upper - net
    else:
        breakeven = lower + net
    return {"width": round(width, 4), "max_profit": round(per_share_profit * 100 * contracts, 2),
            "max_loss": round(per_share_loss * 100 * contracts, 2), "breakeven": round(breakeven, 4),
            "collateral": round(width * 100 * contracts, 2) if credit else 0.0}


def _same_contract(first: dict, second: dict) -> bool:
    return (first["ticker"] == second["ticker"] and first["option_type"] == second["option_type"]
            and str(first["expiry"])[:10] == str(second["expiry"])[:10]
            and (first.get("account") or "") == (second.get("account") or ""))


def pair_open(options: list[dict]) -> dict[str, tuple[dict, dict]]:
    """spread_id -> (long leg, short leg) for intact spreads: one long and one short leg of equal size.
    A spread missing a leg (closed or assigned separately) is left to be shown as single options."""
    groups = defaultdict(list)
    for option in options:
        if option.get("spread_id"):
            groups[option["spread_id"]].append(option)
    pairs = {}
    for spread_id, legs in groups.items():
        longs = [leg for leg in legs if leg.get("position") == "long"]
        shorts = [leg for leg in legs if leg.get("position") == "short"]
        if (len(legs) == 2 and len(longs) == 1 and len(shorts) == 1 and _same_contract(longs[0], shorts[0])
                and longs[0]["contracts"] == shorts[0]["contracts"]):
            pairs[spread_id] = (longs[0], shorts[0])
    return pairs


def describe(long_leg: dict, short_leg: dict) -> dict:
    kind = kind_of(long_leg["option_type"], long_leg["strike"], short_leg["strike"])
    net = net_premium(kind, long_leg["premium"], short_leg["premium"])
    return {"kind": kind, "label": KINDS[kind]["label"], "style": KINDS[kind]["style"],
            "long_strike": long_leg["strike"], "short_strike": short_leg["strike"], "net_open": round(net, 4),
            **metrics(kind, long_leg["strike"], short_leg["strike"], net, long_leg["contracts"])}


def merge_closed(rows: list[dict]) -> list[dict]:
    """Show each closed spread as one trade: legs sharing a spread_id are paired (long with short, in id order,
    equal contracts). The credit spread is recorded as a short position and the debit spread as a long one, with net
    premiums, so captured %, win rate and reviews treat it as a single trade. Unpaired legs stay as they are."""
    by_spread = defaultdict(list)
    for row in rows:
        if row.get("spread_id"):
            by_spread[row["spread_id"]].append(row)
    merged, consumed = {}, set()
    for legs in by_spread.values():
        longs = sorted((leg for leg in legs if leg["position"] == "long"), key=lambda leg: leg["id"])
        shorts = sorted((leg for leg in legs if leg["position"] == "short"), key=lambda leg: leg["id"])
        for short in shorts:
            long_leg = next((leg for leg in longs if leg["id"] not in consumed and leg["contracts"] == short["contracts"]
                             and _same_contract(leg, short)), None)
            if long_leg is None:
                continue
            consumed |= {long_leg["id"], short["id"]}
            kind = kind_of(short["option_type"], long_leg["strike"], short["strike"])
            credit = KINDS[kind]["style"] == "credit"
            primary = short if credit else long_leg
            open_net = net_premium(kind, long_leg["open_premium"], short["open_premium"])
            close_net = net_premium(kind, long_leg["close_premium"], short["close_premium"])
            pnl = round(long_leg["pnl"] + short["pnl"], 2)
            basis = abs(open_net) * 100 * short["contracts"]
            row = {**primary, "position": "short" if credit else "long",
                   "open_premium": round(open_net, 4), "close_premium": round(max(close_net, 0), 4),
                   "pnl": pnl, "pnl_pct": round(pnl / basis * 100, 2) if basis else 0,
                   "spread": {**describe({**long_leg, "premium": long_leg["open_premium"]},
                                         {**short, "premium": short["open_premium"]}),
                              "leg_ids": [short["id"], long_leg["id"]], "close_net": round(close_net, 4)}}
            if "fees" in long_leg or "fees" in short:
                row["fees"] = round((long_leg.get("fees") or 0) + (short.get("fees") or 0), 2)
            if "net_pnl" in long_leg or "net_pnl" in short:
                row["net_pnl"] = round((long_leg.get("net_pnl") if long_leg.get("net_pnl") is not None else long_leg["pnl"])
                                       + (short.get("net_pnl") if short.get("net_pnl") is not None else short["pnl"]), 2)
            row["is_manual"] = bool(long_leg.get("is_manual")) and bool(short.get("is_manual"))
            row["notes"] = primary.get("notes") or (long_leg if primary is short else short).get("notes")
            merged[primary["id"]] = row
    out = []
    for row in rows:
        if row["id"] in merged:
            out.append(merged[row["id"]])
        elif row["id"] not in consumed:
            out.append(row)
    return out
