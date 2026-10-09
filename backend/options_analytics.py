"""Options analytics: implied-vs-realized volatility, expected moves, and income ideas
(covered calls / cash-secured puts). Chains come from Yahoo, falling back to CBOE delayed
quotes; IV is solved from mid prices because Yahoo's own IV field is often stale outside
market hours."""

import logging
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import yfinance as yf

import track_record
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
    if math.isfinite(bid) and math.isfinite(ask) and bid > 0 and ask >= bid:
        return (bid + ask) / 2
    return None


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


def _days_until(day: str) -> int:
    """Calendar days from today in New York, the same clock expiries use."""
    return (datetime.strptime(day, "%Y-%m-%d").date() - datetime.now(_ET).date()).days


def _close_at(expiry: str) -> datetime:
    from market_calendar import close_time
    day = datetime.strptime(expiry, "%Y-%m-%d")
    hour, minute = close_time(day)
    return day.replace(hour=hour, minute=minute, tzinfo=_ET)


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
    """ATM implied vol from the 4 calls and 4 puts nearest spot with tight quotes, weighted toward the
    closest strikes; falls back to the single nearest strike when nothing is quoted (e.g. after hours)."""
    calls, puts = _chain(ticker, expiry)
    T = _years(expiry)
    num = den = 0.0
    fallback = []
    for df, kind in ((calls, "call"), (puts, "put")):
        if df is None or df.empty:
            continue
        near = df.assign(_d=(df["strike"] - S).abs()).nsmallest(4, "_d")
        for i, (_, row) in enumerate(near.iterrows()):
            iv = _row_iv(row, S, T, kind)
            if not iv:
                continue
            if i == 0:
                fallback.append(iv)
            sp = _spread_pct(float(row.get("bid") or 0), float(row.get("ask") or 0))
            if sp is None or sp > 40:
                continue
            w = 1 / (row["_d"] + S * 0.005)
            num += iv * w
            den += w
    if den:
        return num / den
    return sum(fallback) / len(fallback) if fallback else None


def earnings_info(ticker: str) -> dict:
    """Last and next earnings from Finnhub and Yahoo combined. When they disagree on the next date the earlier one
    is used (safer for risk checks) and it's marked unconfirmed."""
    def _fetch():
        today = datetime.now(_ET).date().isoformat()
        past, future = {}, {}  # date -> {"timing", "eps", "src"}
        try:
            calendar = finnhub_earnings_calendar(150, ticker, days_back=100)
        except Exception as error:
            log.info("Finnhub earnings dates unavailable for %s: %s", ticker, error)
            calendar = []
        for e in calendar:
            d = e.get("date")
            if not d or e.get("symbol") != ticker:
                continue
            timing = {"bmo": "before open", "amc": "after close"}.get(e.get("hour"))
            bucket = past if (e.get("epsActual") is not None or d < today) else future
            bucket.setdefault(d, {"timing": timing, "eps": e.get("epsActual"), "src": set()})["src"].add("finnhub")
        try:
            ed = yf.Ticker(ticker).get_earnings_dates(limit=8)
            for when, row in (ed.iterrows() if ed is not None else []):
                d = when.date().isoformat()
                rep = row.get("Reported EPS")
                reported = rep is not None and not (isinstance(rep, float) and math.isnan(rep))
                bucket = past if (reported or d < today) else future
                item = bucket.setdefault(d, {"timing": "before open" if when.hour < 12 else "after close",
                                             "eps": float(rep) if reported else None, "src": set()})
                item["src"].add("yahoo")
        except Exception as e:
            log.info("Yahoo earnings dates unavailable for %s: %s", ticker, e)
        # A report already in `past` can't also be upcoming
        future = {d: v for d, v in future.items() if d not in past}

        nxt = min(future) if future else None
        others = [d for d in future if d != nxt and (datetime.strptime(d, "%Y-%m-%d") -
                  datetime.strptime(nxt, "%Y-%m-%d")).days <= 20] if nxt else []
        confirmed = bool(nxt) and (len(future[nxt]["src"]) > 1 or any(
            abs((datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(nxt, "%Y-%m-%d")).days) <= 1 for d in others))
        last = max(past) if past else None
        days_since = (datetime.now(_ET).date() - datetime.strptime(last, "%Y-%m-%d").date()).days if last else None
        return {
            "next": nxt, "next_timing": future[nxt]["timing"] if nxt else None, "next_confirmed": confirmed,
            "next_alt": None if confirmed or not others else others[0],
            "last": last, "last_timing": past[last]["timing"] if last else None,
            "last_eps": past[last]["eps"] if last else None, "days_since_last": days_since,
        }
    try:
        return get_or_fetch(f"earnings-info:{ticker}", _fetch, ttl=6 * 3600)
    except Exception as e:
        log.info("Earnings info failed for %s: %s", ticker, e)
        return {"next": None, "next_confirmed": False, "last": None, "days_since_last": None}


def _earnings_date(ticker: str) -> str | None:
    return earnings_info(ticker).get("next")


_FUND_TYPES = {"ETF", "MUTUALFUND", "INDEX"}


def _is_fund(ticker: str) -> bool:
    """ETFs, funds and indexes have no company earnings, so a missing report date is expected, not unknown risk."""
    def _fetch():
        return (yf.Ticker(ticker).get_info() or {}).get("quoteType") or ""
    try:
        return get_or_fetch(f"quote-type:{ticker}", _fetch, ttl=7 * 86400) in _FUND_TYPES
    except Exception as error:
        log.info("Quote type unavailable for %s: %s", ticker, error)
        return False


def _earnings_extra(ticker: str) -> dict:
    i = earnings_info(ticker)
    return {"earnings_confirmed": i.get("next_confirmed", False), "earnings_alt": i.get("next_alt"),
            "earnings_timing": i.get("next_timing"), "last_earnings": i.get("last"),
            "last_earnings_timing": i.get("last_timing"), "days_since_earnings": i.get("days_since_last"),
            "no_earnings_expected": not i.get("next") and _is_fund(ticker)}


def _past_earnings_moves(ticker: str) -> list[dict]:
    """Close-to-close reaction to each of the last ~12 reports (after-close: that day → next day)."""
    def _fetch():
        ed = yf.Ticker(ticker).get_earnings_dates(limit=16)
        closes = get_stock_data(ticker, period="5y", interval="1d")["Close"]
        days = [d.date() for d in closes.index]
        today = datetime.now(_ET).date()
        out = []
        for when, _ in (ed.iterrows() if ed is not None else []):
            d = when.date()
            if d >= today:
                continue
            after = when.hour >= 12
            try:
                i = days.index(d)
            except ValueError:
                continue
            a, b = (i, i + 1) if after else (i - 1, i)
            if a < 0 or b >= len(days):
                continue
            out.append({"date": d.isoformat(), "timing": "after close" if after else "before open",
                        "move_pct": round((float(closes.iloc[b]) / float(closes.iloc[a]) - 1) * 100, 2)})
        return sorted(out, key=lambda m: m["date"], reverse=True)[:12]
    return get_or_fetch(f"earnings-moves:{ticker}", _fetch, ttl=12 * 3600)


def earnings_moves(ticker: str) -> dict:
    """How far the stock really moved on past reports vs how far options price the next one."""
    def _fetch():
        from database import kv_get, kv_set
        moves = _past_earnings_moves(ticker)
        info = earnings_info(ticker)
        for m in moves:
            saved = kv_get(f"em-implied:{ticker}:{m['date']}")
            m["implied_pct"] = saved["data"].get("move_pct") if saved and isinstance(saved["data"], dict) else None
        absm = sorted(abs(m["move_pct"]) for m in moves)
        avg = round(sum(absm) / len(absm), 2) if absm else None
        implied = expiry = None
        nxt = info.get("next")
        if nxt and 0 <= (date.fromisoformat(nxt) - datetime.now(_ET).date()).days <= 45:
            S = _spot(ticker)
            # The first expiry that settles after the reaction day
            after = [e for e in _expirations(ticker) if _live(e) and
                     (e > nxt if info.get("next_timing") != "before open" else e >= nxt)]
            if after:
                expiry = after[0]
                calls, puts = _chain(ticker, expiry)
                c = calls.iloc[(calls["strike"] - S).abs().argsort()[:1]] if calls is not None and not calls.empty else None
                p = puts.iloc[(puts["strike"] - S).abs().argsort()[:1]] if puts is not None and not puts.empty else None
                cm = _mid(c.iloc[0]) if c is not None else None
                pm = _mid(p.iloc[0]) if p is not None else None
                if cm and pm:
                    straddle = (cm + pm) / S * 100
                    implied = round(straddle, 2)
                    key = f"em-implied:{ticker}:{nxt}"
                    if (date.fromisoformat(nxt) - datetime.now(_ET).date()).days == 1 and _market_open() and not kv_get(key):
                        kv_set(key, {"move_pct": implied, "as_of": datetime.now(_ET).isoformat(), "horizon": "prior calendar day"})
        ratio = round(implied / avg, 2) if implied and avg else None
        verdict = None
        if ratio:
            verdict = ("rich" if ratio >= 1.2 else "cheap" if ratio <= 0.85 else "fair")
        return {
            "ticker": ticker, "moves": moves, "avg_abs_move_pct": avg,
            "median_abs_move_pct": absm[len(absm) // 2] if absm else None,
            "max_abs_move_pct": absm[-1] if absm else None,
            "up_count": sum(1 for m in moves if m["move_pct"] > 0), "count": len(moves),
            "next_earnings": nxt, "next_confirmed": info.get("next_confirmed"), "implied_move_pct": implied,
            "implied_expiry": expiry, "ratio": ratio, "verdict": verdict,
                "as_of": datetime.now(_ET).isoformat(),
                "note": "Implied move = at-the-money straddle midpoint divided by spot for the first expiry after the report. "
                    "Includes non-earnings time value. Actual moves are close-to-close. This is a pricing proxy, not a "
                    "validated trading edge. Saved observations use the prior calendar day; gaps are not backfilled.",
        }
    return get_or_fetch(f"earnings-moves-v2:{ticker}", _fetch, ttl=900)


def _spot(ticker: str) -> float:
    q = get_quote(ticker)
    if not q.get("price"):
        raise ValueError("Spot price unavailable")
    return float(q["price"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _market_open() -> bool:
    from market_calendar import close_time, trading_day
    now = datetime.now(ZoneInfo("America/New_York"))
    return trading_day(now) and (9, 45) <= (now.hour, now.minute) <= close_time(now)


# ── Volatility overview ──────────────────────────────────────────────────

def volatility_overview(ticker: str) -> dict:
    def _fetch():
        S = _spot(ticker)
        exps = _expirations(ticker)
        if not exps:
            raise LookupError("No listed options")

        monthly = _liquid_expiry(ticker, exps, 30, 20, 60, S)[0] or _pick_expiry(exps, 30, 5, 120)
        weekly = _liquid_expiry(ticker, exps, 7, 4, 12, S)[0]
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
        e_days = _days_until(earnings) if earnings else None
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
            **_earnings_extra(ticker),
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
        for lo in (20, 10):  # shorter than ~20 days only when nothing else ends before the report
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

        e_days = _days_until(earnings) if earnings else None
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

        result = {
            "ticker": ticker, "spot": round(S, 2), "expiry": exp, "dte": _dte(exp),
            "expirations": [{"date": e, "dte": _dte(e), "monthly": _is_monthly(e)} for e in choices],
            "earnings_date": earnings, "earnings_before_expiry": earnings_before, **_earnings_extra(ticker),
            "expected_move": None if not em else {"move": round(em, 2), "low": round(em_range[0], 2),
                                                  "high": round(em_range[1], 2)},
            **ideas,
            "tips": tips,
            "as_of": _now_iso(),
        }
        track_record.record_income(result)
        return result

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
    # Among similar deltas, favour high open interest and a tight bid/ask
    pick = (max(near, key=lambda x: _strike_score(x, target, 0.05)) if near
            else min(cands, key=lambda x: abs(x["delta"] - target)))
    return pick if abs(pick["delta"] - target) <= 0.12 else None


def _spread_pct(bid: float, ask: float) -> float | None:
    return (ask - bid) / ((ask + bid) / 2) * 100 if ask > bid > 0 else None


def _liquidity(oi: int, spread_pct: float | None) -> str:
    s = spread_pct or 0
    return "good" if oi >= 500 and s <= 8 else "thin" if oi < 100 or s > 20 else "ok"


def _prob_above(S: float, X: float, T: float, iv: float) -> float:
    return 1.0 if X <= 0 else _ncdf(_d1_d2(S, X, T, iv)[1])


def _vertical(short: dict, quotes: dict, kind: str, S: float) -> dict | None:
    """Sell `short`, buy a protective wing about a standard width further OTM, favouring wings with open interest."""
    K = short["strike"]
    w = _spread_width(S)
    goal = K - w if kind == "put" else K + w
    wings = [k for k in quotes if (k < K if kind == "put" else k > K) and 0.5 * w <= abs(k - K) <= 2 * w]
    if not wings:
        wings = [k for k in quotes if (k < K if kind == "put" else k > K)]
    if not wings:
        return None
    liquid = [k for k in wings if quotes[k]["oi"] >= _MIN_OI]
    L = max(liquid or wings, key=lambda k: 0.3 * _oi_score(quotes[k]["oi"]) - abs(k - goal) / w)
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
        earnings = _earnings_date(ticker)
        exp, exp_note = _liquid_expiry(ticker, exps, target_dte, lo, hi, S)
        if not exp and risk == "low":
            longest = max(exps, key=_dte)
            exp = longest if _dte(longest) >= 120 else None
        exp = exp or _pick_expiry(exps, target_dte, 0, 1000)
        if not exp:
            raise LookupError("No suitable expirations")
        # Short-horizon plans avoid holding through a report when an earlier liquid expiry exists; LEAPS can't.
        if earnings and earnings <= exp and risk != "low":
            pre, _ = _liquid_expiry(ticker, [e for e in exps if e < earnings], target_dte, max(lo // 2, 0), hi, S)
            if pre:
                exp_note = (f"Moved to {pre}, the last liquid expiry before earnings on {earnings}, so the trade "
                            f"doesn't hold through the report" + (" (shorter than this plan's usual window)."
                                                                 if _dte(pre) < lo else "."))
                exp = pre
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
        e_days = _days_until(earnings) if earnings else None
        no_earnings = not earnings and _is_fund(ticker)

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
        eligible = {key: idea for key, idea in ideas.items() if idea.get("liquidity") in ("good", "ok")}
        no_trade_reason = None
        if not earnings and not no_earnings and risk != "low":
            no_trade_reason = "Earnings date is unavailable, so option event risk is not cleared."
        elif earnings and earnings <= exp and risk != "low":
            no_trade_reason = ("Earnings occur by every liquid expiry in this timeframe, so no option trade passes the "
                               "event-risk check.")
        elif not eligible:
            no_trade_reason = "No liquid candidate fits this budget. Thin or unknown liquidity is not eligible."
        if no_trade_reason and eligible:
            # Shares have no expiry; the option event-risk block does not apply to them.
            eligible = {key: idea for key, idea in eligible.items() if key == "shares"}
            if eligible:
                no_trade_reason += " Shares are still shown; they also gap on a report, so size for it."
        best, why = _pick_best(eligible, *args)
        ordered = sorted(eligible.values(), key=lambda idea: idea["kind"] != best)
        for i in ordered:
            i["best"] = i["kind"] == best

        result = {
            "ticker": ticker, "spot": round(S, 2), "direction": direction, "risk": risk, "budget": budget,
            "timeframe": plan["label"], "expiry": exp, "dte": d, "expiry_note": exp_note,
            "monthly": _is_monthly(exp), "iv_level": iv_level,
            "expected_move": None if not em else {"move": round(em, 2), "pct": round(em / S * 100, 1),
                                                  "low": round(S - em, 2), "high": round(S + em, 2)},
            "earnings_date": earnings, "earnings_before_expiry": e_days is not None and 0 <= e_days <= d,
            **_earnings_extra(ticker),
            "ideas": ordered, "best_why": why, "no_trade_reason": no_trade_reason,
            "min_budget_needed": round(min(needed), 2) if not ordered and needed else None,
            "as_of": _now_iso(),
        }
        if ordered:
            track_record.record_directional(result)
        return result

    return get_or_fetch(f"directional-v3:{ticker}:{direction}:{risk}:{budget}", _fetch, ttl=180)


# ── Covered calls after assignment (wheel step 2) ───────────────────────────

def assigned_calls(ticker: str, cost_basis: float, shares: int = 100, cadence: str = "standard") -> dict:
    """All liquid covered-call candidates by qualifying expiry, at or above entered cost."""
    if cadence not in {"all", "standard", "weekly", "leaps"}:
        raise ValueError("Invalid covered-call cadence")
    leaps = cadence == "leaps"
    def _fetch():
        from concurrent.futures import ThreadPoolExecutor
        S = _spot(ticker)
        exps = _expirations(ticker)
        earnings = _earnings_date(ticker)
        lower, upper = (1, 7) if cadence == "weekly" else (180, 800) if leaps else (0, 120)
        # Long-dated chains quote wider and trade less; a weekly-grade spread/OI bar would reject nearly all of them.
        max_spread, min_oi = (0.15, 100) if leaps else (0.08, 500)
        choices = sorted({expiry for expiry in exps if _live(expiry) and lower <= _dte(expiry) <= upper})
        if not choices:
            raise LookupError(f"No listed expirations within {lower}-{upper} days")
        contracts = shares // 100

        def idea(r, e, rows):
            K, mid = r["strike"], r["mid"]
            days = max(_dte(e), 1)
            label = "Keep the shares" if r["delta"] < 0.2 else "Balanced" if r["delta"] <= 0.32 else "Max premium"
            cap = next((row for row in sorted(rows, key=lambda row: row["strike"]) if row["strike"] >= round(K * 1.1, 2)
                        and row["ask"] >= row["bid"] > 0 and row["oi"] >= 100), None)
            upside_cap = None
            if cap and mid - cap["mid"] > 0:
                upside_cap = {"strike": cap["strike"], "mid": round(cap["mid"], 2),
                              "net_credit": round(mid - cap["mid"], 2),
                              "total_net": round((mid - cap["mid"]) * 100 * contracts, 2)}
            return {
                "label": label, "expiry": e, "dte": _dte(e), "strike": K, "delta": round(r["delta"], 2),
                "mid": round(mid, 2), "bid": round(r["bid"], 2), "ask": round(r["ask"], 2),
                "premium": round(mid * 100, 2), "total_premium": round(mid * 100 * contracts, 2),
                "premium_adjusted_cost": round(cost_basis - mid * 100 * contracts / shares, 2),
                "return_pct": round(mid / cost_basis * 100, 2),
                "annualized_pct": round(mid / cost_basis * 365 / days * 100, 1),
                "yield_pct": round(mid / S * 100, 2),
                "yield_annualized_pct": round(mid / S * 365 / days * 100, 1),
                "if_called_pct": round((K - cost_basis + mid) / cost_basis * 100, 2),
                "if_called_from_today_pct": round((K - S + mid) / S * 100, 2),
                "gain_realized_if_called": round((K - cost_basis) * 100 * contracts, 2),
                "prob_called_pct": round(r["p_itm"] * 100), "otm_pct": round((K - S) / S * 100, 1),
                "open_interest": r["oi"], "liquidity": "good",
                "spread_pct": round((r["ask"] - r["bid"]) / mid * 100, 2),
                "upside_cap": upside_cap,
            }

        def candidates(expiry):
            try:
                calls, _ = _chain(ticker, expiry)
                rows = _otm_rows(calls, "call", S, _years(expiry))
                eligible = [row for row in rows if row["strike"] >= cost_basis
                            and row["oi"] >= min_oi and row["ask"] >= row["bid"] > 0
                            and (row["ask"] - row["bid"]) / ((row["ask"] + row["bid"]) / 2) <= max_spread
                            and 0.10 <= row["delta"] <= 0.40 and row["mid"] / cost_basis >= 0.001]
                return {"date": expiry, "dte": _dte(expiry), "monthly": _is_monthly(expiry),
                        "earnings_before_expiry": bool(earnings and earnings <= expiry),
                        "ideas": [idea(row, expiry, rows) for row in sorted(eligible, key=lambda row: row["strike"])]}
            except Exception as error:
                log.info("Covered-call chain unavailable for %s %s: %s", ticker, expiry, error)
                return {"date": expiry, "unavailable": True}

        with ThreadPoolExecutor(max_workers=4) as pool:
            checked = list(pool.map(candidates, choices))
        dates = [result for result in checked if result.get("ideas")]
        first = dates[0] if dates else None

        gap = (S - cost_basis) / cost_basis * 100
        note = (f"OTM strikes at or above cost; open interest >= {min_oi}; bid/ask spread <= {max_spread:.0%}; "
                "delta 0.10-0.40; quoted premium >= 0.1% of cost. These are screening rules, not a profit guarantee.")
        return {
            "ticker": ticker, "spot": round(S, 2), "cost_basis": round(cost_basis, 2), "shares": shares,
            "cadence": cadence,
            "contracts": contracts, "expiry": first["date"] if first else None,
            "dte": first["dte"] if first else None, "monthly": first["monthly"] if first else False,
            "earnings_date": earnings, "earnings_before_expiry": first["earnings_before_expiry"] if first else False,
            "unrealized_pct": round(gap, 1), "note": note, "ideas": first["ideas"] if first else [],
            "expirations": dates, "checked_expirations": len(checked),
            "skipped_expirations": sum(not result.get("ideas") and not result.get("unavailable") for result in checked),
            "unavailable_expirations": [result["date"] for result in checked if result.get("unavailable")],
            "as_of": _now_iso(),
        }

    return get_or_fetch(f"assigned-cc-v4:{ticker}:{cost_basis:.2f}:{shares}:{cadence}", _fetch, ttl=180)


# ── Roll / repair a tested short option position ────────────────────────────

_ROLL_RULES = [
    "Roll when the short strike is breached or its delta passes ~0.50 — ideally with 2–3 weeks left, not on expiry day.",
    "Compare rolling with closing and assignment. A net credit does not establish lower risk or a better expected outcome.",
    "Avoid rolling into an earnings date unless you accept the gap risk.",
    "Two or three rolls is the limit. If the stock keeps running against you, the thesis is broken — take the loss.",
]


def _roll_candidate(r, wing, K, width, close_mid, credit, kind, e, cur_dte, earnings, allow_debit=False):
    sign = 1 if kind == "call" else -1
    K2 = r["strike"]
    new_credit = r["mid"] - (wing["mid"] if wing else 0)
    if new_credit <= 0:
        return None
    net = new_credit - close_mid
    if net < 0 and not allow_debit:
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
        "opening_credit_natural": round((r["bid"] - (wing["ask"] if wing else 0)) * 100, 2),
        "delta": round(r["delta"], 2), "prob_otm_pct": round((1 - r["p_itm"]) * 100),
        "open_interest": oi, "liquidity": _liquidity(oi, worst),
        "spans_earnings": bool(earnings and datetime.now(_ET).date().isoformat() <= earnings <= e),
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
                c["net_credit_natural"] = round(c["opening_credit_natural"] - close_nat * 100 - (4 if wing else 2), 2)
                if gain == 0:
                    same = c
                if not furthest or rank(c) > rank(furthest):
                    furthest = c
            for c in (same, furthest):
                if c and not any(x["expiry"] == c["expiry"] and x["short_strike"] == c["short_strike"] for x in rolls):
                    c["type"] = "out" if c["strike_change"] == 0 else "improve"
                    rolls.append(c)

        # Roll in: when the position holds through earnings, an earlier expiry that settles before the report
        today = datetime.now(_ET).date().isoformat()
        roll_ins = []
        if earnings and today <= earnings <= expiry:
            for e in [e for e in exps if e < earnings and e < expiry and _dte(e) >= 1][-2:]:
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
                    wing = q2.get(r["strike"] - width) if width is not None else None
                    if width is not None and not wing:
                        continue
                    c = _roll_candidate(r, wing, K, width, close_mid, credit, kind, e, cur_dte, earnings, allow_debit=True)
                    if not c:
                        continue
                    # Never pay away more than the premium already collected (or half the close cost if unknown)
                    floor = -(credit if credit is not None else close_mid / 2) * 100
                    if c["net_credit"] < floor:
                        continue
                    c["net_credit_natural"] = round(c["opening_credit_natural"] - close_nat * 100 - (4 if wing else 2), 2)
                    if gain == 0:
                        same = c
                    if not furthest or c["strike_change"] > furthest["strike_change"]:
                        furthest = c
                for c in (same, furthest):
                    if c and not any(x["expiry"] == c["expiry"] and x["short_strike"] == c["short_strike"] for x in roll_ins):
                        c["type"] = "in" if c["strike_change"] == 0 else "in_improve"
                        roll_ins.append(c)

        safe = [r for r in rolls if earnings and not r["spans_earnings"] and r["liquidity"] != "thin" and r["added_days"] <= 45 and r["net_credit_natural"] >= 0]
        best = tested and max(safe, key=lambda r: (r["strike_change"], -r["added_days"], r["net_credit_natural"]),
                              default=None)
        for r in rolls:
            r["best"] = r is best
        rolls.sort(key=lambda r: (not r["best"], r["dte"], -r["strike_change"]))
        for r in roll_ins:
            r["best"] = False
        rolls = rolls[:8] + roll_ins

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
        if roll_ins:
            alt.append({"title": "Roll in before earnings",
                        "text": f"Earnings ({earnings}) fall before this expiry. Rolling in to an earlier expiry is the same as "
                                "closing now and selling a new, shorter option: the premium already collected is banked either "
                                "way, so judge the new option on its own. It usually costs a net debit and still carries "
                                "assignment risk until it expires."})
        if tested and not any(r["type"] in ("out", "improve") for r in rolls):
            verdict = "No roll pays a net credit within the next ~2 months. Consider closing or accepting assignment."
        return {
            "ticker": ticker, "spot": round(S, 2), "strategy": strategy, "expiry": expiry,
            "short_strike": K, "long_strike": long_strike, "width": width, "earnings_date": earnings,
            "status": status, "verdict": verdict, "rolls": rolls, "alternatives": alt, "rules": _ROLL_RULES,
        }

    key = f"roll:{ticker}:{strategy}:{expiry}:{short_strike}:{long_strike}:{credit}"
    return get_or_fetch(key, _fetch, ttl=120)
