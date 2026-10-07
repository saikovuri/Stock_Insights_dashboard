"""Company research endpoints: analyst ratings, financial statements, ownership, dividends and sparklines."""

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from api_common import limiter, upstream_error, valid_ticker
from cache import get_or_fetch
from providers import finnhub_basic_financials, finnhub_insider_transactions, finnhub_recommendations
from stock_data import get_stock_data

router = APIRouter()


def _is_nan(value) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _records(frame, limit: int) -> list[dict]:
    """DataFrame rows as JSON-safe dicts: dates as YYYY-MM-DD, numbers as floats, NaN dropped."""
    rows = []
    for _, row in frame.head(limit).iterrows():
        item = {}
        for col in frame.columns:
            val = row[col]
            if val is None or _is_nan(val):
                continue
            if hasattr(val, "strftime"):
                item[col] = val.strftime("%Y-%m-%d")
            elif isinstance(val, (int, float)):
                item[col] = float(val)
            else:
                item[col] = str(val)
        rows.append(item)
    return rows


@router.get("/api/stock/{ticker}/analyst")
@limiter.limit("120/minute")
def stock_analyst(request: Request, ticker: str):
    """Analyst recommendations, price targets, and upgrade/downgrade history."""
    ticker = valid_ticker(ticker)

    def _fetch():
        import yfinance as yf
        stock = yf.Ticker(ticker)
        try:
            info = stock.info or {}
        except Exception:
            info = {}

        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        target_mean = info.get("targetMeanPrice")
        target_median = info.get("targetMedianPrice")
        num_analysts = info.get("numberOfAnalystOpinions", 0)
        recommendation = info.get("recommendationKey", "")
        recommendation_mean = info.get("recommendationMean")

        breakdown = {"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}
        fh_recs = finnhub_recommendations(ticker)
        if fh_recs:
            for col in breakdown:
                breakdown[col] = int(fh_recs[0].get(col) or 0)
        try:
            recs = None if fh_recs else stock.recommendations
            if recs is not None and not recs.empty:
                latest = recs.iloc[-1] if len(recs) > 0 else None
                if latest is not None:
                    for col in ["strongBuy", "buy", "hold", "sell", "strongSell"]:
                        val = latest.get(col)
                        if val is not None and not _is_nan(val):
                            breakdown[col] = int(val)
        except Exception:
            pass
        total = sum(breakdown.values())
        if not recommendation_mean and total:
            # Yahoo's 1 (strong buy) .. 5 (strong sell) scale, derived from the Finnhub breakdown
            recommendation_mean = round(sum(w * breakdown[k] for w, k in enumerate(breakdown, 1)) / total, 2)
            recommendation = ("strong_buy" if recommendation_mean <= 1.5 else "buy" if recommendation_mean <= 2.5
                              else "hold" if recommendation_mean <= 3.5 else "sell" if recommendation_mean <= 4.5
                              else "strong_sell")

        upgrades = []
        try:
            ug = stock.upgrades_downgrades
            if ug is not None and not ug.empty:
                for idx, row in ug.head(10).iterrows():
                    cur_pt = row.get("currentPriceTarget")
                    prior_pt = row.get("priorPriceTarget")
                    upgrades.append({
                        "date": str(idx)[:10],
                        "firm": str(row.get("Firm", "")),
                        "toGrade": str(row.get("ToGrade", "")),
                        "fromGrade": str(row.get("FromGrade", "")),
                        "action": str(row.get("Action", "")),
                        "priceTargetAction": str(row.get("priceTargetAction", "")),
                        "currentPriceTarget": None if (cur_pt is None or _is_nan(cur_pt)) else float(cur_pt),
                        "priorPriceTarget": None if (prior_pt is None or _is_nan(prior_pt)) else float(prior_pt),
                    })
        except Exception:
            pass

        return {
            "price_targets": {"high": target_high, "low": target_low, "mean": target_mean, "median": target_median, "num_analysts": num_analysts},
            "recommendation": recommendation,
            "recommendation_mean": recommendation_mean,
            "breakdown": breakdown,
            "upgrades_downgrades": upgrades[-10:],
        }
    try:
        return get_or_fetch(f"analyst:{ticker}", _fetch, ttl=600)
    except Exception as e:
        raise upstream_error(e)


@router.get("/api/stock/{ticker}/financials")
@limiter.limit("60/minute")
def stock_financials(request: Request, ticker: str):
    """Income statement, balance sheet, cash flow (annual + quarterly)."""
    ticker = valid_ticker(ticker)

    def _fetch():
        import yfinance as yf
        stock = yf.Ticker(ticker)

        def _df_to_dict(df):
            if df is None or df.empty:
                return {}
            result = {}
            for col in df.columns:
                items = {str(idx): float(val) for idx, val in df[col].items() if val is not None and not _is_nan(val)}
                if items:
                    result[str(col)[:10]] = items
            return result

        return {
            "income_statement": _df_to_dict(stock.financials),
            "income_statement_quarterly": _df_to_dict(stock.quarterly_financials),
            "balance_sheet": _df_to_dict(stock.balance_sheet),
            "balance_sheet_quarterly": _df_to_dict(stock.quarterly_balance_sheet),
            "cash_flow": _df_to_dict(stock.cashflow),
            "cash_flow_quarterly": _df_to_dict(stock.quarterly_cashflow),
        }
    try:
        return get_or_fetch(f"financials:{ticker}", _fetch, ttl=600)
    except Exception as e:
        raise upstream_error(e)


@router.get("/api/stock/{ticker}/ownership")
@limiter.limit("60/minute")
def stock_ownership(request: Request, ticker: str):
    """Top institutional holders and insider transactions."""
    ticker = valid_ticker(ticker)

    def _fetch():
        import yfinance as yf
        stock = yf.Ticker(ticker)
        try:
            info = stock.info or {}
        except Exception:
            info = {}

        institutions = []
        try:
            ih = stock.institutional_holders
            if ih is not None and not ih.empty:
                institutions = _records(ih, 15)
        except Exception:
            pass

        insiders = []
        try:
            it = stock.insider_transactions
            if it is not None and not it.empty:
                insiders = _records(it, 20)
        except Exception:
            pass
        if not insiders:
            # Finnhub fallback (Form 4 data); codes per SEC Form 4 instructions
            codes = {"P": "Purchase", "S": "Sale", "A": "Award/Grant", "M": "Option Exercise",
                     "F": "Tax Withholding", "G": "Gift", "C": "Conversion", "X": "Option Exercise"}
            for t in finnhub_insider_transactions(ticker)[:20]:
                change, price = t.get("change") or 0, t.get("transactionPrice") or 0
                insiders.append({
                    "Insider": t.get("name"),
                    "Transaction": codes.get(t.get("transactionCode"), t.get("transactionCode") or ""),
                    "Shares": change,
                    "Value": round(abs(change) * price, 2) if price else None,
                    "Date": t.get("transactionDate"),
                })

        held_pct_insiders = info.get("heldPercentInsiders")
        held_pct_institutions = info.get("heldPercentInstitutions")
        return {
            "held_pct_insiders": round(held_pct_insiders * 100, 2) if held_pct_insiders else None,
            "held_pct_institutions": round(held_pct_institutions * 100, 2) if held_pct_institutions else None,
            "institutional_holders": institutions,
            "insider_transactions": insiders,
        }
    try:
        return get_or_fetch(f"ownership:{ticker}", _fetch, ttl=600)
    except Exception as e:
        raise upstream_error(e)


@router.get("/api/stock/{ticker}/dividends")
@limiter.limit("60/minute")
def stock_dividends(request: Request, ticker: str):
    """Dividend history, yield, payout details."""
    ticker = valid_ticker(ticker)

    def _fetch():
        import yfinance as yf
        stock = yf.Ticker(ticker)
        try:
            info = stock.info or {}
        except Exception:
            info = {}

        div_rate = info.get("dividendRate")
        div_yield = info.get("dividendYield")
        ex_date = info.get("exDividendDate")
        payout_ratio = info.get("payoutRatio")
        five_yr_avg = info.get("fiveYearAvgDividendYield")
        if div_yield is None:
            # Finnhub fallback (percent units, like yfinance's dividendYield)
            m = finnhub_basic_financials(ticker) or {}
            div_rate = m.get("dividendIndicatedAnnual") or m.get("dividendPerShareTTM")
            div_yield = m.get("currentDividendYieldTTM")
            if m.get("payoutRatioTTM") is not None:
                payout_ratio = m["payoutRatioTTM"] / 100

        ex_date_str = None
        if ex_date:
            try:
                ex_date_str = datetime.fromtimestamp(ex_date).strftime("%Y-%m-%d")
            except Exception:
                ex_date_str = str(ex_date)

        history = []
        try:
            divs = stock.dividends
            if divs is not None and len(divs) > 0:
                for ts, amount in divs.items():
                    d = str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]
                    history.append({"date": d, "amount": round(float(amount), 4)})
        except Exception:
            pass
        if not ex_date_str and history:
            ex_date_str = history[-1]["date"]

        return {
            "dividend_rate": div_rate,
            "dividend_yield": round(div_yield, 2) if div_yield else None,  # yfinance already returns a percent
            "ex_dividend_date": ex_date_str,
            "payout_ratio": round(payout_ratio * 100, 1) if payout_ratio else None,
            "five_year_avg_yield": five_yr_avg,
            "history": history,
        }
    try:
        return get_or_fetch(f"dividends:{ticker}", _fetch, ttl=600)
    except Exception as e:
        raise upstream_error(e)


class SparklineRequest(BaseModel):
    tickers: list[str]


@router.post("/api/stock/batch-sparklines")
@limiter.limit("60/minute")
def batch_sparklines(request: Request, req: SparklineRequest):
    """Return 5-day close prices for tiny sparkline charts."""
    tickers = [valid_ticker(t) for t in req.tickers[:30]]
    if not tickers:
        return {"sparklines": {}}

    def _fetch_spark(t):
        try:
            df = get_stock_data(t, period="5d", interval="1d")
            return {"ticker": t, "closes": [round(float(row["Close"]), 2) for _, row in df.iterrows()]}
        except Exception:
            return {"ticker": t, "closes": []}

    with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as pool:
        results = list(pool.map(_fetch_spark, tickers))
    return {"sparklines": {r["ticker"]: r["closes"] for r in results}}
