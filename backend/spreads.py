"""Multi-leg option structures. Each leg is a normal option row; the legs share a spread_id.

A leg is {position: long|short, option_type: call|put, strike, expiry, ratio, premium}. Supported structures:
verticals (bull/bear, call/put), iron condors and iron butterflies, 1-2-1 butterflies (broken wings allowed),
and calendars/diagonals (sell a nearer expiry, buy a later one). Payoff limits come from the value at expiry, which is
piecewise linear between strikes, so every structure is measured the same way.
"""
from collections import defaultdict
from math import gcd

KINDS = {
    "bull_call": {"label": "Bull call", "family": "vertical", "style": "debit"},
    "bear_put": {"label": "Bear put", "family": "vertical", "style": "debit"},
    "bull_put": {"label": "Bull put", "family": "vertical", "style": "credit"},
    "bear_call": {"label": "Bear call", "family": "vertical", "style": "credit"},
    "iron_condor": {"label": "Iron condor", "family": "iron", "style": "credit"},
    "iron_butterfly": {"label": "Iron butterfly", "family": "iron", "style": "credit"},
    "call_butterfly": {"label": "Call butterfly", "family": "butterfly", "style": None},
    "put_butterfly": {"label": "Put butterfly", "family": "butterfly", "style": None},
    "call_calendar": {"label": "Call calendar", "family": "calendar", "style": "debit"},
    "put_calendar": {"label": "Put calendar", "family": "calendar", "style": "debit"},
    "call_diagonal": {"label": "Call diagonal", "family": "calendar", "style": "debit"},
    "put_diagonal": {"label": "Put diagonal", "family": "calendar", "style": "debit"},
}
SUPPORTED = ("Supported: verticals, iron condors and iron butterflies, 1-2-1 butterflies, and calendars or diagonals "
             "that sell the nearer expiry and buy the later one.")
VERTICALS = {k for k, v in KINDS.items() if v["family"] == "vertical"}


def _sign(leg: dict) -> int:
    return 1 if leg["position"] == "long" else -1


def _intrinsic(leg: dict, price: float) -> float:
    return max(price - leg["strike"], 0) if leg["option_type"] == "call" else max(leg["strike"] - price, 0)


def _exp(leg: dict) -> str:
    return str(leg["expiry"])[:10]


def kind_of(option_type: str, long_strike: float, short_strike: float) -> str:
    """The vertical spread that buys long_strike and sells short_strike."""
    return f"{'bull' if long_strike < short_strike else 'bear'}_{option_type}"


def classify(legs: list[dict]) -> str:
    """Name the structure, or raise ValueError when the legs aren't one of the supported structures."""
    if not 2 <= len(legs) <= 4:
        raise ValueError("A structure needs 2 to 4 legs. " + SUPPORTED)
    for leg in legs:
        if leg["position"] not in ("long", "short") or leg["option_type"] not in ("call", "put"):
            raise ValueError("Each leg must be a long or short call or put")
        if int(leg.get("ratio") or 0) < 1 or leg["strike"] <= 0:
            raise ValueError("Each leg needs a positive strike and quantity")
    keys = {(leg["position"], leg["option_type"], float(leg["strike"]), _exp(leg)) for leg in legs}
    if len(keys) != len(legs):
        raise ValueError("Two legs are the same contract; combine them into one leg")
    ratio = [int(leg["ratio"]) for leg in legs]
    expiries = {_exp(leg) for leg in legs}
    types = {leg["option_type"] for leg in legs}
    if len(legs) == 2:
        long_leg = next((leg for leg in legs if leg["position"] == "long"), None)
        short_leg = next((leg for leg in legs if leg["position"] == "short"), None)
        if long_leg is None or short_leg is None or len(types) != 1 or ratio[0] != ratio[1]:
            raise ValueError("A two-leg structure buys one option and sells another of the same type, one for one. " + SUPPORTED)
        kind = long_leg["option_type"]
        if len(expiries) == 1:
            if long_leg["strike"] == short_leg["strike"]:
                raise ValueError("A vertical spread needs two different strikes")
            return kind_of(kind, long_leg["strike"], short_leg["strike"])
        if _exp(long_leg) < _exp(short_leg):
            raise ValueError("A calendar or diagonal sells the nearer expiry and buys the later one")
        return f"{kind}_{'calendar' if long_leg['strike'] == short_leg['strike'] else 'diagonal'}"
    if len(expiries) != 1:
        raise ValueError("Butterflies and iron condors use one expiry for every leg. " + SUPPORTED)
    ordered = sorted(legs, key=lambda leg: (leg["strike"], leg["option_type"] == "call"))
    if len(legs) == 3:
        low, mid, high = ordered
        if (len(types) == 1 and low["position"] == high["position"] == "long" and mid["position"] == "short"
                and low["strike"] < mid["strike"] < high["strike"]
                and int(low["ratio"]) == int(high["ratio"]) and int(mid["ratio"]) == 2 * int(low["ratio"])):
            return f"{mid['option_type']}_butterfly"
        raise ValueError("A butterfly buys one low strike, sells two middle strikes and buys one high strike. " + SUPPORTED)
    puts = sorted((leg for leg in legs if leg["option_type"] == "put"), key=lambda leg: leg["strike"])
    calls = sorted((leg for leg in legs if leg["option_type"] == "call"), key=lambda leg: leg["strike"])
    if (len(puts) == 2 and len(calls) == 2 and len(set(ratio)) == 1
            and [puts[0]["position"], puts[1]["position"], calls[0]["position"], calls[1]["position"]] == ["long", "short", "short", "long"]
            and puts[0]["strike"] < puts[1]["strike"] <= calls[0]["strike"] < calls[1]["strike"]):
        return "iron_butterfly" if puts[1]["strike"] == calls[0]["strike"] else "iron_condor"
    raise ValueError("Four legs must form an iron condor: buy a low put, sell a higher put, sell a call at or above "
                     "it and buy a higher call. " + SUPPORTED)


def _units(legs: list[dict]) -> tuple[int, list[int]]:
    """Common number of structures and each leg's ratio, from the contract counts."""
    counts = [int(leg["contracts"]) for leg in legs]
    units = 0
    for count in counts:
        units = gcd(units, count)
    return units, [count // units for count in counts] if units else counts


def _points(legs: list[dict]) -> list[float]:
    strikes = sorted({float(leg["strike"]) for leg in legs})
    return [0.0, *strikes, strikes[-1] * 2 + 1]


def _strikes_label(legs: list[dict]) -> str:
    if len({_exp(leg) for leg in legs}) == 1:
        return "/".join(f"${strike:g}" for strike in sorted({float(leg["strike"]) for leg in legs}))
    near, far = sorted(legs, key=_exp)
    return f"${near['strike']:g} {_exp(near)} / ${far['strike']:g} {_exp(far)}"


def describe(legs: list[dict], units: int = 1) -> dict:
    """Net debit/credit, payoff limits, breakevens and gross collateral for `units` of the structure.
    Premiums are per share; each leg's ratio is per structure. Calendars and diagonals are measured at the near expiry
    with the later leg worth at least its intrinsic value: the max loss is a bound, the max profit depends on volatility."""
    kind = classify(legs)
    meta = KINDS[kind]
    net = sum(_sign(leg) * int(leg["ratio"]) * float(leg["premium"]) for leg in legs)
    style = "debit" if net > 0 else "credit"
    multi = len({_exp(leg) for leg in legs}) > 1

    def intrinsic(price):
        return sum(_sign(leg) * int(leg["ratio"]) * _intrinsic(leg, price) for leg in legs)

    points = _points(legs)
    values = [intrinsic(p) - net for p in points]
    scale = 100 * units
    info = {"kind": kind, "label": meta["label"], "family": meta["family"], "style": style,
            "net_open": round(abs(net), 4), "strikes": _strikes_label(legs), "multi_expiry": multi,
            "max_loss": round(max(-min(values), 0) * scale, 2),
            "max_profit": None if multi else round(max(values) * scale, 2),
            "collateral": round(max(-min(intrinsic(p) for p in points), 0) * scale, 2),
            "breakevens": [], "breakeven": None,
            "legs": [{k: leg.get(k) for k in ("id", "position", "option_type", "strike", "expiry", "ratio", "premium")}
                     for leg in legs]}
    if not multi:
        for (p0, v0), (p1, v1) in zip(zip(points, values), zip(points[1:], values[1:])):
            if v0 == 0 and p0 > 0:
                info["breakevens"].append(round(p0, 4))
            elif v0 * v1 < 0:
                info["breakevens"].append(round(p0 + (p1 - p0) * (-v0) / (v1 - v0), 4))
        info["breakeven"] = info["breakevens"][0] if len(info["breakevens"]) == 1 else None
    if meta["family"] == "vertical":
        long_leg = next(leg for leg in legs if leg["position"] == "long")
        short_leg = next(leg for leg in legs if leg["position"] == "short")
        info.update(long_strike=long_leg["strike"], short_strike=short_leg["strike"],
                    width=round(abs(long_leg["strike"] - short_leg["strike"]), 4))
    return info


def validate_open(legs: list[dict], units: int = 1, expect_kind: str | None = None) -> dict:
    """describe() plus the checks for opening at the given fills: the expected structure, the right debit/credit and
    a trade that can both make and lose money."""
    info = describe(legs, units)
    if expect_kind and expect_kind != info["kind"]:
        wanted = KINDS.get(expect_kind, {}).get("label", expect_kind)
        raise ValueError(f"These strikes make a {info['label'].lower()}, not a {wanted.lower()}; check which strike each leg uses")
    expected = KINDS[info["kind"]]["style"]
    if info["net_open"] == 0:
        raise ValueError("The fills net to zero; check the prices")
    if expected and info["style"] != expected:
        raise ValueError(f"A {info['label'].lower()} is opened for a {expected}; check which legs you bought and sold and their prices")
    if info["max_loss"] <= 0:
        raise ValueError("At these prices the trade can't lose money; check the fills")
    if info["max_profit"] is not None and info["max_profit"] <= 0:
        raise ValueError(f"At these prices the most it can make is ${info['max_profit']:,.2f}; check the fills")
    return info


def net_value(legs: list[dict], prices: dict) -> float:
    """Per-share value of one structure at the given prices per leg id: what selling it would bring (debit structures)
    or buying it back would cost (credit structures)."""
    raw = sum(_sign(leg) * int(leg["ratio"]) * prices[leg["id"]] for leg in legs)
    style = "debit" if sum(_sign(leg) * int(leg["ratio"]) * leg["premium"] for leg in legs) > 0 else "credit"
    return raw if style == "debit" else -raw


def _with_ratio(rows: list[dict]) -> list[dict]:
    """Open rows carry spread_ratio; legacy two-leg rows (before ratios were stored) count as 1."""
    return [{**row, "ratio": int(row.get("spread_ratio") or 1)} for row in rows]


def group_open(options: list[dict]) -> dict[str, list[dict]]:
    """spread_id -> legs (with 'ratio') for intact structures. A structure is intact while it has every leg it was
    opened with, each at its ratio times the same number of units, in one account and of a supported shape."""
    groups = defaultdict(list)
    for option in options:
        if option.get("spread_id"):
            groups[option["spread_id"]].append(option)
    intact = {}
    for spread_id, rows in groups.items():
        legs = sorted(_with_ratio(rows), key=lambda leg: leg["id"])
        expected = int(legs[0].get("spread_legs") or 2)
        if len(legs) != expected or len({(leg.get("account") or "") for leg in legs}) != 1 or len({leg["ticker"] for leg in legs}) != 1:
            continue
        units = legs[0]["contracts"] / legs[0]["ratio"]
        if units != int(units) or units < 1 or any(leg["contracts"] != units * leg["ratio"] for leg in legs):
            continue
        try:
            classify(legs)
        except ValueError:
            continue
        intact[spread_id] = legs
    return intact


def broken_legs(options: list[dict]) -> dict[int, str]:
    """Option id -> label of the structure it was opened in, for legs whose structure is no longer intact."""
    intact = {leg["id"] for legs in group_open(options).values() for leg in legs}
    return {o["id"]: KINDS.get(o.get("spread_kind") or "", {}).get("label", "spread")
            for o in options if o.get("spread_id") and o["id"] not in intact}


def units_of(legs: list[dict]) -> int:
    return int(legs[0]["contracts"] // legs[0]["ratio"])


def describe_open(legs: list[dict]) -> dict:
    return describe(legs, units_of(legs))


def merge_closed(rows: list[dict]) -> list[dict]:
    """Show each closed structure as one trade. Closed legs sharing a spread_id are matched by contract: the k-th close
    of every leg forms the k-th trade (closing a structure closes every leg, so partial closes line up), and the set is
    merged only when it forms a supported structure. Credit structures read as a short position and debit ones as a long
    position with net premiums, so captured %, win rate and reviews count it once. Unmatched legs stay as they are."""
    by_spread = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.get("spread_id"):
            key = (row["position"], row["option_type"], float(row["strike"]), _exp(row))
            by_spread[row["spread_id"]][key].append(row)
    merged, consumed = {}, set()
    for buckets in by_spread.values():
        if len(buckets) < 2:
            continue
        for bucket in buckets.values():
            bucket.sort(key=lambda row: row["id"])
        for k in range(min(len(bucket) for bucket in buckets.values())):
            group = sorted((bucket[k] for bucket in buckets.values()), key=lambda row: row["id"])
            if len({(row.get("account") or "") for row in group}) != 1:
                break
            units, ratios = _units(group)
            opened = [{**row, "ratio": r, "premium": row["open_premium"]} for row, r in zip(group, ratios)]
            try:
                info = describe(opened, units)
            except ValueError:
                break
            credit = info["style"] == "credit"
            primary = next(row for row in group if row["position"] == ("short" if credit else "long"))
            close_raw = sum(_sign(row) * r * row["close_premium"] for row, r in zip(group, ratios))
            close_net = -close_raw if credit else close_raw
            pnl = round(sum(row["pnl"] for row in group), 2)
            basis = info["net_open"] * 100 * units
            row = {**primary, "position": "short" if credit else "long", "contracts": units,
                   "open_premium": info["net_open"], "close_premium": round(max(close_net, 0), 4),
                   "pnl": pnl, "pnl_pct": round(pnl / basis * 100, 2) if basis else 0,
                   "expiry": min(_exp(r) for r in group),
                   "spread": {**info, "leg_ids": [r["id"] for r in group], "close_net": round(close_net, 4),
                              "legs": [{**leg, "id": r["id"], "close_premium": r["close_premium"]}
                                       for leg, r in zip(info["legs"], group)]}}
            if any("fees" in r for r in group):
                row["fees"] = round(sum(r.get("fees") or 0 for r in group), 2)
            if any("net_pnl" in r for r in group):
                row["net_pnl"] = round(sum(r["net_pnl"] if r.get("net_pnl") is not None else r["pnl"] for r in group), 2)
            row["is_manual"] = all(bool(r.get("is_manual")) for r in group)
            row["notes"] = primary.get("notes") or next((r.get("notes") for r in group if r.get("notes")), None)
            merged[primary["id"]] = row
            consumed |= {r["id"] for r in group}
    out = []
    for row in rows:
        if row["id"] in merged:
            out.append(merged[row["id"]])
        elif row["id"] not in consumed:
            out.append(row)
    return out


def suggest_links(options: list[dict]) -> list[dict]:
    """Unlinked (or orphaned) open legs that look like one structure: iron condors first, then verticals and calendars.
    Each option is suggested at most once; nothing is linked until the user confirms."""
    intact = {leg["id"] for legs in group_open(options).values() for leg in legs}
    free = sorted((o for o in options if o["id"] not in intact), key=lambda o: o["id"])
    groups = defaultdict(list)
    for o in free:
        groups[(o["ticker"], o.get("account") or "")].append(o)
    out = []

    def attempt(legs):
        units, ratios = _units(legs)
        try:
            info = describe([{**leg, "ratio": r} for leg, r in zip(legs, ratios)], units)
        except (ValueError, KeyError):
            return None
        return {"option_ids": [leg["id"] for leg in legs], "ticker": legs[0]["ticker"], "kind": info["kind"],
                "label": info["label"], "strikes": info["strikes"], "contracts": units}

    for legs in groups.values():
        used = set()
        by_expiry = defaultdict(list)
        for o in legs:
            by_expiry[_exp(o)].append(o)
        for same in by_expiry.values():
            puts = [o for o in same if o["option_type"] == "put"]
            calls = [o for o in same if o["option_type"] == "call"]
            for sp in (o for o in puts if o["position"] == "short"):
                for lp in (o for o in puts if o["position"] == "long" and o["strike"] < sp["strike"]):
                    for sc in (o for o in calls if o["position"] == "short" and o["strike"] >= sp["strike"]):
                        for lc in (o for o in calls if o["position"] == "long" and o["strike"] > sc["strike"]):
                            quad = [lp, sp, sc, lc]
                            if used & {o["id"] for o in quad} or len({o["contracts"] for o in quad}) != 1:
                                continue
                            found = attempt(quad)
                            if found:
                                out.append(found)
                                used |= {o["id"] for o in quad}
        for first in legs:
            for second in legs:
                if (first["id"] in used or second["id"] in used or first["position"] != "short" or second["position"] != "long"
                        or first["option_type"] != second["option_type"] or first["contracts"] != second["contracts"]):
                    continue
                found = attempt([first, second])
                if found:
                    out.append(found)
                    used |= {first["id"], second["id"]}
    return out
