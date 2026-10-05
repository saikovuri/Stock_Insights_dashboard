"""Track record of the option ideas the app shows: each idea is logged the first time it appears and
scored at expiry from the closing price, so the suggested deltas are judged on real outcomes."""

import logging
import threading
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from database import idea_log_rows, log_ideas, settle_idea, unsettled_ideas

log = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

KIND_LABELS = {
    "csp": "Cash-secured puts", "pcs": "Put credit spreads", "ic": "Iron condors",
    "wheel": "Wheel puts (scanner)", "long": "Long options", "spread": "Debit spreads",
}


def _leg(side: str, kind: str, strike: float) -> dict:
    return {"side": side, "type": kind, "strike": float(strike)}


def _row(kind, label, ticker, expiry, legs, net, risk, spot, delta) -> dict:
    return {"kind": kind, "label": label, "ticker": ticker, "expiry": expiry, "legs": legs,
            "legs_key": "|".join(f"{l['side'][0]}{l['type'][0]}{l['strike']:g}" for l in legs),
            "net": round(net, 4), "risk": None if risk is None else round(risk, 4), "spot": round(spot, 4),
            "delta": delta, "created_day": datetime.now(_ET).date().isoformat(),
            "cost_per_share": round(len(legs) * 0.04, 4),
            "cost_model": "v1: $1 commission/leg/side plus $0.01/share slippage/leg/side; 100-share contracts"}


def _save_async(rows: list[dict]) -> None:
    def run():
        try:
            log_ideas(rows)
        except Exception as e:
            log.info("Idea log failed: %s", e)
    if rows:
        threading.Thread(target=run, daemon=True).start()


def record_income(d: dict) -> None:
    t, exp, S = d["ticker"], d["expiry"], d["spot"]
    rows = []
    for i in d.get("cash_secured_puts", []):
        rows.append(_row("csp", i["label"], t, exp, [_leg("sell", "put", i["strike"])], i["mid"],
                         i["strike"] - i["mid"], S, i["delta"]))
    for i in d.get("put_credit_spreads", []):
        rows.append(_row("pcs", i["label"], t, exp, [_leg("sell", "put", i["short_strike"]), _leg("buy", "put", i["long_strike"])],
                         i["credit"], i["width"] - i["credit"], S, i["delta"]))
    for i in d.get("iron_condors", []):
        legs = [_leg("buy", "put", i["put_long"]), _leg("sell", "put", i["put_short"]),
                _leg("sell", "call", i["call_short"]), _leg("buy", "call", i["call_long"])]
        rows.append(_row("ic", i["label"], t, exp, legs, i["credit"], i["width"] - i["credit"], S, i["delta"]))
    _save_async(rows)


def record_wheel(rows: list[dict]) -> None:
    _save_async([_row("wheel", None, c["ticker"], c["expiry"], [_leg("sell", "put", c["strike"])],
                      c["premium"] / 100, c["strike"] - c["premium"] / 100, c["price"], c["delta"]) for c in rows])


def record_directional(d: dict) -> None:
    rows = []
    for i in d.get("ideas", []):
        if i["kind"] not in ("long", "spread"):
            continue
        legs = [_leg(l["action"].lower(), l["type"], l["strike"]) for l in i["legs"]]
        debit = sum(l["mid"] if l["action"] == "BUY" else -l["mid"] for l in i["legs"])
        if debit <= 0:
            continue
        label = f"{d['risk']} · {d['direction']}"
        rows.append(_row(i["kind"], label, d["ticker"], d["expiry"], legs, -debit, debit, d["spot"],
                         i["legs"][0].get("delta")))
    _save_async(rows)


def _payoff(legs: list[dict], S: float) -> float:
    """Value per share of the position at expiry (long legs +, short legs -)."""
    v = 0.0
    for l in legs:
        intrinsic = max(S - l["strike"], 0) if l["type"] == "call" else max(l["strike"] - S, 0)
        v += intrinsic if l["side"] == "buy" else -intrinsic
    return v


def settle() -> int:
    """Score every idea whose expiry has closed."""
    now = datetime.now(_ET)
    through = now.date() if (now.hour, now.minute) >= (16, 15) else now.date() - timedelta(days=1)
    pending = unsettled_ideas(through.isoformat())
    if not pending:
        return 0
    from stock_data import get_stock_data
    by_ticker = defaultdict(list)
    for r in pending:
        by_ticker[r["ticker"]].append(r)
    done = 0
    for t, rows in by_ticker.items():
        try:
            closes = get_stock_data(t, period="6mo", interval="1d")["Close"]
            closes.index = pd.to_datetime(closes.index.date)
        except Exception as e:
            log.info("Settle %s: no prices (%s)", t, e)
            continue
        for r in rows:
            on = closes[closes.index == pd.Timestamp(r["expiry"])]
            if not len(on) or not pd.notna(on.iloc[-1]) or on.iloc[-1] <= 0:
                continue
            S = float(on.iloc[-1])
            settle_idea(r["id"], round(S, 4), round(r["net"] + _payoff(r["legs"], S), 4))
            done += 1
    log.info("Settled %d ideas", done)
    return done


def summary() -> dict:
    rows = idea_log_rows()
    legacy_settled = [row for row in rows if row["pnl"] is not None and row.get("cost_per_share") is None]
    settled = [{**row, "gross_pnl": row["pnl"], "pnl": row["pnl"] - row["cost_per_share"]}
               for row in rows if row["pnl"] is not None and row.get("cost_per_share") is not None]
    groups = defaultdict(list)
    for r in settled:
        groups[(r["kind"], r["label"] if r["kind"] != "wheel" else None)].append(r)

    out = []
    for (kind, label), rs in groups.items():
        wins = [r for r in rs if r["pnl"] > 0]
        full = [r for r in rs if r["gross_pnl"] >= r["net"] - 1e-6] if rs[0]["net"] > 0 else []
        roi = [r["pnl"] / (r["risk"] + r["cost_per_share"]) for r in rs if r["risk"]]
        out.append({
            "kind": kind, "name": KIND_LABELS.get(kind, kind), "label": label, "ideas": len(rs),
            "win_rate": round(len(wins) / len(rs) * 100),
            "expired_worthless_pct": round(len(full) / len(rs) * 100) if rs[0]["net"] > 0 else None,
            "avg_return_on_risk_pct": round(sum(roi) / len(roi) * 100, 1) if roi else None,
            "avg_delta": round(sum(r["delta"] or 0 for r in rs) / len(rs), 2),
            "worst_pct": round(min(roi) * 100, 1) if roi else None,
            "avg_net_pnl_per_contract": round(sum(row["pnl"] for row in rs) / len(rs) * 100, 2),
        })
    order = list(KIND_LABELS)
    out.sort(key=lambda g: (order.index(g["kind"]) if g["kind"] in order else 99, str(g["label"])))
    today = date.today().isoformat()
    return {
        "groups": out, "settled": len(settled), "open": sum(row["pnl"] is None for row in rows),
        "legacy_uncosted": len(legacy_settled),
        "next_expiry": min((r["expiry"] for r in rows if r["pnl"] is None and r["expiry"] >= today), default=None),
        "since": min((r["created_day"] for r in rows), default=None),
        "note": "Hypothetical midpoint-entry paper ideas, not executed trades. New observations freeze a cost model of $1 "
            "commission per leg per side plus $0.01/share slippage per leg per side. Reported outcomes are net of these costs. "
            "Legacy observations without recorded costs are excluded. Outcomes require an exact expiry-date close; "
            "missing dates remain unsettled. Early assignment, intraday fills and management are not modeled. "
            "Repeated and correlated ideas are not independent observations; this is not evidence of a tradable edge.",
    }
