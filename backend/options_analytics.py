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
    return (datetime.strptime(expiry, "%Y-%m-%d").date() - date.today()).days


def _pick_expiry(expirations: list[str], target: int, lo: int, hi: int) -> str | None:
    cands = [(abs(_dte(e) - target), e) for e in expirations if lo <= _dte(e) <= hi]
    return min(cands)[1] if cands else None


def _atm_iv(ticker: str, expiry: str, S: float) -> float | None:
    calls, puts = _chain(ticker, expiry)
    T = max(_dte(expiry), 1) / 365
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

_TARGETS = [("Conservative", 0.15), ("Balanced", 0.25), ("Aggressive", 0.35)]
_CONDOR_TARGETS = [("Conservative", 0.10), ("Balanced", 0.16), ("Aggressive", 0.25)]
_WIDTHS = (0.5, 1, 2.5, 5, 10, 25, 50)


def _spread_width(S: float) -> float:
    """Standard wing width: the largest round size within ~2.5% of spot."""
    return max((w for w in _WIDTHS if w <= S * 0.025), default=_WIDTHS[0])


def income_ideas(ticker: str, expiry: str | None = None) -> dict:
    def _fetch():
        S = _spot(ticker)
        exps = _expirations(ticker)
        choices = [e for e in exps if 5 <= _dte(e) <= 75]
        exp = expiry if expiry in exps else _pick_expiry(exps, 35, 20, 50) or (choices[0] if choices else None)
        if not exp:
            raise LookupError("No suitable expirations")
        d = max(_dte(exp), 1)
        T = d / 365
        calls, puts = _chain(ticker, exp)

        earnings = _earnings_date(ticker)
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
                    "Many traders take profit at ~50% of the credit, and close or roll if the stock breaks the short "
                    "strike. Close before expiry to avoid assignment.", fill + " Enter both legs as one spread order."],
            "ic": ["Works best when IV is high and you expect no big move. Avoid holding through earnings — a gap "
                   "can blow through one side.",
                   "Manage at ~50% profit, or close the tested side if price reaches a short strike.",
                   fill + " Enter all four legs as one order."],
        }

        return {
            "ticker": ticker, "spot": round(S, 2), "expiry": exp, "dte": d,
            "expirations": [{"date": e, "dte": _dte(e)} for e in choices],
            "earnings_date": earnings, "earnings_before_expiry": earnings_before,
            "expected_move": None if not em else {"move": round(em, 2), "low": round(em_range[0], 2),
                                                  "high": round(em_range[1], 2)},
            "covered_calls": _ideas(call_rows, "call", S, d),
            "cash_secured_puts": _ideas(put_rows, "put", S, d),
            "put_credit_spreads": _put_credit_spreads(put_rows, put_q, S, T, em_range),
            "iron_condors": _iron_condors(put_rows, put_q, call_rows, call_q, S, T, em_range),
            "tips": tips,
        }

    return get_or_fetch(f"income:{ticker}:{expiry or 'auto'}", _fetch, ttl=300)


def _otm_rows(df, kind: str, S: float, T: float) -> list[dict]:
    """Sellable OTM strikes with model delta / probability ITM."""
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        K = float(r["strike"])
        if (kind == "call" and K <= S) or (kind == "put" and K >= S):
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
