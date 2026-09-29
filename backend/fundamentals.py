"""Long-term view from SEC XBRL filings: 10-year fundamentals, quality scores and valuation context."""

import logging
from datetime import datetime

import pandas as pd

from cache import get_or_fetch
from providers import _cik_map, _sec_get
from stock_data import get_key_metrics, get_stock_data

log = logging.getLogger(__name__)

DISCOUNT_RATE = 0.09
TERMINAL_GROWTH = 0.025
TAX_RATE = 0.21

FLOW = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
}
INSTANT = {
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "40-F"}


def _annual(facts: dict, tags: list[str], flow: bool, original: bool = False) -> dict[str, tuple[float, str]]:
    """Fiscal-year-end date -> (value, filed date), merging tags (companies switch tags over time).

    original=True keeps the first-filed value (as reported at the time) instead of later restatements.
    """
    out: dict[str, tuple[str, float, str]] = {}
    for tag in tags:
        node = facts.get(tag)
        if not node:
            continue
        for unit, rows in node.get("units", {}).items():
            if unit not in ("USD", "shares", "USD/shares"):
                continue
            for r in rows:
                if r.get("form") not in ANNUAL_FORMS or not r.get("end"):
                    continue
                if flow:
                    if not r.get("start"):
                        continue
                    days = (datetime.fromisoformat(r["end"]) - datetime.fromisoformat(r["start"])).days
                    if not 330 <= days <= 400:
                        continue
                end, filed = r["end"], r.get("filed", "")
                if end not in out:
                    out[end] = (filed, r["val"], tag)
                elif out[end][2] == tag and ((filed < out[end][0]) if original else (filed > out[end][0])):
                    out[end] = (filed, r["val"], tag)
    return {k: (v[1], v[0]) for k, v in out.items()}


def _cagr(first, last, years):
    if not first or not last or first <= 0 or last <= 0 or years <= 0:
        return None
    return round(((last / first) ** (1 / years) - 1) * 100, 1)


def _safe_div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def _reverse_dcf(fcf0: float, ev: float) -> float | None:
    """Annual FCF growth for 10 years that justifies today's enterprise value."""
    if not fcf0 or fcf0 <= 0 or not ev or ev <= 0:
        return None

    def pv(g):
        total, f = 0.0, fcf0
        for yr in range(1, 11):
            f *= 1 + g
            total += f / (1 + DISCOUNT_RATE) ** yr
        tv = f * (1 + TERMINAL_GROWTH) / (DISCOUNT_RATE - TERMINAL_GROWTH)
        return total + tv / (1 + DISCOUNT_RATE) ** 10

    lo, hi = -0.5, 1.0
    if pv(hi) < ev:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if pv(mid) > ev:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2 * 100, 1)


def _piotroski(cur: dict, prev: dict) -> dict:
    def ratio(d, a, b):
        return _safe_div(d.get(a), d.get(b))

    roa, roa_p = ratio(cur, "net_income", "assets"), ratio(prev, "net_income", "assets")
    lev, lev_p = ratio(cur, "long_term_debt", "assets"), ratio(prev, "long_term_debt", "assets")
    cr, cr_p = ratio(cur, "current_assets", "current_liabilities"), ratio(prev, "current_assets", "current_liabilities")
    gm, gm_p = ratio(cur, "gross_profit", "revenue"), ratio(prev, "gross_profit", "revenue")
    at, at_p = ratio(cur, "revenue", "assets"), ratio(prev, "revenue", "assets")
    checks = [
        ("Profitable (ROA > 0)", roa is not None and roa > 0),
        ("Positive operating cash flow", (cur.get("cfo") or 0) > 0),
        ("ROA improving", roa is not None and roa_p is not None and roa > roa_p),
        ("Cash flow exceeds net income", cur.get("cfo") is not None and cur.get("net_income") is not None
         and cur["cfo"] > cur["net_income"]),
        ("Leverage falling", lev is not None and lev_p is not None and lev <= lev_p),
        ("Liquidity improving", cr is not None and cr_p is not None and cr > cr_p),
        ("No share dilution", cur.get("shares") is not None and prev.get("shares") is not None
         and cur["shares"] <= prev["shares"] * 1.005),
        ("Gross margin improving", gm is not None and gm_p is not None and gm > gm_p),
        ("Asset turnover improving", at is not None and at_p is not None and at > at_p),
    ]
    return {"score": sum(1 for _, ok in checks if ok), "checks": [{"label": l, "pass": bool(ok)} for l, ok in checks]}


def _altman(cur: dict, market_cap: float | None) -> dict | None:
    ta, tl = cur.get("assets"), cur.get("liabilities")
    if not ta or not tl or not market_cap:
        return None
    wc = (cur.get("current_assets") or 0) - (cur.get("current_liabilities") or 0)
    z = (1.2 * wc / ta + 1.4 * (cur.get("retained_earnings") or 0) / ta + 3.3 * (cur.get("operating_income") or 0) / ta
         + 0.6 * market_cap / tl + 1.0 * (cur.get("revenue") or 0) / ta)
    zone = "safe" if z > 2.99 else "grey" if z > 1.81 else "distress"
    return {"z": round(z, 2), "zone": zone}


def long_term(ticker: str) -> dict:
    def _fetch():
        cik = _cik_map().get(ticker.upper().replace(".", "-"))
        if not cik:
            raise LookupError("Not an SEC filer (ETF or non-US company?)")
        cf = _sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        facts = cf.get("facts", {}).get("us-gaap", {})
        if not facts:
            raise LookupError("No XBRL financial data")

        per_share = {"eps", "shares"}
        series = {k: _annual(facts, tags, True, original=k in per_share) for k, tags in FLOW.items()}
        series.update({k: _annual(facts, tags, False) for k, tags in INSTANT.items()})
        ends = sorted(set(series["revenue"]) | set(series["net_income"]))[-10:]
        if not ends:
            raise LookupError("No annual financials found")

        monthly = None
        try:
            monthly = get_stock_data(ticker, period="10y", interval="1mo")["Close"]
            monthly.index = pd.to_datetime(monthly.index.date)
        except Exception:
            pass

        # SEC figures are as-reported; Yahoo prices are split-adjusted
        try:
            import yfinance as yf
            splits = yf.Ticker(ticker).splits
            splits.index = pd.to_datetime(splits.index.date)
        except Exception:
            splits = pd.Series(dtype=float)

        def split_factor(since: str) -> float:
            after = splits[splits.index > pd.Timestamp(since)]
            return float(after.prod()) if len(after) else 1.0

        years = []
        for end in ends:
            y = {k: series[k][end][0] if end in series[k] else None for k in series}
            # As-filed per-share figures already reflect splits before the filing date
            for k in ("eps", "shares"):
                if end in series[k]:
                    f = split_factor(series[k][end][1] or end)
                    y[k] = y[k] / f if k == "eps" else y[k] * f
            y["year"] = int(end[:4])
            y["end"] = end
            y["fcf"] = y["cfo"] - (y["capex"] or 0) if y["cfo"] is not None else None
            y["gross_margin"] = _pct(y["gross_profit"], y["revenue"])
            y["operating_margin"] = _pct(y["operating_income"], y["revenue"])
            y["net_margin"] = _pct(y["net_income"], y["revenue"])
            y["fcf_margin"] = _pct(y["fcf"], y["revenue"])
            invested = (y["equity"] or 0) + (y["long_term_debt"] or 0) - (y["cash"] or 0)
            y["roic"] = _pct(y["operating_income"] * (1 - TAX_RATE) if y["operating_income"] else None,
                             invested if invested > 0 else None)
            y["roe"] = _pct(y["net_income"], y["equity"] if (y["equity"] or 0) > 0 else None)
            price = None
            if monthly is not None:
                prior = monthly[monthly.index <= pd.Timestamp(end)]
                price = float(prior.iloc[-1]) if len(prior) else None
            y["price"] = round(price, 2) if price else None
            y["pe"] = round(price / y["eps"], 1) if price and y["eps"] and y["eps"] > 0 else None
            years.append(y)

        cur, prev = years[-1], years[-2] if len(years) > 1 else {}
        metrics = get_key_metrics(ticker)
        mcap = metrics.get("market_cap")
        n = len(years) - 1

        def growth(key, span):
            if len(years) <= span:
                return None
            return _cagr(years[-span - 1].get(key), years[-1].get(key), span)

        growth_rates = {
            "revenue_3y": growth("revenue", 3), "revenue_5y": growth("revenue", 5), "revenue_10y": growth("revenue", min(n, 9)),
            "fcf_5y": growth("fcf", 5), "eps_5y": growth("eps", 5),
            "shares_5y": growth("shares", 5),
        }

        pes = [y["pe"] for y in years if y["pe"]]
        pe_now = metrics.get("pe_ratio")
        pe_band = None
        if len(pes) >= 3 and pe_now:
            s = sorted(pes)
            pe_band = {"min": s[0], "median": s[len(s) // 2], "max": s[-1], "now": round(pe_now, 1),
                       "percentile": round(sum(1 for p in s if p < pe_now) / len(s) * 100)}

        ev = (mcap or 0) + (cur.get("long_term_debt") or 0) - (cur.get("cash") or 0)
        implied_g = _reverse_dcf(cur.get("fcf"), ev)
        hist_g = growth_rates["fcf_5y"] if growth_rates["fcf_5y"] is not None else growth_rates["revenue_5y"]
        if implied_g is None:
            dcf_verdict = "Not meaningful — free cash flow is negative or too small relative to the valuation."
        elif hist_g is None:
            dcf_verdict = f"The price implies about {implied_g}% yearly FCF growth for 10 years."
        elif implied_g <= hist_g - 3:
            dcf_verdict = (f"The price implies {implied_g}%/yr FCF growth — below the {hist_g}%/yr the business "
                           "delivered over 5 years. Expectations look modest.")
        elif implied_g >= hist_g + 5:
            dcf_verdict = (f"The price implies {implied_g}%/yr FCF growth — well above the {hist_g}%/yr of the past "
                           "5 years. The market is pricing in acceleration; little room for disappointment.")
        else:
            dcf_verdict = (f"The price implies {implied_g}%/yr FCF growth, close to the {hist_g}%/yr delivered over "
                           "5 years. Fairly priced if the track record continues.")

        dividends = _dividend_profile(ticker, cur)
        piotroski = _piotroski(cur, prev) if prev else None
        is_fin = any(w in (metrics.get("sector") or "") for w in ("Financ", "Bank", "Insurance"))
        altman = None if is_fin else _altman(cur, mcap)

        flags = []
        if (cur.get("roic") or 0) >= 15:
            flags.append(("good", f"High return on invested capital ({cur['roic']}%)"))
        elif cur.get("roic") is not None and cur["roic"] < 6:
            flags.append(("bad", f"Low return on invested capital ({cur['roic']}%)"))
        if (cur.get("fcf_margin") or 0) >= 15:
            flags.append(("good", f"Strong free-cash-flow margin ({cur['fcf_margin']}%)"))
        if growth_rates["shares_5y"] is not None:
            if growth_rates["shares_5y"] <= -1:
                flags.append(("good", f"Share count shrinking {abs(growth_rates['shares_5y'])}%/yr (buybacks)"))
            elif growth_rates["shares_5y"] >= 2:
                flags.append(("bad", f"Share count growing {growth_rates['shares_5y']}%/yr (dilution)"))
        if piotroski and piotroski["score"] <= 3:
            flags.append(("bad", f"Weak Piotroski score ({piotroski['score']}/9)"))
        if altman and altman["zone"] == "distress":
            flags.append(("bad", f"Altman Z {altman['z']} in distress zone"))
        if cur.get("fcf") is not None and cur.get("long_term_debt") and cur["fcf"] > 0:
            yrs = cur["long_term_debt"] / cur["fcf"]
            if yrs > 5:
                flags.append(("bad", f"Debt equals {yrs:.1f} years of free cash flow"))

        chart_keys = ("year", "revenue", "net_income", "fcf", "gross_margin", "operating_margin", "net_margin",
                      "fcf_margin", "roic", "roe", "shares", "eps", "pe", "dividends_paid", "buybacks")
        return {
            "ticker": ticker,
            "fiscal_year_end": cur["end"],
            "years": [{k: y.get(k) for k in chart_keys} for y in years],
            "growth": growth_rates,
            "piotroski": piotroski,
            "altman": altman,
            "valuation": {
                "pe_band": pe_band,
                "market_cap": mcap,
                "enterprise_value": ev,
                "fcf_yield_pct": _pct(cur.get("fcf"), mcap),
                "implied_fcf_growth": implied_g,
                "historical_growth": hist_g,
                "verdict": dcf_verdict,
                "assumptions": f"{int(DISCOUNT_RATE * 100)}% discount rate, {TERMINAL_GROWTH * 100}% terminal growth, 10 years",
            },
            "dividends": dividends,
            "flags": [{"type": t, "text": x} for t, x in flags],
            "source": "SEC EDGAR XBRL (annual 10-K filings)",
        }

    return get_or_fetch(f"longterm:{ticker}", _fetch, ttl=43200)


def _pct(a, b):
    v = _safe_div(a, b)
    return round(v * 100, 1) if v is not None else None


def _dividend_profile(ticker: str, cur: dict) -> dict | None:
    import yfinance as yf
    try:
        divs = yf.Ticker(ticker).dividends
    except Exception:
        return None
    if divs is None or len(divs) == 0:
        return None
    annual = divs.groupby(divs.index.year).sum()
    this_year = datetime.now().year
    annual = annual[annual.index < this_year]
    # Largest single payment per year is robust to an extra/missing payment shifting between years
    per_payment = divs.groupby(divs.index.year).max()
    per_payment = per_payment[per_payment.index < this_year]
    streak = 0
    pp = list(per_payment.values)
    yrs = list(per_payment.index)
    for i in range(len(pp) - 1, 0, -1):
        if yrs[i] - yrs[i - 1] == 1 and pp[i] >= pp[i - 1] * 0.999:
            streak += 1
        else:
            break
    vals = list(annual.values)
    payout_fcf = _pct(cur.get("dividends_paid"), cur.get("fcf") if (cur.get("fcf") or 0) > 0 else None)
    return {
        "annual": [{"year": int(y), "amount": round(float(v), 4)} for y, v in annual.tail(10).items()],
        "growth_streak_years": streak,
        "cagr_5y": _cagr(float(vals[-6]), float(vals[-1]), 5) if len(vals) >= 6 else None,
        "fcf_payout_pct": payout_fcf,
        "safety": None if payout_fcf is None else "safe" if payout_fcf < 60 else "watch" if payout_fcf < 90 else "at risk",
    }
