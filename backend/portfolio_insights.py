"""Portfolio analytics: performance vs SPY, projected dividend income, wash-sale warnings,
and broker CSV import."""

import csv
import io
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

from cache import get_or_fetch
from database import add_user_holding, get_closed_trades, get_user_holdings
from stock_data import get_quote, get_stock_data

log = logging.getLogger(__name__)
MAX_TICKERS = 40


def _d(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _closes(ticker: str, since: date) -> pd.Series:
    days = (date.today() - since).days
    period = "1y" if days <= 360 else "2y" if days <= 720 else "5y" if days <= 1800 else "max"
    s = get_stock_data(ticker, period=period, interval="1d")["Close"]
    s.index = pd.to_datetime(s.index.date)
    return s[~s.index.duplicated(keep="last")]


def _price_on(s: pd.Series, d: date) -> float | None:
    sub = s[s.index <= pd.Timestamp(d)]
    return float(sub.iloc[-1]) if len(sub) else (float(s.iloc[0]) if len(s) else None)


# ── Performance vs S&P 500 ───────────────────────────────────────────────

def performance(user_id: int) -> dict:
    lots = [h for h in get_user_holdings(user_id) if h["shares"] > 0][:200]
    if not lots:
        return {"lots": 0}
    for h in lots:
        h["acq"] = _d(h.get("date_added")) or date.today()
    start = min(h["acq"] for h in lots)
    spy = _closes("SPY", start)
    tickers = sorted({h["ticker"] for h in lots})[:MAX_TICKERS]
    closes = {}
    for t in tickers:
        try:
            closes[t] = _closes(t, start)
        except Exception as e:
            log.info("No history for %s: %s", t, e)

    per, cost_total, value_total, spy_total = defaultdict(lambda: {"cost": 0.0, "value": 0.0, "spy": 0.0}), 0.0, 0.0, 0.0
    spy_now = float(spy.iloc[-1])
    for h in lots:
        s = closes.get(h["ticker"])
        if s is None or s.empty:
            continue
        cost = h["shares"] * h["buy_price"]
        value = h["shares"] * float(s.iloc[-1])
        spy_then = _price_on(spy, h["acq"])
        shadow = cost / spy_then * spy_now if spy_then else cost
        p = per[h["ticker"]]
        p["cost"] += cost
        p["value"] += value
        p["spy"] += shadow
        cost_total, value_total, spy_total = cost_total + cost, value_total + value, spy_total + shadow

    rows = sorted(({"ticker": t, "cost": round(v["cost"], 2), "value": round(v["value"], 2),
                    "return_pct": round((v["value"] / v["cost"] - 1) * 100, 2) if v["cost"] else None,
                    "spy_return_pct": round((v["spy"] / v["cost"] - 1) * 100, 2) if v["cost"] else None,
                    "vs_spy": round(v["value"] - v["spy"], 2)} for t, v in per.items()),
                  key=lambda r: r["vs_spy"], reverse=True)

    # Weekly series: value of the lots you hold vs. the same dollars put into SPY on the same dates
    idx = spy.index[spy.index >= pd.Timestamp(start)]
    series = []
    if len(idx) > 5:
        sample = idx[::5].append(idx[-1:]).unique()
        aligned = {t: s.reindex(sample, method="ffill").bfill() for t, s in closes.items() if not s.empty}
        spy_s = spy.reindex(sample)
        v = pd.Series(0.0, index=sample)
        sh, c = v.copy(), v.copy()
        for h in lots:
            s = aligned.get(h["ticker"])
            spy_then = _price_on(spy, h["acq"])
            if s is None or not spy_then:
                continue
            held = sample >= pd.Timestamp(h["acq"])
            cost = h["shares"] * h["buy_price"]
            v += (h["shares"] * s).where(held, 0.0)
            sh += (cost / spy_then * spy_s).where(held, 0.0)
            c += pd.Series(cost, index=sample).where(held, 0.0)
        series = [{"date": ts.date().isoformat(), "portfolio": round(float(v[ts]), 2), "spy": round(float(sh[ts]), 2),
                   "cost": round(float(c[ts]), 2)} for ts in sample if c[ts] > 0]

    realized = sum(t["pnl"] for t in get_closed_trades(user_id))
    return {
        "lots": len(lots), "since": start.isoformat(), "cost": round(cost_total, 2), "value": round(value_total, 2),
        "spy_value": round(spy_total, 2),
        "return_pct": round((value_total / cost_total - 1) * 100, 2) if cost_total else None,
        "spy_return_pct": round((spy_total / cost_total - 1) * 100, 2) if cost_total else None,
        "alpha": round(value_total - spy_total, 2), "realized_pnl": round(realized, 2),
        "by_ticker": rows, "series": series,
        "note": "Compares the lots you hold today with buying SPY for the same dollars on each lot's purchase date. "
                "Dividends are not included.",
    }


# ── Dividend income ──────────────────────────────────────────────────────

def _dividends(ticker: str) -> list[tuple[date, float]]:
    def _fetch():
        s = yf.Ticker(ticker).dividends
        return [(ts.date(), float(v)) for ts, v in s.items()] if s is not None else []
    return get_or_fetch(f"divs:{ticker}", _fetch, ttl=12 * 3600)


def dividend_income(user_id: int) -> dict:
    shares, cost = defaultdict(float), defaultdict(float)
    for h in get_user_holdings(user_id):
        shares[h["ticker"]] += h["shares"]
        cost[h["ticker"]] += h["shares"] * h["buy_price"]
    today = date.today()
    months = defaultdict(float)
    rows, payments = [], []
    for t in sorted(shares)[:MAX_TICKERS]:
        try:
            divs = _dividends(t)
        except Exception:
            continue
        last_year = [(d, a) for d, a in divs if today - timedelta(days=365) < d <= today]
        if not last_year:
            continue
        annual = sum(a for _, a in last_year) * shares[t]
        for d, a in last_year:
            nd = d + timedelta(days=364)
            amt = a * shares[t]
            months[nd.strftime("%Y-%m")] += amt
            payments.append({"ticker": t, "est_ex_date": nd.isoformat(), "amount": round(amt, 2),
                             "per_share": round(a, 4)})
        try:
            price = get_quote(t).get("price") or 0
        except Exception:
            price = 0
        rows.append({"ticker": t, "shares": round(shares[t], 4), "annual_income": round(annual, 2),
                     "per_share": round(sum(a for _, a in last_year), 4), "payments_per_year": len(last_year),
                     "yield_pct": round(sum(a for _, a in last_year) / price * 100, 2) if price else None,
                     "yield_on_cost_pct": round(annual / cost[t] * 100, 2) if cost[t] else None})
    calendar = [{"month": (today.replace(day=1) + timedelta(days=32 * i)).strftime("%Y-%m")} for i in range(12)]
    for c in calendar:
        c["income"] = round(months.get(c["month"], 0.0), 2)
    payments.sort(key=lambda p: p["est_ex_date"])
    total = sum(r["annual_income"] for r in rows)
    return {"annual_income": round(total, 2), "monthly_avg": round(total / 12, 2),
            "by_ticker": sorted(rows, key=lambda r: r["annual_income"], reverse=True),
            "calendar": calendar, "upcoming": [p for p in payments if p["est_ex_date"] >= today.isoformat()][:12],
            "note": "Projected from the last 12 months of payments at your current share count. Ex-dates are estimates."}


# ── Wash-sale warnings ───────────────────────────────────────────────────

def wash_sales(user_id: int) -> dict:
    today = date.today()
    lots = get_user_holdings(user_id)
    closed = get_closed_trades(user_id)
    warnings = []
    for t in closed:
        if (t.get("pnl") or 0) >= 0:
            continue
        sold = _d(t.get("closed_at"))
        if not sold or (today - sold).days > 400:
            continue
        rebuys = [h for h in lots if h["ticker"] == t["ticker"] and _d(h.get("date_added"))
                  and abs((_d(h["date_added"]) - sold).days) <= 30]
        if rebuys:
            warnings.append({"level": "high", "ticker": t["ticker"], "date": sold.isoformat(),
                             "text": f"Sold {t['ticker']} at a ${abs(t['pnl']):,.2f} loss on {sold} and bought it within "
                                     f"30 days ({', '.join(str(_d(h['date_added'])) for h in rebuys)}). The loss is likely "
                                     "disallowed as a wash sale and added to the new lot's cost basis."})
        elif (today - sold).days <= 30:
            safe = sold + timedelta(days=31)
            warnings.append({"level": "info", "ticker": t["ticker"], "date": sold.isoformat(),
                             "text": f"You realized a ${abs(t['pnl']):,.2f} loss on {t['ticker']} on {sold}. "
                                     f"Don't buy it back before {safe} (in any account, including IRAs) to keep the loss."})
    by_ticker = defaultdict(list)
    for h in lots:
        by_ticker[h["ticker"]].append(h)
    for ticker, hs in by_ticker.items():
        recent = [h for h in hs if _d(h.get("date_added")) and (today - _d(h["date_added"])).days <= 30]
        if not recent:
            continue
        try:
            px = get_quote(ticker).get("price")
        except Exception:
            continue
        losers = [h for h in hs if px and px < h["buy_price"] and h not in recent]
        if losers:
            until = max(_d(h["date_added"]) for h in recent) + timedelta(days=31)
            warnings.append({"level": "medium", "ticker": ticker, "date": today.isoformat(),
                             "text": f"You bought {ticker} in the last 30 days. Selling an older losing lot before "
                                     f"{until} would trigger a wash sale."})
    order = {"high": 0, "medium": 1, "info": 2}
    warnings += _option_wash_sales(user_id, lots, today)
    warnings.sort(key=lambda w: order[w["level"]])
    return {"warnings": warnings, "lots": _holding_terms(lots, today),
            "note": "Based only on trades recorded here. Your broker's 1099-B is authoritative. Not tax advice."}


def _option_wash_sales(user_id: int, lots: list[dict], today: date) -> list[dict]:
    """Options on the same stock can be 'substantially identical': a losing close followed by a new position
    within 30 days may be a wash sale."""
    from database import get_closed_options, get_user_options
    opened = [(o["ticker"], _d(o.get("date_added")), "option") for o in get_user_options(user_id)]
    opened += [(h["ticker"], _d(h.get("date_added")), "shares") for h in lots]
    out = []
    for c in get_closed_options(user_id):
        closed = _d(c.get("closed_at"))
        if (c.get("pnl") or 0) >= 0 or not closed or (today - closed).days > 60:
            continue
        hits = [(t, d, w) for t, d, w in opened if t == c["ticker"] and d and 0 <= (d - closed).days <= 30]
        if hits:
            out.append({"level": "medium", "ticker": c["ticker"], "date": closed.isoformat(),
                        "text": f"Closed a {c['ticker']} ${c['strike']:g} {c['option_type']} at a ${abs(c['pnl']):,.2f} loss on "
                                f"{closed} and opened new {c['ticker']} {hits[0][2]} on {hits[0][1]}. Rolling a losing option "
                                "into a similar one can be treated as a wash sale — check with your broker."})
        elif (today - closed).days <= 30:
            out.append({"level": "info", "ticker": c["ticker"], "date": closed.isoformat(),
                        "text": f"${abs(c['pnl']):,.2f} option loss on {c['ticker']} on {closed}. Re-entering a similar "
                                f"position before {closed + timedelta(days=31)} may defer that loss."})
    return out


def _holding_terms(lots: list[dict], today: date) -> list[dict]:
    """Short- vs long-term status per lot, flagging gains that turn long-term soon."""
    prices, out = {}, []
    for h in lots:
        acq = _d(h.get("date_added"))
        if not acq or h["shares"] <= 0:
            continue
        t = h["ticker"]
        if t not in prices:
            try:
                prices[t] = get_quote(t).get("price")
            except Exception:
                prices[t] = None
        px = prices[t]
        lt_day = acq.replace(year=acq.year + 1) + timedelta(days=1) if not (acq.month == 2 and acq.day == 29) \
            else date(acq.year + 1, 3, 1)
        held = (today - acq).days
        gain = (px - h["buy_price"]) * h["shares"] if px else None
        long_term = today >= lt_day
        note = None
        if not long_term and gain and gain > 0 and (lt_day - today).days <= 60:
            note = f"Turns long-term on {lt_day} ({(lt_day - today).days} days). Selling before then taxes the gain at short-term rates."
        elif not long_term and gain is not None and gain < 0:
            note = "Short-term loss: offsets short-term gains first if you harvest it."
        out.append({"ticker": t, "shares": h["shares"], "acquired": acq.isoformat(), "days_held": held,
                    "term": "long" if long_term else "short", "long_term_on": None if long_term else lt_day.isoformat(),
                    "gain": None if gain is None else round(gain, 2), "note": note})
    out.sort(key=lambda r: (r["note"] is None, r["long_term_on"] or "9999"))
    return out


# ── Broker CSV import ────────────────────────────────────────────────────

_COLS = {
    "symbol": ("symbol", "ticker", "security symbol", "instrument"),
    "shares": ("quantity", "qty", "shares", "share quantity", "qty (quantity)"),
    "avg": ("average cost basis", "average cost", "avg cost", "cost/share", "cost per share", "avg price",
            "average price", "price paid", "unit cost", "cost basis per share", "avg cost basis"),
    "total": ("cost basis total", "cost basis", "total cost", "cost basis ($)", "book cost", "cost"),
    "acquired": ("date acquired", "acquired", "open date", "purchase date", "trade date", "acquisition date"),
    "value": ("value", "market value", "current value", "total value"),
}
_SKIP = {"CASH", "PENDING", "TOTAL", "ACCOUNT", "MONEY", "SWEEP", "CORE"}
# US money-market mutual funds use five-letter tickers ending in XX (VUSXX, SPAXX, SWVXX, ...).
_MONEY_MARKET = re.compile(r"[A-Z]{3}XX")


def _header(name: str) -> str:
    """Lower-case header without unit markers, so "Price Paid $" and "Cost Basis ($)" match their plain aliases."""
    name = re.sub(r"\s*(\(\$\)|\(%\)|\$|%)\s*$", "", str(name).strip().lower())
    return " ".join(name.split())


def _find_columns(row, aliases) -> dict:
    names = [_header(c) for c in row]
    return {key: next((j for j, n in enumerate(names) if n in {_header(a) for a in syn}), None) for key, syn in aliases.items()}


def _num(v) -> float | None:
    s = str(v or "").strip().replace("$", "").replace(",", "").replace("%", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    if s in ("", "--", "-", "n/a", "N/A"):
        return None
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        return None


def _date(v) -> str | None:
    s = str(v or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.isoformat() if d <= date.today() else None
        except ValueError:
            continue
    return None


def parse_broker_csv(text: str) -> dict:
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    header_i, cols = None, {}
    for i, r in enumerate(rows[:30]):
        found = _find_columns(r, _COLS)
        if found["symbol"] is not None and found["shares"] is not None:
            header_i, cols = i, found
            break
    if header_i is None:
        raise ValueError("Couldn't find Symbol and Quantity columns. Export positions as CSV from your broker.")
    out, skipped, money_market = [], [], []
    for n, r in enumerate(rows[header_i + 1:], start=header_i + 2):
        get = lambda k: r[cols[k]] if cols.get(k) is not None and cols[k] < len(r) else None
        raw = (get("symbol") or "").strip().upper()
        if not raw:
            continue
        if "**" in raw or any(w in raw for w in _SKIP):
            skipped.append({"line": n, "symbol": raw, "reason": "cash / money market"})
            continue
        qty = _num(get("shares"))
        option = parse_option_symbol(raw)
        if option:
            if not qty:
                skipped.append({"line": n, "symbol": raw, "reason": "no quantity"})
                continue
            if option["expiry"] < date.today().isoformat():
                skipped.append({"line": n, "symbol": raw, "reason": "option already expired"})
                continue
            contracts = abs(qty)
            if not float(contracts).is_integer():
                skipped.append({"line": n, "symbol": raw, "reason": "fractional contract quantity"})
                continue
            total, avg = _num(get("total")), _num(get("avg"))
            premium = abs(total) / (contracts * 100) if total else abs(avg) if avg else None
            if not premium:
                skipped.append({"line": n, "symbol": raw, "reason": "no option cost"})
                continue
            out.append({"kind": "option", **option, "contracts": int(contracts),
                        "position": "short" if qty < 0 else "long", "premium": round(premium, 4)})
            if len(out) >= 500:
                break
            continue
        sym = raw.rstrip("*").replace(" ", "")
        if _MONEY_MARKET.fullmatch(sym):
            amount = _num(get("value"))
            if amount is None and qty:
                amount = qty * (_num(get("avg")) or 1.0)
            if amount and amount > 0:
                money_market.append({"line": n, "ticker": sym, "amount": round(amount, 2)})
            else:
                skipped.append({"line": n, "symbol": sym, "reason": "money-market fund without a value"})
            continue
        if not re.fullmatch(r"[A-Z]{1,5}([.-][A-Z])?", sym):
            skipped.append({"line": n, "symbol": raw, "reason": "not a recognized stock, ETF or option symbol"})
            continue
        if not qty or qty <= 0:
            skipped.append({"line": n, "symbol": sym, "reason": "no quantity (short stock positions aren't imported)"})
            continue
        avg = _num(get("avg"))
        if avg is None and _num(get("total")) is not None:
            avg = _num(get("total")) / qty
        if not avg or avg <= 0:
            skipped.append({"line": n, "symbol": sym, "reason": "no cost basis"})
            continue
        out.append({"kind": "stock", "ticker": sym.replace(".", "-"), "shares": round(qty, 6), "price": round(avg, 4),
                    "acquired": _date(get("acquired"))})
        if len(out) >= 500:
            break
    return {"rows": out, "skipped": skipped, "money_market": money_market,
            "money_market_total": round(sum(m["amount"] for m in money_market), 2),
            "columns": {k: rows[header_i][v] for k, v in cols.items() if v is not None}}


_MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
_OPTION_FORMATS = (
    # OCC: AAPL  250117C00150000
    (re.compile(r"([A-Z]{1,6})\s*(\d{2})(\d{2})(\d{2})([CP])(\d{8})"), lambda m: (m[1], 2000 + int(m[2]), int(m[3]), int(m[4]), m[5], int(m[6]) / 1000)),
    # Fidelity: -AAPL250117C150
    (re.compile(r"([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d+(?:\.\d+)?)"), lambda m: (m[1], 2000 + int(m[2]), int(m[3]), int(m[4]), m[5], float(m[6]))),
    # Schwab: AAPL 01/17/2025 150.00 C
    (re.compile(r"([A-Z]{1,6}) (\d{2})/(\d{2})/(\d{4}) (\d+(?:\.\d+)?) ([CP])"), lambda m: (m[1], int(m[4]), int(m[2]), int(m[3]), m[6], float(m[5]))),
    # E*Trade / generic: AAPL JAN 17 '25 $150 CALL
    (re.compile(r"([A-Z]{1,6}) ([A-Z]{3}) (\d{1,2}) '?(\d{2}) \$?(\d+(?:\.\d+)?) (CALL|PUT)"),
     lambda m: (m[1], 2000 + int(m[4]), _MONTHS.get(m[2], 0), int(m[3]), m[6][0], float(m[5]))),
)


def parse_option_symbol(raw: str) -> dict | None:
    """Recognize common broker option symbols; returns underlying, expiry, type and strike."""
    text = re.sub(r"\s+", " ", raw.strip().upper().lstrip("-").strip())
    for pattern, fields in _OPTION_FORMATS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        ticker, year, month, day, kind, strike = fields(match)
        try:
            expiry = date(year, month, day).isoformat()
        except ValueError:
            return None
        if strike <= 0:
            return None
        return {"ticker": ticker, "expiry": expiry, "option_type": "call" if kind == "C" else "put", "strike": strike}
    return None


_HISTORY_COLS = {
    "symbol": ("symbol", "ticker", "security symbol", "instrument"),
    "description": ("description", "security description", "security"),
    "shares": ("quantity", "qty", "shares", "share quantity"),
    "opened": ("opened date", "open date", "date acquired", "acquired", "purchase date", "acquisition date"),
    "closed": ("closed date", "close date", "date sold", "sold", "sale date", "date closed", "sold date"),
    "proceeds": ("proceeds", "total proceeds", "sales proceeds", "proceeds ($)"),
    "cost": ("cost basis", "cost basis ($)", "total cost", "cost", "adjusted cost basis"),
    "side": ("position", "side", "long/short"),
}


def parse_history_csv(text: str) -> dict:
    """Realized gain/loss (closed lots) export: one row per closed stock lot or option position."""
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    header_i, cols = None, {}
    for i, r in enumerate(rows[:30]):
        found = _find_columns(r, _HISTORY_COLS)
        if all(found[k] is not None for k in ("shares", "closed", "proceeds", "cost")) and (
                found["symbol"] is not None or found["description"] is not None):
            header_i, cols = i, found
            break
    if header_i is None:
        raise ValueError("Couldn't find Quantity, Closed date, Proceeds and Cost basis columns. "
                         "Export realized gain/loss (closed positions) as CSV from your broker.")
    out, skipped = [], []
    for n, r in enumerate(rows[header_i + 1:], start=header_i + 2):
        get = lambda k: r[cols[k]] if cols.get(k) is not None and cols[k] < len(r) else None
        raw = (get("symbol") or "").strip().upper()
        option = parse_option_symbol(raw) or parse_option_symbol(get("description") or "")
        if not raw and not option:
            continue
        qty, proceeds, cost = _num(get("shares")), _num(get("proceeds")), _num(get("cost"))
        opened, closed = _date(get("opened")), _date(get("closed"))
        label = raw or (get("description") or "").strip()
        if not qty or proceeds is None or cost is None or not closed:
            skipped.append({"line": n, "symbol": label, "reason": "missing quantity, proceeds, cost or closed date"})
            continue
        if option:
            contracts = abs(qty)
            if not float(contracts).is_integer():
                skipped.append({"line": n, "symbol": label, "reason": "fractional contract quantity"})
                continue
            side = (get("side") or "").strip().lower()
            short = side.startswith("short") or (not side and qty < 0)
            open_total, close_total = (abs(proceeds), abs(cost)) if short else (abs(cost), abs(proceeds))
            if open_total <= 0:
                skipped.append({"line": n, "symbol": label, "reason": "no opening premium"})
                continue
            out.append({"kind": "option", **option, "position": "short" if short else "long", "contracts": int(contracts),
                        "open_premium": round(open_total / (contracts * 100), 4),
                        "close_premium": round(close_total / (contracts * 100), 4),
                        "opened_at": opened or closed, "closed_at": closed})
        else:
            sym = raw.rstrip("*").replace(" ", "")
            if not re.fullmatch(r"[A-Z]{1,5}([.-][A-Z])?", sym) or qty <= 0 or cost <= 0:
                skipped.append({"line": n, "symbol": label, "reason": "not a long stock/ETF lot or recognized option"})
                continue
            out.append({"kind": "stock", "ticker": sym.replace(".", "-"), "shares": round(qty, 6),
                        "buy_price": round(cost / qty, 4), "sell_price": round(proceeds / qty, 4),
                        "acquired": opened, "closed_at": closed})
        if len(out) >= 1000:
            break
    return {"rows": out, "skipped": skipped,
            "columns": {k: rows[header_i][v] for k, v in cols.items() if v is not None}}


def import_rows(user_id: int, rows: list[dict], account: str | None = None) -> int:
    from database import add_user_option
    for r in rows:
        if r.get("kind") == "option":
            add_user_option(user_id, r["ticker"], r["option_type"], r["strike"], r["expiry"], r["premium"],
                            r["contracts"], r["position"], account=account)
        else:
            add_user_holding(user_id, r["ticker"], r["shares"], r["price"],
                             f"{r['acquired']} 00:00:00" if r.get("acquired") else None, account=account)
    return len(rows)


def add_money_market_cash(user_id: int, account: str | None, amount: float) -> dict | None:
    """Money-market balances are cash, not stock lots: add them to the account's entered cash balance."""
    import accounts
    import database
    if not amount or amount <= 0:
        return None
    name = database.account_name(account) or database.DEFAULT_ACCOUNT
    current = accounts._cash(user_id).get(name, {}).get("cash") or 0
    return accounts.set_cash(user_id, name, round(current + amount, 2))


def import_history(user_id: int, rows: list[dict], account: str | None = None) -> dict:
    """Closed options go through the audited manual-history path; identical rows re-import as no-ops."""
    import hashlib
    import json
    from pydantic import ValidationError
    import database
    imported, duplicates, failed = 0, 0, []
    for r in rows:
        key = "brk-" + hashlib.sha256(json.dumps([user_id, account, r], sort_keys=True).encode()).hexdigest()[:32]
        try:
            if r["kind"] == "option":
                before = database._run(f"SELECT 1 FROM accounting_events WHERE user_id={database.PH} AND idempotency_key={database.PH}",
                                       (user_id, key), "one")
                database.record_closed_option(user_id, {
                    "ticker": r["ticker"], "option_type": r["option_type"], "position": r["position"],
                    "strike": str(r["strike"]), "expiry": r["expiry"], "contracts": r["contracts"],
                    "open_premium": str(r["open_premium"]), "close_premium": str(r["close_premium"]),
                    "opened_at": r["opened_at"], "closed_at": r["closed_at"], "notes": "Imported from broker CSV",
                    "idempotency_key": key, "account": account})
            else:
                closed_at = f"{r['closed_at']} 20:00:00"
                PH = database.PH
                before = database._run(f"""SELECT 1 FROM closed_trades WHERE user_id={PH} AND ticker={PH} AND shares={PH}
                    AND buy_price={PH} AND sell_price={PH} AND closed_at={PH}""",
                    (user_id, r["ticker"], r["shares"], r["buy_price"], r["sell_price"], closed_at), "one")
                if not before:
                    pnl = (r["sell_price"] - r["buy_price"]) * r["shares"]
                    database._run(f"""INSERT INTO closed_trades (user_id, ticker, shares, buy_price, sell_price, pnl, pnl_pct,
                        acquired_at, closed_at, account) VALUES ({', '.join([PH] * 10)})""",
                        (user_id, r["ticker"], r["shares"], r["buy_price"], r["sell_price"], round(pnl, 2),
                         round(pnl / (r["buy_price"] * r["shares"]) * 100, 2), r.get("acquired"), closed_at,
                         database.account_name(account)))
            if before:
                duplicates += 1
            else:
                imported += 1
        except (ValueError, ValidationError, LookupError) as error:
            message = error.errors()[0]["msg"] if isinstance(error, ValidationError) else str(error)
            failed.append({"symbol": r["ticker"], "reason": message})
    return {"imported": imported, "duplicates": duplicates, "failed": failed}
