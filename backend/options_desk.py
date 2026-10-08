"""Options position desk: daily actions for open option positions (take profit, tested, gamma, earnings,
early assignment before ex-dividend), earnings exposure, wheel ledger and an AI review of closed options."""

import logging
import math
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
STOP_MULTIPLE = 2.0  # close a short option once the loss reaches 2x the credit received
PIN_PCT = 1.0  # expiry-day distance from the strike that counts as pinned
ROLL_LIMIT = 3
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
    bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
    if not all(math.isfinite(value) for value in (bid, ask)) or bid <= 0 or ask < bid:
        return {}
    mid = (bid + ask) / 2
    T = oa._years(expiry)
    iv = oa._row_iv(row, S, T, kind)
    delta = None
    if iv:
        d1, _ = oa._d1_d2(S, strike, T, iv)
        delta = oa._ncdf(d1) if kind == "call" else oa._ncdf(d1) - 1
    return {"mid": mid, "iv": iv, "delta": delta, "bid": bid, "ask": ask}


def _roll_counts(user_id: int, options: list[dict]) -> dict[int, int]:
    """Rolls behind each open short option: a bought-back short of the same ticker, type and account closed within a
    day of when this one (and then each predecessor) was opened."""
    import database
    rows = database._run(f"SELECT ticker, option_type, position, close_premium, opened_at, closed_at, account "
                         f"FROM closed_options WHERE user_id={database.PH}", (user_id,), "all")
    closes = [r for r in rows if r["position"] == "short" and (r["close_premium"] or 0) > 0]
    account = lambda row: row.get("account") or database.DEFAULT_ACCOUNT  # noqa: E731
    counts = {}
    for o in options:
        if o.get("position") != "short":
            continue
        n, opened, used = 0, _d(o.get("date_added")), set()
        while opened and n < 20:
            match = next((i for i, r in enumerate(closes) if i not in used and r["ticker"] == o["ticker"]
                          and r["option_type"] == o["option_type"] and account(r) == account(o)
                          and _d(r["closed_at"]) and abs((_d(r["closed_at"]) - opened).days) <= 1), None)
            if match is None:
                break
            used.add(match)
            n += 1
            opened = _d(closes[match].get("opened_at"))
        counts[o["id"]] = n
    return counts


def _actions(o: dict, S: float, c: dict, shares_held: float, earnings: dict, div: dict | None, rolls: int = 0) -> list[dict]:
    kind, K, short = o["option_type"], o["strike"], o.get("position") == "short"
    dte = oa._dte(o["expiry"])
    intrinsic = max(S - K, 0) if kind == "call" else max(K - S, 0)
    itm = intrinsic > 0
    acts = []
    if dte < 0 or (dte == 0 and not oa._live(o["expiry"])):
        verb = ("was likely assigned" if itm else "expired worthless") if short else ("expired in the money — check if it was exercised" if itm else "expired worthless")
        return [{"level": "act", "code": "expired", "assign": short and itm,
                 "text": f"Expired {o['expiry']}: {verb}. "
                         + ("Mark it assigned to move the shares into your holdings." if short and itm else
                            "Close it out in the portfolio so P&L stays accurate.")}]
    mid = c.get("mid")
    if short:
        if dte == 0 and K and abs(S - K) / K * 100 <= PIN_PCT:
            acts.append({"level": "act", "code": "pin_risk",
                         "text": f"Expires today within {abs(S - K) / K * 100:.1f}% of the ${K:g} strike. Close before 4 PM ET: "
                                 "after-hours moves until about 5:30 PM can still decide assignment, leaving surprise "
                                 + ("shares" if kind == "put" else "a short stock position (or lost shares)") + " on Monday."})
        if mid is not None and o["premium"] > 0 and (mid - o["premium"]) / o["premium"] >= STOP_MULTIPLE:
            multiple = (mid - o["premium"]) / o["premium"]
            acts.append({"level": "act", "code": "stop_loss",
                         "text": f"Loss is {multiple:.1f}× the ${o['premium']:.2f} credit (mark ${mid:.2f}). A common rule closes "
                                 f"short options at a {STOP_MULTIPLE:g}× credit loss so one bad trade can't erase many good ones. "
                                 "Rolling only for a credit does not reduce this risk.", "repair": True})
        if rolls >= ROLL_LIMIT - 1:
            acts.append({"level": "warn" if rolls >= ROLL_LIMIT else "info", "code": "roll_count",
                         "text": f"Rolled {rolls} time{'s' if rolls != 1 else ''} already. A common limit is 2–3 rolls: if the "
                                 "stock keeps moving against you, the original idea is broken — compare closing or "
                                 "taking assignment before rolling again."})
        if mid is not None and o["premium"] > 0:
            captured = (o["premium"] - mid) / o["premium"]
            if captured >= TAKE_PROFIT:
                acts.append({"level": "act", "code": "take_profit",
                             "text": f"{captured * 100:.0f}% of premium is captured. Consider closing near ${mid:.2f} and "
                                     "re-sell further out — the last part of the premium carries most of the risk."})
        delta = abs(c["delta"]) if c.get("delta") is not None else None
        if itm or (delta is not None and delta >= TESTED_DELTA):
            acts.append({"level": "warn", "code": "tested",
                         "text": (f"In the money ({'above' if kind == 'call' else 'below'} the ${K:g} strike). " if itm else
                                  f"Delta {delta:.2f} — the strike is being tested. ")
                                 + "Compare closing, holding through assignment, and rolling after costs. A credit alone does not reduce risk.", "repair": True})
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
    try:
        rolls = _roll_counts(user_id, options)
    except Exception as e:
        log.info("Roll count failed for user %s: %s", user_id, e)
        rolls = {}
    shares = defaultdict(float)
    for h in get_user_holdings(user_id):
        shares[h["ticker"]] += h["shares"]
    spots, earnings, divs, out = {}, {}, {}, []
    for o in options:
        t = o["ticker"]
        coverage = min(shares[t], 100 * o["contracts"])
        if o.get("position") == "short" and o["option_type"] == "call":
            shares[t] -= coverage
        S, c, acts = None, {}, []
        try:
            if t not in spots:
                spots[t] = oa._spot(t)
                earnings[t] = oa.earnings_info(t)
                divs[t] = next_dividend(t)
            S = spots[t]
            if not S or not math.isfinite(S):
                raise ValueError("Underlying quote unavailable")
            c = _contract(t, o["option_type"], o["strike"], o["expiry"], S)
            acts = _actions(o, S, c, coverage, earnings[t], divs[t], rolls.get(o["id"], 0))
        except Exception as e:
            log.info("Position check failed for %s: %s", t, e)
            S = None
        if not c:
            acts.append({"level": "warn", "code": "unavailable", "text": "Quote unavailable: risk and P&L are incomplete. Verify this position with your broker."})
        if S is None and o.get("position") == "short" and o["option_type"] == "call" and coverage < 100 * o["contracts"]:
            acts.append({"level": "warn", "code": "naked", "text": "Insufficient unallocated shares to cover this call."})
        if not earnings.get(t, {}).get("next"):
            acts.append({"level": "warn", "code": "earnings_unknown", "text": "Next earnings date unknown; event risk has not been cleared."})
        acts.sort(key=lambda a: _LEVEL[a["level"]])
        mid = c.get("mid")
        short = o.get("position") == "short"
        out.append({
            "id": o["id"], "ticker": t, "type": o["option_type"], "position": o.get("position", "long"),
            "strike": o["strike"], "expiry": o["expiry"], "dte": oa._dte(o["expiry"]), "contracts": o["contracts"],
            "premium": o["premium"], "spot": round(S, 2) if S is not None else None, "mid": None if mid is None else round(mid, 2),
            "bid": c.get("bid"), "ask": c.get("ask"), "rolls": rolls.get(o["id"], 0),
            "loss_multiple": round((mid - o["premium"]) / o["premium"], 2) if short and mid is not None and o["premium"] else None,
            "delta": None if c.get("delta") is None else round(c["delta"], 2),
            "iv_pct": None if not c.get("iv") else round(c["iv"] * 100, 1),
            "profit_captured_pct": round((o["premium"] - mid) / o["premium"] * 100) if short and mid is not None and o["premium"] else None,
            "pnl": None if mid is None else round(((o["premium"] - mid) if short else (mid - o["premium"])) * 100 * o["contracts"], 2),
            "next_dividend": divs.get(t), "actions": acts,
        })
    out.sort(key=lambda p: (min((_LEVEL[a["level"]] for a in p["actions"]), default=9), p["dte"]))
    return {"positions": out, "counts": {lvl: sum(1 for p in out for a in p["actions"] if a["level"] == lvl) for lvl in _LEVEL},
            "rules": {"take_profit_pct": int(TAKE_PROFIT * 100), "tested_delta": TESTED_DELTA, "gamma_days": GAMMA_DAYS,
                      "stop_multiple": STOP_MULTIPLE, "pin_pct": PIN_PCT, "roll_limit": ROLL_LIMIT}}


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
    unavailable = []
    for t in sorted(set(shares) | set(opts)):
        try:
            info = oa.earnings_info(t)
        except Exception:
            unavailable.append(t)
            continue
        if not info.get("next"):
            unavailable.append(t)
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
    return {"upcoming": upcoming, "recent": recent, "unavailable": unavailable}


def _legs_key(o: dict) -> tuple:
    return o["ticker"], o["option_type"], o["expiry"]


def _spread_longs(opts: list[dict], closed: list[dict]) -> tuple[list[dict], list[dict]]:
    """Long options sharing ticker, type and expiry with a short one: the protective legs of credit spreads."""
    keys = {_legs_key(o) for o in opts + closed if o.get("position") == "short"}
    return ([o for o in opts if o.get("position") == "long" and _legs_key(o) in keys],
            [c for c in closed if c.get("position") == "long" and _legs_key(c) in keys])


def _put_capital(short: dict, longs: list[dict], remaining=None) -> float:
    """Gross put collateral, allocating each protective contract at most once."""
    if remaining is None:
        remaining = {index: leg["contracts"] for index, leg in enumerate(longs)}
    needed, capital = short["contracts"], 0.0
    wings = sorted(enumerate(longs), key=lambda item: item[1]["strike"], reverse=True)
    for index, leg in wings:
        if _legs_key(leg) != _legs_key(short) or leg["strike"] >= short["strike"]:
            continue
        matched = min(needed, remaining[index])
        capital += matched * (short["strike"] - leg["strike"]) * 100
        needed -= matched
        remaining[index] -= matched
    return capital + needed * short["strike"] * 100


def capital_requirements(options: list[dict], holdings: list[dict]) -> dict:
    longs = [option for option in options if option.get("position") == "long"]
    remaining = {index: leg["contracts"] for index, leg in enumerate(longs)}
    shares = defaultdict(float)
    for holding in holdings:
        shares[holding["ticker"]] += holding["shares"]
    reserved, uncovered = 0.0, 0
    by_ticker = defaultdict(float)
    for option in sorted(options, key=lambda item: (item["ticker"], item["expiry"], -item["strike"])):
        if option.get("position") != "short":
            continue
        if option["option_type"] == "put":
            capital = _put_capital(option, longs, remaining)
            reserved += capital
            by_ticker[option["ticker"]] += capital
        else:
            covered = min(option["contracts"], int(shares[option["ticker"]] // 100))
            shares[option["ticker"]] -= covered * 100
            needed = option["contracts"] - covered
            for index, leg in enumerate(longs):
                if _legs_key(leg) != _legs_key(option):
                    continue
                matched = min(needed, remaining[index])
                capital = matched * max(leg["strike"] - option["strike"], 0) * 100
                reserved += capital
                by_ticker[option["ticker"]] += capital
                remaining[index] -= matched
                needed -= matched
            uncovered += needed
    return {"reserved_cash": round(reserved, 2), "uncovered_calls": uncovered, "by_ticker": dict(by_ticker)}


def wheel_ledger(user_id: int) -> dict:
    """Per-stock wheel results: option premium kept, stock P&L, adjusted cost basis, vs buy-and-hold."""
    opts, closed = get_user_options(user_id), get_closed_options(user_id)
    holdings = get_user_holdings(user_id)
    closed_stocks = get_closed_trades(user_id)
    tickers = sorted({o["ticker"] for o in opts + closed + holdings + closed_stocks})
    requirements = capital_requirements(opts, holdings)
    lots = defaultdict(list)
    for h in holdings:
        lots[h["ticker"]].append(h)
    sold = defaultdict(list)
    for t in closed_stocks:
        sold[t["ticker"]].append(t)
    rows = []
    for t in tickers:
        shorts_closed = [c for c in closed if c["ticker"] == t and c["position"] == "short"]
        shorts_open = [o for o in opts if o["ticker"] == t and o.get("position") == "short"]
        wings_open = [o for o in opts if o["ticker"] == t and o.get("position") == "long"]
        wings_closed = [c for c in closed if c["ticker"] == t and c.get("position") == "long"]
        realized_opts = sum(c.get("net_pnl", c["pnl"]) for c in shorts_closed + wings_closed)
        open_premium = (sum(o["premium"] * 100 * o["contracts"] for o in shorts_open)
                        - sum(o["premium"] * 100 * o["contracts"] for o in wings_open))
        sh = sum(h["shares"] for h in lots[t])
        stock_cost = sum(h["shares"] * h["buy_price"] for h in lots[t])
        realized_stock = sum(x["pnl"] for x in sold[t])
        try:
            S = oa._spot(t)
        except Exception:
            S = None
        if S is not None and (not math.isfinite(S) or S <= 0):
            S = None
        unreal_stock = sh * S - stock_cost if S is not None and sh else 0.0
        unreal_opts, missing = 0.0, bool(sh and S is None)
        for option in shorts_open + wings_open:
            try:
                contract = _contract(t, option["option_type"], option["strike"], option["expiry"], S) if S else {}
                if contract.get("mid") is None:
                    missing = True
                    continue
                direction = -1 if option["position"] == "short" else 1
                unreal_opts += direction * (contract["mid"] - option["premium"]) * 100 * option["contracts"]
            except Exception:
                missing = True
        dates = [d for d in ([_d(c.get("opened_at")) or _d(c.get("closed_at")) for c in shorts_closed]
                             + [_d(o.get("date_added")) for o in opts if o["ticker"] == t]
                             + [_d(h.get("date_added")) for h in lots[t]]) if d]
        start = min(dates) if dates else date.today()
        days = max((date.today() - start).days, 1)
        capital = stock_cost + requirements["by_ticker"].get(t, 0)
        total = None if missing else realized_opts + unreal_opts + realized_stock + unreal_stock
        rows.append({
            "ticker": t, "since": start.isoformat(), "days": days,
            "cycles": len(shorts_closed) + len(shorts_open), "open_shorts": len(shorts_open),
            "premium_kept": round(realized_opts, 2), "open_premium": round(open_premium, 2),
            "shares": round(sh, 4), "avg_cost": round(stock_cost / sh, 2) if sh else None,
            "adjusted_cost": None,
            "stock_pnl": round(realized_stock + unreal_stock, 2) if not (sh and S is None) else None,
            "unrealized_options": round(unreal_opts, 2) if not missing else None,
            "total_pnl": round(total, 2) if total is not None else None, "capital": round(capital, 2),
            "return_pct": None, "annualized_pct": None, "incomplete": missing,
            "buy_hold_pct": None,
        })
    rows.sort(key=lambda row: row["total_pnl"] if row["total_pnl"] is not None else -math.inf, reverse=True)
    incomplete = any(row["incomplete"] for row in rows)
    return {
        "rows": rows,
        "total_pnl": None if incomplete else round(sum(row["total_pnl"] for row in rows), 2),
        "incomplete": incomplete,
        "capital_requirements": requirements,
        "note": "Combined stock and option P&L by ticker, not linked wheel cycles. Closed options include recorded fees. Open options are marked at "
                "two-sided quote midpoints, not realized income or executable fills. Missing marks suppress totals. "
                "Capital is current stock cost plus gross option collateral, not historical capital or broker margin. "
                "Returns and adjusted tax basis are omitted because cash flows and strategy links are not recorded.",
    }


def premium_income(user_id: int, months: int = 12) -> dict:
    """Premium collected and paid back per month, realized option P&L per month, and progress to a monthly goal."""
    from database import kv_get
    opts, closed = get_user_options(user_id), get_closed_options(user_id)
    m = defaultdict(lambda: {"collected": 0.0, "paid": 0.0, "realized": 0.0, "trades": 0})
    key = lambda d: d.strftime("%Y-%m") if d else None
    for o in opts:
        k = key(_d(o.get("date_added")))
        if not k:
            continue
        amt = o["premium"] * 100 * o["contracts"]
        if o.get("position") == "short":
            m[k]["collected"] += amt
            m[k]["trades"] += 1
        else:
            m[k]["paid"] += amt
    for c in closed:
        n = c["contracts"] * 100
        opened, done = key(_d(c.get("opened_at")) or _d(c.get("closed_at"))), key(_d(c.get("closed_at")))
        if c["position"] == "short":
            m[opened]["collected"] += c["open_premium"] * n
            m[opened]["trades"] += 1
            m[done]["paid"] += (c["close_premium"] or 0) * n
        else:
            m[opened]["paid"] += c["open_premium"] * n
            m[done]["collected"] += (c["close_premium"] or 0) * n
        m[done]["realized"] += c.get("net_pnl", c["pnl"])
    today = date.today()
    first = today.replace(day=1)
    keys = []
    for i in range(months - 1, -1, -1):
        y, mo = first.year, first.month - i
        while mo <= 0:
            y, mo = y - 1, mo + 12
        keys.append(f"{y}-{mo:02d}")
    rows = [{"month": k, **{f: round(v, 2) if isinstance(v, float) else v for f, v in m[k].items()},
             "net": round(m[k]["collected"] - m[k]["paid"], 2)} for k in keys]
    ytd = [r for r in rows if r["month"].startswith(str(today.year))]
    goal = kv_get(f"income-goal:{user_id}")
    goal = goal["data"] if goal else None
    this = rows[-1]
    return {
        "months": rows, "goal": goal, "this_month": this,
        "goal_pct": round(this["realized"] / goal * 100) if goal else None,
        "ytd_net": round(sum(r["net"] for r in ytd), 2), "ytd_realized": round(sum(r["realized"] for r in ytd), 2),
        "avg_net_3m": round(sum(r["net"] for r in rows[-4:-1]) / 3, 2),
        "note": "Collected = premium received when you sell (counted in the month you opened). Paid = buy-backs and "
                "all purchased options. Premium cash flow excludes fees; realized P&L includes recorded fees for trades closed that month. Cash flow is not profit. Trades closed before open dates were "
                "recorded are counted in their close month.",
    }


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
    closed = [{**trade, "pnl": trade.get("net_pnl", trade["pnl"])} for trade in get_closed_options(user_id)]
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
        "exit": _group(closed, lambda c: "zero-price close (reason unrecorded)" if (c["close_premium"] or 0) == 0 else "priced close"),
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
                                       "close_premium", "contracts", "pnl", "fees", "net_pnl")} for c in get_closed_options(user_id)[:40]]
    system = ("You are an options trading coach. Base every observation on the statistics and trades given and quote the "
              "numbers. Be direct and practical. Output JSON only.")
    user = f"""Stats and breakdowns use net P&L after recorded fees. Recent trades include gross pnl and net_pnl.
Stats: {s}
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
