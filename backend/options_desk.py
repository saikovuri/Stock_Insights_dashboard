"""Options position desk: daily actions for open option positions (take profit, tested, gamma, earnings,
early assignment before ex-dividend), earnings exposure, wheel ledger and an AI review of closed options."""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

import yfinance as yf

import llm
import options_analytics as oa
from cache import get_or_fetch
from database import get_closed_options, get_closed_trades, get_user_holdings, get_user_options
from stock_data import get_stock_data

log = logging.getLogger(__name__)

TAKE_PROFIT = 0.50
TESTED_DELTA = 0.40
GAMMA_DAYS = 7
_LEVEL = {"act": 0, "warn": 1, "info": 2}


def _d(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def next_dividend(ticker: str) -> dict | None:
    """Next ex-dividend date and amount: the announced date when Yahoo has it, else projected from history."""
    def _fetch():
        from portfolio_insights import _dividends
        divs = _dividends(ticker)
        if len(divs) < 2:
            return {"none": True}
        recent = divs[-5:]
        gap = (recent[-1][0] - recent[0][0]).days / max(len(recent) - 1, 1)
        if (date.today() - recent[-1][0]).days > gap * 2:
            return {"none": True}  # dividend suspended
        amount, est = recent[-1][1], recent[-1][0] + timedelta(days=round(gap))
        announced = False
        try:
            cal = yf.Ticker(ticker).calendar or {}
            ex = cal.get("Ex-Dividend Date") if isinstance(cal, dict) else None
            if ex and _d(ex) and _d(ex) >= date.today():
                est, announced = _d(ex), True
        except Exception:
            pass
        while est < date.today():
            est += timedelta(days=round(gap))
        return {"date": est.isoformat(), "amount": round(amount, 4), "announced": announced}
    try:
        r = get_or_fetch(f"next-div:{ticker}", _fetch, ttl=12 * 3600)
    except Exception as e:
        log.info("Dividend lookup failed for %s: %s", ticker, e)
        return None
    return None if r.get("none") else r


def _contract(ticker: str, kind: str, strike: float, expiry: str, S: float) -> dict:
    """Mid, IV and delta of the exact contract (empty if it isn't quoted)."""
    if expiry not in oa._expirations(ticker):
        return {}
    calls, puts = oa._chain(ticker, expiry)
    df = calls if kind == "call" else puts
    if df is None or df.empty:
        return {}
    m = df[df["strike"] == strike]
    if m.empty:
        return {}
    row = m.iloc[0]
    mid = oa._mid(row)
    if mid is None:
        return {}
    T = oa._years(expiry)
    iv = oa._row_iv(row, S, T, kind)
    delta = None
    if iv:
        d1, _ = oa._d1_d2(S, strike, T, iv)
        delta = oa._ncdf(d1) if kind == "call" else oa._ncdf(d1) - 1
    return {"mid": mid, "iv": iv, "delta": delta, "bid": float(row.get("bid") or 0), "ask": float(row.get("ask") or 0)}


def _actions(o: dict, S: float, c: dict, shares_held: float, earnings: dict, div: dict | None) -> list[dict]:
    kind, K, short = o["option_type"], o["strike"], o.get("position") == "short"
    dte = oa._dte(o["expiry"])
    intrinsic = max(S - K, 0) if kind == "call" else max(K - S, 0)
    itm = intrinsic > 0
    acts = []
    if dte < 0 or (dte == 0 and not oa._live(o["expiry"])):
        verb = ("was likely assigned" if itm else "expired worthless") if short else ("expired in the money — check if it was exercised" if itm else "expired worthless")
        return [{"level": "act", "code": "expired",
                 "text": f"Expired {o['expiry']}: {verb}. Close it out in the portfolio so P&L stays accurate."}]
    mid = c.get("mid")
    if short:
        if mid is not None and o["premium"] > 0:
            captured = (o["premium"] - mid) / o["premium"]
            if captured >= TAKE_PROFIT:
                acts.append({"level": "act", "code": "take_profit",
                             "text": f"{captured * 100:.0f}% of the max profit is in. Buy it back near ${mid:.2f} and "
                                     "re-sell further out — the last part of the premium carries most of the risk."})
        delta = abs(c["delta"]) if c.get("delta") is not None else None
        if itm or (delta is not None and delta >= TESTED_DELTA):
            acts.append({"level": "warn", "code": "tested",
                         "text": (f"In the money ({'above' if kind == 'call' else 'below'} the ${K:g} strike). " if itm else
                                  f"Delta {delta:.2f} — the strike is being tested. ")
                                 + f"Roll out and {'up' if kind == 'call' else 'down'} for a credit or close; see Repair.", "repair": True})
        if dte <= GAMMA_DAYS and not any(a["code"] == "take_profit" for a in acts):
            acts.append({"level": "warn" if (delta or 0) >= 0.25 or itm else "info", "code": "gamma",
                         "text": f"{dte} day{'s' if dte != 1 else ''} left: small moves now swing the price hard. "
                                 "Close or roll unless it's far out of the money."})
        if kind == "call":
            need = 100 * o["contracts"]
            if shares_held < need:
                acts.append({"level": "warn", "code": "naked",
                             "text": f"Only {shares_held:g} of the {need} shares needed to cover this call are recorded — "
                                     "an uncovered call has unlimited risk."})
            if div and o["expiry"] >= div["date"] >= date.today().isoformat() and itm and mid is not None:
                extrinsic = max(mid - intrinsic, 0)
                if extrinsic < div["amount"]:
                    day_before = (_d(div["date"]) - timedelta(days=1)).isoformat()
                    acts.append({"level": "act", "code": "ex_div",
                                 "text": f"Early assignment likely before the {div['date']} ex-dividend"
                                         f"{'' if div['announced'] else ' (est.)'}: time value ${extrinsic:.2f} is less "
                                         f"than the ${div['amount']:.2f} dividend. Roll or close by {day_before} if you "
                                         "want to keep the shares."})
        elif itm and mid is not None and max(mid - intrinsic, 0) < 0.05:
            acts.append({"level": "warn", "code": "early_put",
                         "text": "Almost no time value left: early assignment can happen any day. Roll now if you "
                                 "don't want the shares."})
    else:
        if mid is not None and o["premium"] > 0:
            gain = (mid - o["premium"]) / o["premium"]
            if gain >= 1:
                acts.append({"level": "act", "code": "take_profit",
                             "text": f"Up {gain * 100:.0f}%. Consider selling part to lock in the gain."})
            elif gain <= -0.5 and dte <= 21:
                acts.append({"level": "warn", "code": "decay",
                             "text": f"Down {abs(gain) * 100:.0f}% with {dte} days left; time decay speeds up from here. "
                                     "Decide whether the move can still come in time."})
    nxt = earnings.get("next")
    if nxt and date.today().isoformat() <= nxt <= o["expiry"]:
        acts.append({"level": "warn" if short else "info", "code": "earnings",
                     "text": f"Earnings {nxt}{'' if earnings.get('next_confirmed') else ' (est.)'} before expiry — "
                             + ("a gap can blow through the strike." if short else "implied volatility usually drops right after.")})
    return acts


def position_actions(user_id: int) -> dict:
    options = get_user_options(user_id)
    shares = defaultdict(float)
    for h in get_user_holdings(user_id):
        shares[h["ticker"]] += h["shares"]
    spots, earnings, divs, out = {}, {}, {}, []
    for o in options:
        t = o["ticker"]
        try:
            if t not in spots:
                spots[t] = oa._spot(t)
                earnings[t] = oa.earnings_info(t)
                divs[t] = next_dividend(t)
            S = spots[t]
            c = _contract(t, o["option_type"], o["strike"], o["expiry"], S)
        except Exception as e:
            log.info("Position check failed for %s: %s", t, e)
            continue
        acts = sorted(_actions(o, S, c, shares[t], earnings[t], divs[t]), key=lambda a: _LEVEL[a["level"]])
        mid = c.get("mid")
        short = o.get("position") == "short"
        out.append({
            "id": o["id"], "ticker": t, "type": o["option_type"], "position": o.get("position", "long"),
            "strike": o["strike"], "expiry": o["expiry"], "dte": oa._dte(o["expiry"]), "contracts": o["contracts"],
            "premium": o["premium"], "spot": round(S, 2), "mid": None if mid is None else round(mid, 2),
            "delta": None if c.get("delta") is None else round(c["delta"], 2),
            "iv_pct": None if not c.get("iv") else round(c["iv"] * 100, 1),
            "profit_captured_pct": round((o["premium"] - mid) / o["premium"] * 100) if short and mid is not None and o["premium"] else None,
            "pnl": None if mid is None else round(((o["premium"] - mid) if short else (mid - o["premium"])) * 100 * o["contracts"], 2),
            "next_dividend": divs[t], "actions": acts,
        })
    out.sort(key=lambda p: (min((_LEVEL[a["level"]] for a in p["actions"]), default=9), p["dte"]))
    return {"positions": out, "counts": {lvl: sum(1 for p in out for a in p["actions"] if a["level"] == lvl) for lvl in _LEVEL},
            "rules": {"take_profit_pct": int(TAKE_PROFIT * 100), "tested_delta": TESTED_DELTA, "gamma_days": GAMMA_DAYS}}


def earnings_exposure(user_id: int) -> dict:
    """Holdings and options with a report in the next 30 days, plus stocks that just reported."""
    shares, cost = defaultdict(float), defaultdict(float)
    for h in get_user_holdings(user_id):
        shares[h["ticker"]] += h["shares"]
        cost[h["ticker"]] += h["shares"] * h["buy_price"]
    opts = defaultdict(list)
    for o in get_user_options(user_id):
        opts[o["ticker"]].append(o)
    today = date.today()
    upcoming, recent = [], []
    for t in sorted(set(shares) | set(opts))[:40]:
        info = oa.earnings_info(t)
        nxt = info.get("next")
        days = (_d(nxt) - today).days if nxt else None
        if days is not None and 0 <= days <= 30:
            try:
                hist = oa._past_earnings_moves(t)
            except Exception:
                hist = []
            avg = sum(abs(m["move_pct"]) for m in hist) / len(hist) if hist else None
            try:
                S = oa._spot(t)
            except Exception:
                S = None
            spanning = [o for o in opts[t] if o["expiry"] >= nxt]
            upcoming.append({
                "ticker": t, "date": nxt, "days": days, "timing": info.get("next_timing"),
                "confirmed": info.get("next_confirmed"), "alt": info.get("next_alt"),
                "shares": round(shares[t], 4), "avg_move_pct": None if avg is None else round(avg, 1),
                "dollar_move": round(shares[t] * S * avg / 100, 2) if avg and S and shares[t] else None,
                "options": [{"id": o["id"], "type": o["option_type"], "position": o.get("position", "long"),
                             "strike": o["strike"], "expiry": o["expiry"], "contracts": o["contracts"]} for o in spanning],
            })
        ds = info.get("days_since_last")
        if ds is not None and ds <= 10:
            recent.append({"ticker": t, "date": info["last"], "days_ago": ds, "timing": info.get("last_timing"),
                           "shares": round(shares[t], 4), "has_options": bool(opts[t])})
    upcoming.sort(key=lambda r: r["days"])
    recent.sort(key=lambda r: r["days_ago"])
    return {"upcoming": upcoming, "recent": recent}


def wheel_ledger(user_id: int) -> dict:
    """Per-stock wheel results: option premium kept, stock P&L, adjusted cost basis, vs buy-and-hold."""
    opts, closed = get_user_options(user_id), get_closed_options(user_id)
    tickers = sorted({o["ticker"] for o in opts + closed if o.get("position") == "short"})
    lots = defaultdict(list)
    for h in get_user_holdings(user_id):
        lots[h["ticker"]].append(h)
    sold = defaultdict(list)
    for t in get_closed_trades(user_id):
        sold[t["ticker"]].append(t)
    rows = []
    for t in tickers[:30]:
        shorts_closed = [c for c in closed if c["ticker"] == t and c["position"] == "short"]
        shorts_open = [o for o in opts if o["ticker"] == t and o.get("position") == "short"]
        realized_opts = sum(c["pnl"] for c in shorts_closed)
        open_premium = sum(o["premium"] * 100 * o["contracts"] for o in shorts_open)
        sh = sum(h["shares"] for h in lots[t])
        stock_cost = sum(h["shares"] * h["buy_price"] for h in lots[t])
        realized_stock = sum(x["pnl"] for x in sold[t])
        try:
            S = oa._spot(t)
        except Exception:
            S = None
        unreal_stock = sh * S - stock_cost if S is not None and sh else 0.0
        dates = [d for d in ([_d(c.get("opened_at")) or _d(c.get("closed_at")) for c in shorts_closed]
                             + [_d(o.get("date_added")) for o in opts if o["ticker"] == t]
                             + [_d(h.get("date_added")) for h in lots[t]]) if d]
        start = min(dates) if dates else date.today()
        days = max((date.today() - start).days, 1)
        capital = max([stock_cost] + [o["strike"] * 100 * o["contracts"] for o in shorts_open if o["option_type"] == "put"]
                      + [c["strike"] * 100 * c["contracts"] for c in shorts_closed if c["option_type"] == "put"])
        total = realized_opts + open_premium + realized_stock + unreal_stock
        hold_pct = None
        try:
            closes = get_stock_data(t, period="2y", interval="1d")["Close"]
            then = closes[closes.index.date >= start]
            if len(then) and S:
                hold_pct = round((S / float(then.iloc[0]) - 1) * 100, 2)
        except Exception:
            pass
        rows.append({
            "ticker": t, "since": start.isoformat(), "days": days,
            "cycles": len(shorts_closed) + len(shorts_open), "open_shorts": len(shorts_open),
            "premium_kept": round(realized_opts, 2), "open_premium": round(open_premium, 2),
            "shares": round(sh, 4), "avg_cost": round(stock_cost / sh, 2) if sh else None,
            "adjusted_cost": round((stock_cost - realized_opts - open_premium) / sh, 2) if sh else None,
            "stock_pnl": round(realized_stock + unreal_stock, 2), "total_pnl": round(total, 2), "capital": round(capital, 2),
            "return_pct": round(total / capital * 100, 2) if capital else None,
            "annualized_pct": round(total / capital * 365 / days * 100, 1) if capital and days >= 14 else None,
            "buy_hold_pct": hold_pct,
        })
    rows.sort(key=lambda r: r["total_pnl"], reverse=True)
    return {"rows": rows, "total_pnl": round(sum(r["total_pnl"] for r in rows), 2),
            "note": "Counts every short option on the stock as part of the wheel. Open premium is counted as received; "
                    "buy-backs of open positions would reduce it. Capital is the largest cash-secured put or share cost."}


def _dte_bucket(c: dict) -> str:
    o, e = _d(c.get("opened_at")), _d(c.get("expiry"))
    if not o or not e:
        return "unknown"
    d = (e - o).days
    return "0DTE" if d <= 0 else "1–7 days" if d <= 7 else "8–30 days" if d <= 30 else "31–60 days" if d <= 60 else "60+ days"


def _group(rows, key):
    g = defaultdict(list)
    for r in rows:
        g[key(r)].append(r)
    out = [{"key": k, "trades": len(v), "win_rate": round(sum(1 for r in v if r["pnl"] > 0) / len(v) * 100),
            "pnl": round(sum(r["pnl"] for r in v), 2)} for k, v in g.items()]
    return sorted(out, key=lambda x: x["pnl"], reverse=True)


def options_review(user_id: int) -> dict:
    closed = get_closed_options(user_id)
    if not closed:
        return {"stats": None, "breakdowns": {}}
    wins = [c for c in closed if c["pnl"] > 0]
    losses = [c for c in closed if c["pnl"] <= 0]
    gross_loss = -sum(c["pnl"] for c in losses)
    stats = {
        "trades": len(closed), "win_rate": round(len(wins) / len(closed) * 100),
        "total_pnl": round(sum(c["pnl"] for c in closed), 2),
        "avg_win": round(sum(c["pnl"] for c in wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(c["pnl"] for c in losses) / len(losses), 2) if losses else None,
        "profit_factor": round(sum(c["pnl"] for c in wins) / gross_loss, 2) if gross_loss else None,
        "biggest_loss": round(min(c["pnl"] for c in closed), 2),
    }
    breakdowns = {
        "strategy": _group(closed, lambda c: f"{c['position']} {c['option_type']}"),
        "dte_at_open": _group(closed, _dte_bucket),
        "exit": _group(closed, lambda c: "held to expiry" if (c["close_premium"] or 0) == 0 else "closed early"),
        "ticker": _group(closed, lambda c: c["ticker"])[:8],
    }
    return {"stats": stats, "breakdowns": breakdowns}


def options_coach(user_id: int) -> dict:
    report = options_review(user_id)
    s = report["stats"]
    if not s or s["trades"] < 5:
        return {"ai": False, "summary": "Close at least 5 option trades to get a review.", "strengths": [], "leaks": [], "rules": []}
    if not llm.ai_enabled():
        return {"ai": False, "summary": "AI review needs an AI key on the server.", "strengths": [], "leaks": [], "rules": []}
    recent = [{k: c.get(k) for k in ("ticker", "position", "option_type", "strike", "expiry", "opened_at", "open_premium",
                                       "close_premium", "contracts", "pnl")} for c in get_closed_options(user_id)[:40]]
    system = ("You are an options trading coach. Base every observation on the statistics and trades given and quote the "
              "numbers. Be direct and practical. Output JSON only.")
    user = f"""Stats: {s}
Breakdowns (strategy, days to expiry when opened, held to expiry vs closed early, ticker): {report['breakdowns']}
Recent closed option trades: {recent}

Return JSON:
{{"summary": "2-3 sentence honest assessment",
 "strengths": ["1-3 things that work, with numbers"],
 "leaks": ["2-4 specific patterns costing money, with numbers (e.g. 0DTE losses, holding to expiry, one ticker)"],
 "rules": ["2-4 concrete rules to adopt"]}}"""
    raw = llm.chat_json(system, user, temperature=0.3, max_tokens=1600)

    def lst(k):
        v = raw.get(k)
        return [str(x).strip() for x in v if str(x).strip()][:4] if isinstance(v, list) else []
    return {"ai": True, "summary": str(raw.get("summary", "")), "strengths": lst("strengths"), "leaks": lst("leaks"),
            "rules": lst("rules"), "generated_at": datetime.now().date().isoformat()}
