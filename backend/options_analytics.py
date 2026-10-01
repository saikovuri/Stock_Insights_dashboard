"""Options analytics: implied-vs-realized volatility, expected moves, and income ideas
(covered calls / cash-secured puts). Chains come from Yahoo, falling back to CBOE delayed
quotes; IV is solved from mid prices because Yahoo's own IV field is often stale outside
market hours."""

import logging
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import yfinance as yf

from cache import get_or_fetch
from database import record_iv, get_iv_history
from providers import cboe_chains, finnhub_earnings_calendar
from stock_data import get_quote, get_stock_data

log = logging.getLogger(__name__)

RISK_FREE = 0.04
MIN_IV_HISTORY = 20
_ET = ZoneInfo("America/New_York")


# ── Black-Scholes helpers ────────────────────────────────────────────────

def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _d1_d2(S, K, T, sigma, r=RISK_FREE):
    d1 = (math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * math.sqrt(T))
    return d1, d1 - sigma * math.sqrt(T)


def bs_price(S, K, T, sigma, kind, r=RISK_FREE):
    d1, d2 = _d1_d2(S, K, T, sigma, r)
    if kind == "call":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)


def implied_vol(price, S, K, T, kind, r=RISK_FREE) -> float | None:
    intrinsic = max(0.0, S - K) if kind == "call" else max(0.0, K - S)
    if price is None or price <= intrinsic or T <= 0:
        return None
    lo, hi = 0.01, 5.0
    if bs_price(S, K, T, hi, kind, r) < price:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if bs_price(S, K, T, mid, kind, r) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _mid(row) -> float | None:
    bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    last = float(row.get("lastPrice") or 0)
    return last if last > 0 else None


def _row_iv(row, S, T, kind) -> float | None:
    iv = implied_vol(_mid(row), S, float(row["strike"]), T, kind)
    if iv is None:
        y = float(row.get("impliedVolatility") or 0)
        iv = y if 0.03 < y < 5 else None
    return iv


# ── Chain access ─────────────────────────────────────────────────────────

def _expirations(ticker: str) -> list[str]:
    def _fetch():
        try:
            exps = list(yf.Ticker(ticker).options or [])
        except Exception as e:
            log.info("Yahoo expirations failed for %s: %s", ticker, e)
            exps = []
        # Yahoo often blocks cloud hosts; CBOE delayed quotes are the fallback
        exps = exps or list(cboe_chains(ticker))
        if not exps:
            raise LookupError(ticker)  # don't cache a transient miss for an hour
        return exps
    try:
        return get_or_fetch(f"opt-exp:{ticker}", _fetch, ttl=3600)
    except LookupError:
        return []


def _chain(ticker: str, expiry: str):
    def _fetch():
        try:
            c = yf.Ticker(ticker).option_chain(expiry)
            if not (c.calls.empty and c.puts.empty):
                return c.calls, c.puts
        except Exception as e:
            log.info("Yahoo chain failed for %s %s: %s", ticker, expiry, e)
        chain = cboe_chains(ticker).get(expiry)
        if chain is None:
            raise ValueError(f"No option chain for {ticker} {expiry}")
        return chain
    return get_or_fetch(f"opt-chain:{ticker}:{expiry}", _fetch, ttl=300)


def _dte(expiry: str) -> int:
    return (datetime.strptime(expiry, "%Y-%m-%d").date() - datetime.now(_ET).date()).days


def _close_at(expiry: str) -> datetime:
    return datetime.strptime(expiry, "%Y-%m-%d").replace(hour=16, tzinfo=_ET)


def _live(expiry: str) -> bool:
    """False once the expiry's 4pm ET close has passed (0DTE chains are dead after the bell)."""
    return datetime.now(_ET) < _close_at(expiry)


def _years(expiry: str) -> float:
    """Time to the expiry-day close in years; intraday-accurate so 0DTE pricing isn't overstated."""
    secs = (_close_at(expiry) - datetime.now(_ET)).total_seconds()
    return max(secs, 3600) / (365 * 86400)


def _pick_expiry(expirations: list[str], target: int, lo: int, hi: int) -> str | None:
    cands = [(abs(_dte(e) - target), e) for e in expirations if lo <= _dte(e) <= hi and _live(e)]
    return min(cands)[1] if cands else None


def _atm_iv(ticker: str, expiry: str, S: float) -> float | None:
    calls, puts = _chain(ticker, expiry)
    T = _years(expiry)
    ivs = []
    for df, kind in ((calls, "call"), (puts, "put")):
        if df is None or df.empty:
            continue
        row = df.loc[(df["strike"] - S).abs().idxmin()]
        iv = _row_iv(row, S, T, kind)
        if iv:
            ivs.append(iv)
    return sum(ivs) / len(ivs) if ivs else None


def _earnings_date(ticker: str) -> str | None:
    cal = finnhub_earnings_calendar(90, ticker)
    hit = next((e.get("date") for e in cal if e.get("symbol") == ticker and e.get("date")), None)
    if hit:
        return hit
    try:
        ed = (yf.Ticker(ticker).calendar or {}).get("Earnings Date")
        ed = ed[0] if isinstance(ed, list) and ed else ed
        return ed.strftime("%Y-%m-%d") if hasattr(ed, "strftime") else (str(ed)[:10] if ed else None)
    except Exception:
        return None


def _spot(ticker: str) -> float:
    q = get_quote(ticker)
    if not q.get("price"):
        raise ValueError("Spot price unavailable")
    return float(q["price"])


def _market_open() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    return now.weekday() < 5 and (9, 45) <= (now.hour, now.minute) <= (16, 0)


# ── Volatility overview ──────────────────────────────────────────────────

def volatility_overview(ticker: str) -> dict:
    def _fetch():
        S = _spot(ticker)
        exps = _expirations(ticker)
        if not exps:
            raise LookupError("No listed options")

        monthly = _pick_expiry(exps, 30, 20, 60) or _pick_expiry(exps, 30, 5, 120)
        weekly = _pick_expiry(exps, 7, 4, 12)
        iv30 = _atm_iv(ticker, monthly, S) if monthly else None

        closes = get_stock_data(ticker, period="1y", interval="1d")["Close"]
        log_ret = np.log(closes / closes.shift(1)).dropna()
        rolling = (log_ret.rolling(20).std() * math.sqrt(252)).dropna()
        rv20 = float(rolling.iloc[-1]) if len(rolling) else None

        # True IV rank needs our own daily snapshots; realized-vol range is the fallback
        iv_rank = iv_pct = None
        history = []
        if iv30:
            try:
                # After-hours quotes are stale, so only store snapshots while the market is open
                if _market_open():
                    record_iv(ticker, date.today().isoformat(), iv30)
                history = get_iv_history(ticker, (date.today() - timedelta(days=365)).isoformat())
            except Exception as e:
                log.info("IV history unavailable: %s", e)
        if len(history) >= MIN_IV_HISTORY:
            lo, hi = min(history), max(history)
            iv_rank = round((iv30 - lo) / (hi - lo) * 100) if hi > lo else 50
            iv_pct = round(sum(1 for h in history if h < iv30) / len(history) * 100)

        ratio = iv30 / rv20 if iv30 and rv20 else None
        if iv_rank is not None:
            level = "high" if iv_rank >= 60 else "low" if iv_rank <= 25 else "normal"
        elif ratio is not None:
            level = "high" if ratio >= 1.25 else "low" if ratio <= 0.9 else "normal"
        else:
            level = None

        moves = []
        for label, exp in (("This week", weekly), ("About a month", monthly)):
            if not exp or exp in [m["expiry"] for m in moves]:
                continue
            iv = iv30 if exp == monthly else _atm_iv(ticker, exp, S)
            if not iv:
                continue
            d = _dte(exp)
            move = S * iv * math.sqrt(max(d, 1) / 365)
            moves.append({"label": label, "expiry": exp, "dte": d, "move": round(move, 2),
                          "move_pct": round(move / S * 100, 1),
                          "low": round(S - move, 2), "high": round(S + move, 2)})

        earnings = _earnings_date(ticker)
        e_days = (datetime.strptime(earnings, "%Y-%m-%d").date() - date.today()).days if earnings else None
        earnings_in_window = e_days is not None and monthly is not None and 0 <= e_days <= _dte(monthly)

        return {
            "ticker": ticker,
            "spot": round(S, 2),
            "iv_pct": None if iv30 is None else round(iv30 * 100, 1),
            "rv_pct": None if rv20 is None else round(rv20 * 100, 1),
            "iv_rv_ratio": None if ratio is None else round(ratio, 2),
            "iv_rank": iv_rank,
            "iv_percentile": iv_pct,
            "iv_history_days": len(history),
            "iv_history_needed": MIN_IV_HISTORY,
            "level": level,
            "moves": moves,
            "earnings_date": earnings,
            "earnings_in_days": e_days,
            "earnings_in_window": earnings_in_window,
            "summary": _vol_summary(level, iv30, rv20, iv_rank, earnings_in_window, e_days),
        }

    return get_or_fetch(f"vol:{ticker}", _fetch, ttl=300)


def _vol_summary(level, iv, rv, iv_rank, earnings_in_window, e_days) -> str:
    if iv is None:
        return "Options data is unavailable right now."
    parts = []
    if iv_rank is not None:
        parts.append(f"Options are pricing {iv * 100:.0f}% yearly volatility — IV rank {iv_rank} "
                     f"(0 = cheapest of the past year, 100 = most expensive).")
    elif rv:
        cmp_ = "more" if iv > rv else "less"
        parts.append(f"Options are pricing {iv * 100:.0f}% yearly volatility, {cmp_} than the "
                     f"{rv * 100:.0f}% the stock has actually moved recently.")
    parts.append({
        "high": "Premium is expensive: better for selling options (covered calls, cash-secured puts, spreads) than buying them.",
        "low": "Premium is cheap: buying calls/puts is relatively inexpensive; selling pays less than usual.",
        "normal": "Premium is fairly priced — no strong edge for buyers or sellers.",
    }.get(level, ""))
    if earnings_in_window:
        parts.append(f"Earnings in {e_days} days — part of the premium is the market pricing an earnings jump.")
    return " ".join(p for p in parts if p)


# ── Income ideas: covered calls, cash-secured puts, credit spreads, condors ──

_TARGETS = [("Conservative", 0.10), ("Balanced", 0.16), ("Aggressive", 0.25)]
_CONDOR_TARGETS = [("Conservative", 0.08), ("Balanced", 0.12), ("Aggressive", 0.16)]
_WIDTHS = (0.5, 1, 2.5, 5, 10, 25, 50)
_MIN_OI = 100
_MAX_SPREAD_PCT = 25
_MIN_CREDIT_RATIO = 0.10  # spread credit vs width; below this you risk >9x what you can make


def _spread_width(S: float) -> float:
    """Standard wing width: the largest round size within ~2.5% of spot."""
    return max((w for w in _WIDTHS if w <= S * 0.025), default=_WIDTHS[0])


def _default_income_expiry(ticker: str, exps: list[str], earnings: str | None, S: float) -> str | None:
    """~35 DTE favouring liquid (usually monthly) expiries, and the last one before earnings when one fits,
    so the default never holds through a report."""
    if earnings:
        pre = [e for e in exps if e < earnings]
        for lo in (20, 10):
            pick, _ = _liquid_expiry(ticker, pre, 35, lo, 50, S)
            if pick:
                return pick
    return _liquid_expiry(ticker, exps, 35, 20, 50, S)[0]


def _add_checks(ideas: list[dict], kind: str, em_range, earnings_before: bool, dte: int) -> None:
    """Attach pass/fail safety checks and an overall grade to each idea."""
    for i in ideas:
        checks = [(i["liquidity"] != "thin",
                   f"Liquid (OI {i['open_interest']:,})" if i["liquidity"] != "thin"
                   else "Thin market — wide bid/ask, hard to exit at a fair price")]
        if em_range:
            if kind == "ic":
                out = i["put_short"] < em_range[0] and i["call_short"] > em_range[1]
            elif kind == "call":
                out = i["strike"] > em_range[1]
            else:
                out = i.get("short_strike", i.get("strike")) < em_range[0]
            checks.append((out, "Outside the expected move" if out
                           else "Inside the expected move — a normal move can test it"))
        if "width" in i:
            ratio = i["credit"] / i["width"]
            checks.append((ratio >= _MIN_CREDIT_RATIO,
                           f"Credit is {ratio * 100:.0f}% of the width" if ratio >= _MIN_CREDIT_RATIO else
                           f"Credit is only {ratio * 100:.0f}% of the width — risking ${i['max_loss']:,.0f} "
                           f"to make ${i['premium']:,.0f}"))
        if earnings_before:
            checks.append((False, "Earnings before expiry — overnight gap risk"))
        if dte <= 6:
            checks.append((False, "Expires within days — high gamma risk"))
        fails = sum(not ok for ok, _ in checks)
        i["checks"] = [{"ok": ok, "text": t} for ok, t in checks]
        i["safety"] = "safer" if fails == 0 else "caution" if fails == 1 else "risky"


def income_ideas(ticker: str, expiry: str | None = None) -> dict:
    def _fetch():
        S = _spot(ticker)
        exps = _expirations(ticker)
        choices = [e for e in exps if _dte(e) <= 75 and _live(e)]
        earnings = _earnings_date(ticker)
        exp = expiry if expiry in choices else _default_income_expiry(ticker, exps, earnings, S) or (choices[0] if choices else None)
        if not exp:
            raise LookupError("No suitable expirations")
        d = max(_dte(exp), 1)
        T = _years(exp)
        calls, puts = _chain(ticker, exp)

        e_days = (datetime.strptime(earnings, "%Y-%m-%d").date() - date.today()).days if earnings else None
        earnings_before = e_days is not None and 0 <= e_days <= d

        call_rows, put_rows = _otm_rows(calls, "call", S, T), _otm_rows(puts, "put", S, T)
        call_q, put_q = _quotes(calls), _quotes(puts)
        atm = _atm_iv(ticker, exp, S)
        em = S * atm * math.sqrt(T) if atm else None
        em_range = (S - em, S + em) if em else None

        fill = "Use a limit order near the mid price. Wide bid/ask spreads or low open interest mean worse fills."
        tips = {
            "cc": ["Only sell at a strike you'd be happy to sell your shares at. You keep the premium either way, "
                   "but give up gains above the strike.", fill],
            "csp": ["Only sell on a stock you want to own. If assigned, you buy 100 shares per contract at the strike "
                    "(your real cost is the strike minus the premium).", fill],
            "pcs": ["Needs no shares and far less cash than a cash-secured put: the most you can lose is the width "
                    "minus the credit.",
                    "Take profit at ~50% of the credit. If the stock breaks the short strike, roll down and out for a "
                    "credit (see Roll / repair below) or close — don't hold into expiry.", fill + " Enter both legs as one spread order."],
            "ic": ["Works best when IV is high and you expect no big move. Avoid holding through earnings — a gap "
                   "can blow through one side.",
                   "Manage at ~50% profit, or close the tested side if price reaches a short strike.",
                   fill + " Enter all four legs as one order."],
        }
        for k in ("cc", "csp"):
            tips[k].append("Take profit at ~50% of the premium and re-sell; if the strike is breached, roll out for a "
                           "credit (see Roll / repair below) rather than paying to escape.")

        ideas = {
            "covered_calls": _ideas(call_rows, "call", S, d),
            "cash_secured_puts": _ideas(put_rows, "put", S, d),
            "put_credit_spreads": _put_credit_spreads(put_rows, put_q, S, T, em_range),
            "iron_condors": _iron_condors(put_rows, put_q, call_rows, call_q, S, T, em_range),
        }
        for key, kind in (("covered_calls", "call"), ("cash_secured_puts", "put"),
                          ("put_credit_spreads", "put"), ("iron_condors", "ic")):
            _add_checks(ideas[key], kind, em_range, earnings_before, _dte(exp))

        return {
            "ticker": ticker, "spot": round(S, 2), "expiry": exp, "dte": _dte(exp),
            "expirations": [{"date": e, "dte": _dte(e)} for e in choices],
            "earnings_date": earnings, "earnings_before_expiry": earnings_before,
            "expected_move": None if not em else {"move": round(em, 2), "low": round(em_range[0], 2),
                                                  "high": round(em_range[1], 2)},
            **ideas,
            "tips": tips,
        }

    return get_or_fetch(f"income:{ticker}:{expiry or 'auto'}", _fetch, ttl=300)


def _otm_rows(df, kind: str, S: float, T: float, otm_only: bool = True) -> list[dict]:
    """Quoted strikes (OTM only by default) with model delta / probability ITM."""
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        K = float(r["strike"])
        if otm_only and ((kind == "call" and K <= S) or (kind == "put" and K >= S)):
            continue
        mid, bid = _mid(r), float(r.get("bid") or 0)
        if not mid or bid <= 0:
            continue
        iv = _row_iv(r, S, T, kind)
        if not iv:
            continue
        d1, d2 = _d1_d2(S, K, T, iv)
        rows.append({"strike": K, "mid": mid, "bid": bid, "ask": float(r.get("ask") or 0), "iv": iv,
                     "delta": abs(_ncdf(d1) if kind == "call" else _ncdf(d1) - 1),
                     "p_itm": _ncdf(d2) if kind == "call" else _ncdf(-d2),
                     "oi": int(r.get("openInterest") or 0)})
    return rows


def _quotes(df) -> dict[float, dict]:
    """Every strike with a live ask — long wings may have no bid."""
    out = {}
    if df is None or df.empty:
        return out
    for _, r in df.iterrows():
        bid, ask = float(r.get("bid") or 0), float(r.get("ask") or 0)
        if ask > 0:
            out[float(r["strike"])] = {"mid": (bid + ask) / 2 if bid > 0 else ask, "bid": bid, "ask": ask,
                                       "oi": int(r.get("openInterest") or 0)}
    return out


def _pick(rows: list[dict], target: float, used=()) -> dict | None:
    cands = [x for x in rows if x["strike"] not in used]
    # Liquid strikes first; thin ones only if nothing else trades
    liquid = [x for x in cands if x["oi"] >= _MIN_OI and (_spread_pct(x["bid"], x["ask"]) or 0) <= _MAX_SPREAD_PCT]
    cands = liquid or cands
    if not cands:
        return None
    near = [x for x in cands if abs(x["delta"] - target) <= 0.05]
    # Among similar deltas, favour the most liquid strike
    pick = max(near, key=lambda x: x["oi"]) if near else min(cands, key=lambda x: abs(x["delta"] - target))
    return pick if abs(pick["delta"] - target) <= 0.12 else None


def _spread_pct(bid: float, ask: float) -> float | None:
    return (ask - bid) / ((ask + bid) / 2) * 100 if ask > bid > 0 else None


def _liquidity(oi: int, spread_pct: float | None) -> str:
    s = spread_pct or 0
    return "good" if oi >= 500 and s <= 8 else "thin" if oi < 100 or s > 20 else "ok"


def _prob_above(S: float, X: float, T: float, iv: float) -> float:
    return 1.0 if X <= 0 else _ncdf(_d1_d2(S, X, T, iv)[1])


def _vertical(short: dict, quotes: dict, kind: str, S: float) -> dict | None:
    """Sell `short`, buy the listed strike closest to a standard width further OTM."""
    K = short["strike"]
    w = _spread_width(S)
    goal = K - w if kind == "put" else K + w
    wings = [k for k in quotes if (k < K if kind == "put" else k > K)]
    if not wings:
        return None
    L = min(wings, key=lambda k: abs(k - goal))
    long = quotes[L]
    width, credit = abs(K - L), short["mid"] - long["mid"]
    if credit <= 0 or credit >= width:
        return None
    worst_spread = max(_spread_pct(short["bid"], short["ask"]) or 0,
                       _spread_pct(long["bid"], long["ask"]) or (100 if long["bid"] <= 0 else 0))
    return {"short": K, "long": L, "width": width, "credit": credit,
            "natural": max(short["bid"] - long["ask"], 0), "oi": min(short["oi"], long["oi"]),
            "liquidity": _liquidity(min(short["oi"], long["oi"]), worst_spread)}


_LIQ_RANK = {"good": 0, "ok": 1, "thin": 2}


def _put_credit_spreads(rows, quotes, S, T, em_range) -> list[dict]:
    out, used = [], set()
    for label, target in _TARGETS:
        short = _pick(rows, target, used)
        v = short and _vertical(short, quotes, "put", S)
        if not v:
            continue
        used.add(short["strike"])
        credit, width = v["credit"], v["width"]
        be = short["strike"] - credit
        out.append({
            "label": label,
            "short_strike": v["short"], "long_strike": v["long"], "width": round(width, 2),
            "credit": round(credit, 2), "natural_credit": round(v["natural"], 2),
            "premium": round(credit * 100, 2), "max_loss": round((width - credit) * 100, 2),
            "return_on_risk_pct": round(credit / (width - credit) * 100, 1),
            "breakeven": round(be, 2), "breakeven_pct": round((S - be) / S * 100, 1),
            "prob_profit_pct": round(_prob_above(S, be, T, short["iv"]) * 100),
            "prob_max_profit_pct": round((1 - short["p_itm"]) * 100),
            "delta": round(short["delta"], 2), "otm_pct": round((S - v["short"]) / S * 100, 1),
            "outside_expected_move": None if not em_range else v["short"] < em_range[0],
            "open_interest": v["oi"], "liquidity": v["liquidity"],
        })
    return out


def _iron_condors(put_rows, put_q, call_rows, call_q, S, T, em_range) -> list[dict]:
    out, used_p, used_c = [], set(), set()
    for label, target in _CONDOR_TARGETS:
        ps, cs = _pick(put_rows, target, used_p), _pick(call_rows, target, used_c)
        pv = ps and _vertical(ps, put_q, "put", S)
        cv = cs and _vertical(cs, call_q, "call", S)
        if not (pv and cv):
            continue
        credit, width = pv["credit"] + cv["credit"], max(pv["width"], cv["width"])
        if credit >= width:
            continue
        used_p.add(ps["strike"])
        used_c.add(cs["strike"])
        lo, hi = ps["strike"] - credit, cs["strike"] + credit
        p_profit = _prob_above(S, lo, T, ps["iv"]) - _prob_above(S, hi, T, cs["iv"])
        p_max = _prob_above(S, ps["strike"], T, ps["iv"]) - _prob_above(S, cs["strike"], T, cs["iv"])
        out.append({
            "label": label,
            "put_long": pv["long"], "put_short": pv["short"], "call_short": cv["short"], "call_long": cv["long"],
            "width": round(width, 2),
            "credit": round(credit, 2), "natural_credit": round(pv["natural"] + cv["natural"], 2),
            "premium": round(credit * 100, 2), "max_loss": round((width - credit) * 100, 2),
            "return_on_risk_pct": round(credit / (width - credit) * 100, 1),
            "breakeven_low": round(lo, 2), "breakeven_high": round(hi, 2),
            "prob_profit_pct": round(max(p_profit, 0) * 100),
            "prob_max_profit_pct": round(max(p_max, 0) * 100),
            "delta": round((ps["delta"] + cs["delta"]) / 2, 2),
            "outside_expected_move": None if not em_range else (
                pv["short"] < em_range[0] and cv["short"] > em_range[1]),
            "open_interest": min(pv["oi"], cv["oi"]),
            "liquidity": max(pv["liquidity"], cv["liquidity"], key=_LIQ_RANK.get),
        })
    return out


def _ideas(rows: list[dict], kind: str, S: float, dte: int) -> list[dict]:
    out, used = [], set()
    for label, target in _TARGETS:
        p = _pick(rows, target, used)
        if not p:
            continue
        K, mid, bid, ask, iv, p_itm, oi, delta = (p[k] for k in ("strike", "mid", "bid", "ask", "iv", "p_itm", "oi", "delta"))
        used.add(K)
        premium = mid * 100
        spread_pct = _spread_pct(bid, ask)
        liquidity = _liquidity(oi, spread_pct)
        idea = {
            "label": label,
            "strike": K,
            "bid": round(bid, 2), "ask": round(ask, 2), "mid": round(mid, 2),
            "premium": round(premium, 2),
            "delta": round(delta, 2),
            "iv_pct": round(iv * 100, 1),
            "prob_assigned_pct": round(p_itm * 100),
            "otm_pct": round(abs(K - S) / S * 100, 1),
            "open_interest": oi,
            "spread_pct": None if spread_pct is None else round(spread_pct, 1),
            "liquidity": liquidity,
        }
        if kind == "call":
            ret = mid / S
            idea.update({
                "return_pct": round(ret * 100, 2),
                "annualized_pct": round(ret * 365 / dte * 100, 1),
                "if_called_pct": round((K - S + mid) / S * 100, 2),
                "downside_breakeven": round(S - mid, 2),
            })
        else:
            ret = mid / K
            idea.update({
                "capital_required": round(K * 100, 2),
                "return_pct": round(ret * 100, 2),
                "annualized_pct": round(ret * 365 / dte * 100, 1),
                "effective_buy_price": round(K - mid, 2),
                "discount_pct": round((S - (K - mid)) / S * 100, 1),
            })
        out.append(idea)
    return out


# ── Directional ideas: shares vs long option vs debit spread, sized to budget and risk ──

_RISK_PLANS = {
    # (min DTE, max DTE, target DTE), target delta of the bought option
    "extreme": {"label": "0DTE / this week", "dte": (0, 6, 0), "delta": 0.45},
    "high": {"label": "Near-dated (1–3 weeks)", "dte": (7, 21, 14), "delta": 0.40},
    "moderate": {"label": "30–45 days out", "dte": (28, 50, 38), "delta": 0.50},
    "low": {"label": "LEAPS (6+ months)", "dte": (180, 900, 365), "delta": 0.75},
}


def _near_delta(rows: list[dict], target: float, band: float = 0.08) -> dict | None:
    """Best strike near the target delta, scored on delta fit, open interest and bid/ask tightness.
    Tradable strikes win; the band widens before falling back to thin ones."""
    if not rows:
        return None
    for b, need_liquid in ((band, True), (band * 2, True), (band * 2, False)):
        pool = [r for r in rows if abs(r["delta"] - target) <= b and (not need_liquid or _tradable(r))]
        if pool:
            return max(pool, key=lambda r: _strike_score(r, target, b))
    return min(rows, key=lambda r: abs(r["delta"] - target))


def _tradable(r: dict) -> bool:
    sp = _spread_pct(r["bid"], r["ask"])
    return r["oi"] >= _MIN_OI and sp is not None and sp <= _MAX_SPREAD_PCT


def _oi_score(oi: int) -> float:
    return min(math.log10(oi + 1) / 4, 1.0)  # 0 at no OI, 1 at 10k+


def _strike_score(r: dict, target: float, band: float) -> float:
    sp = _spread_pct(r["bid"], r["ask"])
    return (1 - abs(r["delta"] - target) / band) + 0.6 * _oi_score(r["oi"]) - 0.6 * min((sp if sp is not None else 50) / 30, 1)


def _leg_spread(r: dict) -> float | None:
    sp = _spread_pct(r["bid"], r["ask"])
    return None if sp is None else round(sp, 1)


def _is_monthly(expiry: str) -> bool:
    d = datetime.strptime(expiry, "%Y-%m-%d").date()
    return d.weekday() == 4 and 15 <= d.day <= 21


def _expiry_oi(ticker: str, expiry: str, S: float) -> int:
    """Open interest across calls and puts within ±10% of spot — a proxy for how tradable the expiry is."""
    total = 0
    for df in _chain(ticker, expiry):
        if df is None or df.empty or "openInterest" not in df.columns:
            continue
        near = df[(df["strike"] >= S * 0.9) & (df["strike"] <= S * 1.1)]
        total += int(near["openInterest"].fillna(0).sum())
    return total


def _liquid_expiry(ticker: str, exps: list[str], target: int, lo: int, hi: int, S: float):
    """Expiry in [lo, hi] DTE balancing closeness to the target with open interest (monthlies usually win).
    Returns (expiry, note explaining a switch away from the nearest-to-target expiry)."""
    cands = sorted((e for e in exps if _live(e) and lo <= _dte(e) <= hi), key=lambda e: abs(_dte(e) - target))[:6]
    stats = []
    for e in cands:
        try:
            stats.append((e, _expiry_oi(ticker, e, S)))
        except Exception:
            continue
    if not stats:
        return None, None
    top = max(oi for _, oi in stats) or 1
    span = max(hi - lo, 1)

    def score(s):
        e, oi = s
        return math.log10(oi + 1) / math.log10(top + 1) - 0.5 * abs(_dte(e) - target) / span + (0.1 if _is_monthly(e) else 0)

    best, nearest = max(stats, key=score), stats[0]
    note = None
    if best[0] != nearest[0]:
        ratio = best[1] / max(nearest[1], 1)
        if ratio >= 1.5:
            note = (f"Picked {'the monthly' if _is_monthly(best[0]) else 'this'} expiry over {nearest[0]}: "
                    f"{ratio:.0f}× the open interest near the money, so tighter fills and easier exits.")
    return best[0], note


def _prob_profit(kind: str, S: float, be: float, T: float, iv: float) -> int:
    p = _prob_above(S, be, T, iv)
    return round((p if kind == "call" else 1 - p) * 100)


def _move_pct(kind: str, S: float, be: float) -> float:
    return round((be - S) / S * 100 if kind == "call" else (S - be) / S * 100, 1)


def _long_option(rows, kind, S, T, budget, target):
    """Returns (idea | None, cost of one contract at the target delta)."""
    ideal = _near_delta(rows, target)
    if not ideal:
        return None, None
    pick, stretched = ideal, False
    if ideal["mid"] * 100 > budget:
        afford = [r for r in rows if r["mid"] * 100 <= budget and r["delta"] >= 0.2]
        if not afford:
            return None, ideal["mid"] * 100
        pick = _near_delta(afford, max(r["delta"] for r in afford), band=0.05)
        stretched = True
    K, prem = pick["strike"], pick["mid"]
    n = int(budget // (prem * 100))
    be = K + prem if kind == "call" else K - prem
    cost = prem * 100 * n
    return {
        "kind": "long", "title": f"Long {kind}",
        "legs": [{"action": "BUY", "type": kind, "strike": K, "mid": round(prem, 2),
                  "oi": pick["oi"], "delta": round(pick["delta"], 2), "spread_pct": _leg_spread(pick)}],
        "qty": n, "unit": "contract", "cost": round(cost, 2), "max_loss": round(cost, 2),
        "max_profit": "Unlimited" if kind == "call" else round((K - prem) * 100 * n, 2),
        "breakeven": round(be, 2), "move_needed_pct": _move_pct(kind, S, be),
        "prob_profit_pct": _prob_profit(kind, S, be, T, pick["iv"]),
        "open_interest": pick["oi"], "liquidity": _liquidity(pick["oi"], _spread_pct(pick["bid"], pick["ask"])),
        "stretched": stretched,
        "notes": ("Further out-of-the-money than ideal to fit the budget — needs a bigger move. " if stretched else "")
                 + "Unlimited upside, but you pay all the time value: needs the move AND the timing."
                 if kind == "call" else
                 ("Further out-of-the-money than ideal to fit the budget. " if stretched else "")
                 + "Profits as the stock falls; loses value every day the drop doesn't come.",
    }, ideal["mid"] * 100


def _debit_spread(rows, kind, S, T, budget, target, em):
    """Buy near the target delta, sell near the expected move; narrow the width until it fits the budget.
    Returns (idea | None, cheapest one-lot cost seen)."""
    long = _near_delta(rows, target)
    if not long:
        return None, None
    sign = 1 if kind == "call" else -1
    reach = max(em or S * 0.05, _spread_width(S))
    goal = long["strike"] + sign * reach
    shorts = [r for r in rows if sign * (r["strike"] - long["strike"]) > 0 and r["bid"] > 0]
    shorts = [r for r in shorts if _tradable(r)] or shorts
    if not shorts:
        return None, None
    ideal = max(shorts, key=lambda r: 0.4 * _oi_score(r["oi"]) - abs(r["strike"] - goal) / reach)
    w_ideal = abs(ideal["strike"] - long["strike"])
    narrower = sorted((r for r in shorts if abs(r["strike"] - long["strike"]) < w_ideal),
                      key=lambda r: -abs(r["strike"] - long["strike"]))
    cheapest = None
    for s in [ideal] + narrower:
        width = abs(s["strike"] - long["strike"])
        debit = long["mid"] - s["mid"]
        if not 0 < debit < width:
            continue
        cheapest = debit * 100 if cheapest is None else min(cheapest, debit * 100)
        if debit * 100 > budget:
            continue
        n = int(budget // (debit * 100))
        be = long["strike"] + sign * debit
        oi = min(long["oi"], s["oi"])
        worst = max(_spread_pct(long["bid"], long["ask"]) or 0, _spread_pct(s["bid"], s["ask"]) or 0)
        label = "Bull call" if kind == "call" else "Bear put"
        return {
            "kind": "spread", "title": f"{label} debit spread",
            "legs": [{"action": "BUY", "type": kind, "strike": long["strike"], "mid": round(long["mid"], 2),
                      "oi": long["oi"], "delta": round(long["delta"], 2), "spread_pct": _leg_spread(long)},
                     {"action": "SELL", "type": kind, "strike": s["strike"], "mid": round(s["mid"], 2),
                      "oi": s["oi"], "delta": round(s["delta"], 2), "spread_pct": _leg_spread(s)}],
            "qty": n, "unit": "spread", "cost": round(debit * 100 * n, 2), "max_loss": round(debit * 100 * n, 2),
            "max_profit": round((width - debit) * 100 * n, 2),
            "reward_risk": round((width - debit) / debit, 2),
            "breakeven": round(be, 2), "move_needed_pct": _move_pct(kind, S, be),
            "prob_profit_pct": _prob_profit(kind, S, be, T, long["iv"]),
            "open_interest": oi, "liquidity": _liquidity(oi, worst),
            "narrowed": s is not ideal,
            "notes": ("Narrower than the expected-move target to fit the budget. " if s is not ideal else
                      "Short strike sits near the expected move. ")
                     + "Profit is capped at the short strike, but it costs far less and decays slower than a lone "
                       "option. Enter both legs as one order at a limit near the mid.",
        }, cheapest
    return None, cheapest


def _pick_best(ideas: dict, direction: str, risk: str, budget: float, S: float, iv_high: bool):
    shares, long, spread = ideas.get("shares"), ideas.get("long"), ideas.get("spread")
    if shares and direction == "bull" and budget >= 100 * S:
        return "shares", (f"Your budget buys {shares['qty']} shares — at least the 100 shares one option contract "
                          "controls — so owning the stock gives the same exposure with no expiry and no time decay.")
    if risk in ("high", "extreme"):
        if long and not long["stretched"] and not (iv_high and spread):
            return "long", ("Expires within days: the cheapest, most leveraged bet — it can double or go to zero "
                            "within hours, so size it as money you can lose." if risk == "extreme" else
                            "Most leverage for a quick move. Near-dated options lose value fast, so this can expire "
                            "worthless if the move doesn't come within days.")
        if spread:
            return "spread", ("Options are expensive right now; selling the higher strike pays for part of the premium."
                              if iv_high else
                              "A near-the-money option doesn't fit the budget; the spread keeps the bought strike near "
                              "the money for less money, instead of a far out-of-the-money lottery ticket.")
    if risk == "moderate" and spread:
        return "spread", ("Best value for a move over the next month or so: the sold strike pays for part of the "
                          "premium and time decay hurts much less than owning a lone option.")
    if risk == "low":
        if long and not long["stretched"]:
            return "long", (f"An in-the-money LEAPS moves about {round(long['legs'][0]['delta'] * 100)}% as much as the "
                            "stock for a fraction of the price, with many months for the idea to play out.")
        if shares:
            return "shares", ("LEAPS near the money are above your budget; a few shares is the lowest-risk way to "
                              "express the view — no expiry, no time decay.")
    for k in ("spread", "long", "shares"):
        if ideas.get(k):
            return k, "Closest fit for your budget."
    return None, None


def directional_ideas(ticker: str, direction: str, budget: float, risk: str) -> dict:
    def _fetch():
        S = _spot(ticker)
        exps = _expirations(ticker)
        if not exps:
            raise LookupError("No listed options")
        plan = _RISK_PLANS[risk]
        lo, hi, target_dte = plan["dte"]
        exp, exp_note = _liquid_expiry(ticker, exps, target_dte, lo, hi, S)
        if not exp and risk == "low":
            longest = max(exps, key=_dte)
            exp = longest if _dte(longest) >= 120 else None
        exp = exp or _pick_expiry(exps, target_dte, 0, 1000)
        if not exp:
            raise LookupError("No suitable expirations")
        d = _dte(exp)
        T = _years(exp)
        kind = "call" if direction == "bull" else "put"
        calls, puts = _chain(ticker, exp)
        rows = [r for r in _otm_rows(calls if kind == "call" else puts, kind, S, T, otm_only=False) if r["ask"] > 0]

        atm = _atm_iv(ticker, exp, S)
        em = S * atm * math.sqrt(T) if atm else None
        try:
            iv_level = volatility_overview(ticker).get("level")
        except Exception:
            iv_level = None
        earnings = _earnings_date(ticker)
        e_days = (datetime.strptime(earnings, "%Y-%m-%d").date() - date.today()).days if earnings else None

        ideas, needed = {}, []
        if direction == "bull":
            n = int(budget // S)
            if n >= 1:
                ideas["shares"] = {
                    "kind": "shares", "title": "Buy shares",
                    "legs": [{"action": "BUY", "type": "shares", "strike": None, "mid": round(S, 2)}],
                    "qty": n, "unit": "share", "cost": round(n * S, 2), "max_loss": round(n * S, 2),
                    "max_profit": "Unlimited", "breakeven": round(S, 2), "move_needed_pct": 0.0,
                    "prob_profit_pct": None, "open_interest": None, "liquidity": "good",
                    "notes": "No expiry and no time decay — you can wait out a dip. Use a stop below recent support "
                             "to cap the loss well below the full amount.",
                }
            else:
                needed.append(S)
        long, long_cost = _long_option(rows, kind, S, T, budget, plan["delta"])
        spread, spread_cost = _debit_spread(rows, kind, S, T, budget, plan["delta"], em)
        if long:
            ideas["long"] = long
        elif long_cost:
            needed.append(long_cost)
        if spread:
            ideas["spread"] = spread
        elif spread_cost:
            needed.append(spread_cost)

        args = (direction, risk, budget, S, iv_level == "high")
        best, why = _pick_best({k: v for k, v in ideas.items() if v["liquidity"] != "thin"}, *args)
        usual, usual_why = _pick_best(ideas, *args)
        if not best:
            best, why = usual, usual_why
        elif usual != best:
            why += " (The usual pick here trades too thinly to get a fair fill.)"
        ordered = sorted(ideas.values(), key=lambda i: i["kind"] != best)
        for i in ordered:
            i["best"] = i["kind"] == best

        return {
            "ticker": ticker, "spot": round(S, 2), "direction": direction, "risk": risk, "budget": budget,
            "timeframe": plan["label"], "expiry": exp, "dte": d, "expiry_note": exp_note,
            "monthly": _is_monthly(exp), "iv_level": iv_level,
            "expected_move": None if not em else {"move": round(em, 2), "pct": round(em / S * 100, 1),
                                                  "low": round(S - em, 2), "high": round(S + em, 2)},
            "earnings_date": earnings, "earnings_before_expiry": e_days is not None and 0 <= e_days <= d,
            "ideas": ordered, "best_why": why,
            "min_budget_needed": round(min(needed), 2) if not ordered and needed else None,
        }

    return get_or_fetch(f"directional:{ticker}:{direction}:{risk}:{int(budget)}", _fetch, ttl=180)


# ── Roll / repair a tested short option position ────────────────────────────

_ROLL_RULES = [
    "Roll when the short strike is breached or its delta passes ~0.50 — ideally with 2–3 weeks left, not on expiry day.",
    "Only roll for a net credit. Paying to roll just adds risk; if no credit roll exists, close or accept assignment.",
    "Avoid rolling into an earnings date unless you accept the gap risk.",
    "Two or three rolls is the limit. If the stock keeps running against you, the thesis is broken — take the loss.",
]


def _roll_candidate(r, wing, K, width, close_mid, credit, kind, e, cur_dte, earnings):
    sign = 1 if kind == "call" else -1
    K2 = r["strike"]
    new_credit = r["mid"] - (wing["mid"] if wing else 0)
    if new_credit <= 0:
        return None
    net = new_credit - close_mid
    if net < 0:
        return None
    oi = min(r["oi"], wing["oi"]) if wing else r["oi"]
    worst = max(_spread_pct(r["bid"], r["ask"]) or 0,
                (_spread_pct(wing["bid"], wing["ask"]) or (100 if wing["bid"] <= 0 else 0)) if wing else 0)
    total = (credit or 0) + net  # premium collected across the original trade and this roll
    d2 = _dte(e)
    cand = {
        "expiry": e, "dte": d2, "added_days": d2 - cur_dte,
        "short_strike": K2, "long_strike": None if width is None else K2 - width,
        "strike_change": round(sign * (K2 - K), 2) + 0.0,  # + 0.0 turns -0.0 into 0.0
        "new_credit": round(new_credit * 100, 2), "net_credit": round(net * 100, 2),
        "delta": round(r["delta"], 2), "prob_otm_pct": round((1 - r["p_itm"]) * 100),
        "open_interest": oi, "liquidity": _liquidity(oi, worst),
        "spans_earnings": bool(earnings and date.today().isoformat() <= earnings <= e),
    }
    if credit is not None:
        if kind == "call":
            cand["outcome"] = f"If called: sell at ${K2:g} + ${total:.2f} total premium = ${K2 + total:.2f}/share"
        elif width is None:
            cand["outcome"] = f"If assigned: buy at ${K2:g} − ${total:.2f} total premium = ${K2 - total:.2f}/share"
        else:
            cand["outcome"] = (f"Breakeven ${K2 - total:.2f} · max loss ${max(width - total, 0) * 100:,.0f}"
                               f" (was ${max(width - credit, 0) * 100:,.0f})")
    return cand


def roll_ideas(ticker: str, strategy: str, expiry: str, short_strike: float,
               long_strike: float | None = None, credit: float | None = None) -> dict:
    def _fetch():
        S = _spot(ticker)
        exps = [e for e in _expirations(ticker) if _live(e)]
        if expiry not in exps:
            raise ValueError("That expiry isn't listed for this ticker, or has already expired.")
        kind = "call" if strategy == "cc" else "put"
        sign = 1 if kind == "call" else -1  # direction that moves the short strike away from the stock
        calls, puts = _chain(ticker, expiry)
        df = calls if kind == "call" else puts
        q = _quotes(df)
        K = float(short_strike)
        short = q.get(K)
        if not short:
            raise ValueError(f"No quote for the ${K:g} {kind} expiring {expiry}.")
        long = width = None
        if strategy == "pcs":
            if long_strike is None or float(long_strike) >= K:
                raise ValueError("A put credit spread needs a long strike below the short strike.")
            long = q.get(float(long_strike))
            if not long:
                raise ValueError(f"No quote for the ${float(long_strike):g} put expiring {expiry}.")
            width = K - float(long_strike)

        close_mid = short["mid"] - (long["mid"] if long else 0)
        close_nat = short["ask"] - (long["bid"] if long else 0)
        rows = {r["strike"]: r for r in _otm_rows(df, kind, S, _years(expiry), otm_only=False)}
        delta = rows.get(K, {}).get("delta")
        cur_dte = _dte(expiry)
        itm = S > K if kind == "call" else S < K
        tested = itm or (delta or 0) >= 0.4
        status = {
            "itm": itm, "tested": tested, "dte": cur_dte,
            "cushion_pct": round(sign * (K - S) / S * 100, 1),
            "delta": None if delta is None else round(delta, 2),
            "close_cost": round(close_mid * 100, 2), "close_cost_natural": round(max(close_nat, 0) * 100, 2),
            "pnl": None if credit is None else round((credit - close_mid) * 100, 2),
        }

        earnings = _earnings_date(ticker)
        later = [e for e in exps if cur_dte < _dte(e) <= cur_dte + 63 and _dte(e) >= 7][:10]

        def rank(x):  # prefer liquid, then the biggest strike improvement, then the most credit
            return x["liquidity"] != "thin", x["strike_change"], x["net_credit"]

        rolls = []
        for e in later:
            try:
                c2, p2 = _chain(ticker, e)
            except Exception:
                continue
            df2 = c2 if kind == "call" else p2
            q2 = _quotes(df2)
            same = furthest = None
            for r in _otm_rows(df2, kind, S, _years(e), otm_only=False):
                gain = sign * (r["strike"] - K)
                if gain < 0 or gain > S * 0.2:
                    continue
                wing = None
                if width is not None:
                    wing = q2.get(r["strike"] - width)
                    if not wing:
                        continue
                c = _roll_candidate(r, wing, K, width, close_mid, credit, kind, e, cur_dte, earnings)
                if not c:
                    continue
                if gain == 0:
                    same = c
                if not furthest or rank(c) > rank(furthest):
                    furthest = c
            for c in (same, furthest):
                if c and not any(x["expiry"] == c["expiry"] and x["short_strike"] == c["short_strike"] for x in rolls):
                    c["type"] = "out" if c["strike_change"] == 0 else "improve"
                    rolls.append(c)

        safe = [r for r in rolls if not r["spans_earnings"] and r["liquidity"] != "thin" and r["added_days"] <= 45]
        best = tested and max(safe or rolls, key=lambda r: (r["strike_change"], -r["added_days"], r["net_credit"]),
                              default=None)
        for r in rolls:
            r["best"] = r is best
        rolls.sort(key=lambda r: (not r["best"], r["dte"], -r["strike_change"]))

        alt = []
        cost = status["close_cost"]
        if strategy == "cc":
            alt.append({"title": "Let the shares be called away",
                        "text": f"You sell at ${K:g}" + (f" plus ${credit:.2f} premium (${K + credit:.2f}/share)" if credit else "")
                                + " — a fine outcome if you'd be happy selling there."})
            alt.append({"title": "Buy the call back", "text": f"Costs about ${cost:,.0f} per contract and keeps the shares uncapped."})
        elif strategy == "csp":
            alt.append({"title": "Take assignment and run the wheel",
                        "text": f"Buy 100 shares at ${K:g}" + (f" (net ${K - credit:.2f} after premium)" if credit else "")
                                + ", then sell covered calls at or above that price to lower your cost further."})
            alt.append({"title": "Close it", "text": f"Buy the put back for about ${cost:,.0f} per contract."})
        else:
            if credit is not None:
                alt.append({"title": "Close now",
                            "text": f"Costs about ${cost:,.0f}: a {'loss' if cost > credit * 100 else 'gain'} of "
                                    f"${abs(cost - credit * 100):,.0f} vs a max loss of ${max(width - credit, 0) * 100:,.0f} at expiry."})
            else:
                alt.append({"title": "Close now", "text": f"Costs about ${cost:,.0f} per spread."})
            if S < float(long_strike):
                alt.append({"title": "Both strikes are in the money",
                            "text": "The spread is near max loss, so a credit roll is unlikely. Close it rather than "
                                    "risk early assignment on the short put."})

        verdict = (None if tested else
                   "Not in trouble yet — the short strike still has cushion. No need to roll; consider taking profit "
                   "at ~50% of the credit.")
        if tested and not rolls:
            verdict = "No roll pays a net credit within the next ~2 months. Consider closing or accepting assignment."
        return {
            "ticker": ticker, "spot": round(S, 2), "strategy": strategy, "expiry": expiry,
            "short_strike": K, "long_strike": long_strike, "width": width, "earnings_date": earnings,
            "status": status, "verdict": verdict, "rolls": rolls[:8], "alternatives": alt, "rules": _ROLL_RULES,
        }

    key = f"roll:{ticker}:{strategy}:{expiry}:{short_strike}:{long_strike}:{credit}"
    return get_or_fetch(key, _fetch, ttl=120)
