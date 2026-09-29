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
    warnings.sort(key=lambda w: order[w["level"]])
    return {"warnings": warnings,
            "note": "Based only on trades recorded here. Your broker's 1099-B is authoritative. Not tax advice."}


# ── Broker CSV import ────────────────────────────────────────────────────

_COLS = {
    "symbol": ("symbol", "ticker", "security symbol", "instrument"),
    "shares": ("quantity", "qty", "shares", "share quantity", "qty (quantity)"),
    "avg": ("average cost basis", "average cost", "avg cost", "cost/share", "cost per share", "avg price",
            "average price", "price paid", "unit cost", "cost basis per share", "avg cost basis"),
    "total": ("cost basis total", "cost basis", "total cost", "cost basis ($)", "book cost", "cost"),
    "acquired": ("date acquired", "acquired", "open date", "purchase date", "trade date", "acquisition date"),
}
_SKIP = {"CASH", "PENDING", "TOTAL", "ACCOUNT", "MONEY", "SWEEP", "CORE"}


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
        names = [c.strip().lower() for c in r]
        found = {k: next((j for j, n in enumerate(names) if n in syn), None) for k, syn in _COLS.items()}
        if found["symbol"] is not None and found["shares"] is not None:
            header_i, cols = i, found
            break
    if header_i is None:
        raise ValueError("Couldn't find Symbol and Quantity columns. Export positions as CSV from your broker.")
    out, skipped = [], []
    for n, r in enumerate(rows[header_i + 1:], start=header_i + 2):
        get = lambda k: r[cols[k]] if cols.get(k) is not None and cols[k] < len(r) else None
        raw = (get("symbol") or "").strip().upper()
        if not raw:
            continue
        if "**" in raw or any(w in raw for w in _SKIP):
            skipped.append({"line": n, "symbol": raw, "reason": "cash / money market"})
            continue
        sym = raw.rstrip("*").replace(" ", "")
        if not re.fullmatch(r"[A-Z]{1,5}([.-][A-Z])?", sym):
            skipped.append({"line": n, "symbol": raw, "reason": "not a stock or ETF symbol (options aren't imported)"})
            continue
        qty = _num(get("shares"))
        if not qty or qty <= 0:
            skipped.append({"line": n, "symbol": sym, "reason": "no quantity (short positions aren't imported)"})
            continue
        avg = _num(get("avg"))
        if avg is None and _num(get("total")) is not None:
            avg = _num(get("total")) / qty
        if not avg or avg <= 0:
            skipped.append({"line": n, "symbol": sym, "reason": "no cost basis"})
            continue
        out.append({"ticker": sym.replace(".", "-"), "shares": round(qty, 6), "price": round(avg, 4),
                    "acquired": _date(get("acquired"))})
        if len(out) >= 500:
            break
    return {"rows": out, "skipped": skipped,
            "columns": {k: rows[header_i][v] for k, v in cols.items() if v is not None}}


def import_rows(user_id: int, rows: list[dict]) -> int:
    for r in rows:
        add_user_holding(user_id, r["ticker"], r["shares"], r["price"],
                         f"{r['acquired']} 00:00:00" if r.get("acquired") else None)
    return len(rows)
