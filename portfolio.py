import json
import os
from datetime import datetime
from config import PORTFOLIO_FILE


def _load_portfolio() -> dict:
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            return json.load(f)
    return {"holdings": [], "history": []}


def _save_portfolio(data: dict):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def add_holding(ticker: str, shares: float, buy_price: float) -> dict:
    """Add a stock to the portfolio."""
    portfolio = _load_portfolio()

    holding = {
        "ticker": ticker.upper(),
        "shares": shares,
        "buy_price": buy_price,
        "date_added": datetime.now().isoformat(),
    }
    portfolio["holdings"].append(holding)
    portfolio["history"].append({"action": "BUY", **holding})
    _save_portfolio(portfolio)
    return holding


def remove_holding(ticker: str, shares: float, sell_price: float) -> dict | None:
    """Remove shares from portfolio. Returns the transaction or None."""
    portfolio = _load_portfolio()
    ticker = ticker.upper()

    for h in portfolio["holdings"]:
        if h["ticker"] == ticker:
            if shares >= h["shares"]:
                portfolio["holdings"].remove(h)
                sold_shares = h["shares"]
            else:
                h["shares"] -= shares
                sold_shares = shares

            txn = {
                "action": "SELL",
                "ticker": ticker,
                "shares": sold_shares,
                "sell_price": sell_price,
                "date": datetime.now().isoformat(),
            }
            portfolio["history"].append(txn)
            _save_portfolio(portfolio)
            return txn

    return None


def get_holdings() -> list[dict]:
    """Return current holdings."""
    return _load_portfolio()["holdings"]


def get_portfolio_summary(current_prices: dict[str, float]) -> dict:
    """Calculate portfolio value and P/L given current prices.

    Args:
        current_prices: mapping of ticker -> current price
    """
    holdings = get_holdings()
    total_invested = 0.0
    total_current = 0.0
    details = []

    for h in holdings:
        ticker = h["ticker"]
        shares = h["shares"]
        buy_price = h["buy_price"]
        current = current_prices.get(ticker, buy_price)

        invested = shares * buy_price
        current_val = shares * current
        pnl = current_val - invested
        pnl_pct = (pnl / invested * 100) if invested else 0

        total_invested += invested
        total_current += current_val

        details.append(
            {
                "ticker": ticker,
                "shares": shares,
                "buy_price": buy_price,
                "current_price": current,
                "invested": round(invested, 2),
                "current_value": round(current_val, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            }
        )

    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0

    return {
        "total_invested": round(total_invested, 2),
        "total_current": round(total_current, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "holdings": details,
    }


def get_history() -> list[dict]:
    """Return transaction history."""
    return _load_portfolio()["history"]
