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


def update_holding(index: int, ticker: str, shares: float, buy_price: float) -> dict | None:
    """Update a stock holding at the given index."""
    portfolio = _load_portfolio()
    if index < 0 or index >= len(portfolio["holdings"]):
        return None
    portfolio["holdings"][index] = {
        "ticker": ticker.upper(),
        "shares": shares,
        "buy_price": buy_price,
        "date_added": portfolio["holdings"][index].get("date_added", datetime.now().isoformat()),
    }
    portfolio["history"].append({
        "action": "EDIT", "ticker": ticker.upper(),
        "shares": shares, "buy_price": buy_price,
        "date": datetime.now().isoformat(),
    })
    _save_portfolio(portfolio)
    return portfolio["holdings"][index]


def delete_holding(index: int) -> dict | None:
    """Delete a stock holding by index."""
    portfolio = _load_portfolio()
    if index < 0 or index >= len(portfolio["holdings"]):
        return None
    removed = portfolio["holdings"].pop(index)
    portfolio["history"].append({
        "action": "DELETE", "ticker": removed["ticker"],
        "shares": removed["shares"], "date": datetime.now().isoformat(),
    })
    _save_portfolio(portfolio)
    return removed


def get_portfolio_summary(current_prices: dict[str, float]) -> dict:
    """Calculate portfolio value and P/L given current prices."""
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


# ── Options tracking ────────────────────────────────────────────────────────

def add_option(
    ticker: str, option_type: str, strike: float, expiry: str,
    premium: float, contracts: int, position: str = "long",
) -> dict:
    """Add an options position. option_type: 'call'|'put'. position: 'long'|'short'."""
    portfolio = _load_portfolio()
    if "options" not in portfolio:
        portfolio["options"] = []

    action = "BTO" if position == "long" else "STO"
    option = {
        "ticker": ticker.upper(),
        "type": option_type.lower(),
        "position": position.lower(),
        "strike": strike,
        "expiry": expiry,
        "premium": premium,
        "contracts": contracts,
        "date_added": datetime.now().isoformat(),
    }
    portfolio["options"].append(option)
    portfolio["history"].append({"action": f"{action}_{option_type.upper()}", **option})
    _save_portfolio(portfolio)
    return option


def remove_option(
    ticker: str, option_type: str, strike: float, expiry: str,
    close_premium: float, contracts: int, position: str = "long",
) -> dict | None:
    """Close an options position."""
    portfolio = _load_portfolio()
    if "options" not in portfolio:
        return None

    ticker = ticker.upper()
    for opt in portfolio["options"]:
        if (opt["ticker"] == ticker and opt["type"] == option_type.lower()
                and opt.get("position", "long") == position.lower()
                and opt["strike"] == strike and opt["expiry"] == expiry):
            if contracts >= opt["contracts"]:
                portfolio["options"].remove(opt)
                closed = opt["contracts"]
            else:
                opt["contracts"] -= contracts
                closed = contracts

            close_action = "STC" if position == "long" else "BTC"
            txn = {
                "action": f"{close_action}_{option_type.upper()}",
                "ticker": ticker,
                "type": option_type.lower(),
                "strike": strike,
                "expiry": expiry,
                "close_premium": close_premium,
                "contracts": closed,
                "date": datetime.now().isoformat(),
            }
            portfolio["history"].append(txn)
            _save_portfolio(portfolio)
            return txn

    return None


def get_options() -> list[dict]:
    """Return current options positions."""
    portfolio = _load_portfolio()
    return portfolio.get("options", [])


def update_option(index: int, ticker: str, option_type: str, strike: float,
                  expiry: str, premium: float, contracts: int,
                  position: str = "long") -> dict | None:
    """Update an options position at the given index."""
    portfolio = _load_portfolio()
    opts = portfolio.get("options", [])
    if index < 0 or index >= len(opts):
        return None
    opts[index] = {
        "ticker": ticker.upper(),
        "type": option_type.lower(),
        "position": position.lower(),
        "strike": strike,
        "expiry": expiry,
        "premium": premium,
        "contracts": contracts,
        "date_added": opts[index].get("date_added", datetime.now().isoformat()),
    }
    portfolio["options"] = opts
    portfolio["history"].append({
        "action": "EDIT_OPTION", "ticker": ticker.upper(),
        "type": option_type.lower(), "strike": strike,
        "expiry": expiry, "date": datetime.now().isoformat(),
    })
    _save_portfolio(portfolio)
    return opts[index]


def delete_option(index: int) -> dict | None:
    """Delete an options position by index."""
    portfolio = _load_portfolio()
    opts = portfolio.get("options", [])
    if index < 0 or index >= len(opts):
        return None
    removed = opts.pop(index)
    portfolio["options"] = opts
    portfolio["history"].append({
        "action": "DELETE_OPTION", "ticker": removed["ticker"],
        "type": removed["type"], "strike": removed["strike"],
        "date": datetime.now().isoformat(),
    })
    _save_portfolio(portfolio)
    return removed


def get_options_summary(current_prices: dict[str, float]) -> dict:
    """Calculate options portfolio value using real Yahoo Finance option prices."""
    import yfinance as yf
    from datetime import date as _date

    options = get_options()
    details = []
    today = _date.today()

    # Index tickers that need ^ prefix for yfinance
    INDEX_MAP = {
        "SPX": "^SPX", "NDX": "^NDX", "RUT": "^RUT", "DJX": "^DJI",
        "VIX": "^VIX", "OEX": "^OEX", "XSP": "^XSP",
    }

    def _yf_ticker(ticker: str) -> str:
        """Convert display ticker to yfinance-compatible ticker."""
        return INDEX_MAP.get(ticker.upper(), ticker)

    # Cache option chains per (ticker, expiry) to avoid duplicate fetches
    chain_cache: dict[tuple[str, str], dict] = {}

    def _get_market_price(ticker: str, opt_type: str, strike: float, expiry: str) -> dict:
        """Fetch real market data for a specific option contract."""
        yf_sym = _yf_ticker(ticker)
        key = (yf_sym, expiry)
        if key not in chain_cache:
            try:
                t = yf.Ticker(yf_sym)
                # Find the closest available expiry
                available = t.options  # tuple of date strings
                if expiry in available:
                    chain = t.option_chain(expiry)
                else:
                    # Find nearest expiry
                    nearest = min(available, key=lambda e: abs(
                        (datetime.strptime(e, "%Y-%m-%d").date() - datetime.strptime(expiry, "%Y-%m-%d").date()).days
                    )) if available else None
                    chain = t.option_chain(nearest) if nearest else None
                chain_cache[key] = {
                    "calls": chain.calls if chain else None,
                    "puts": chain.puts if chain else None,
                }
            except Exception:
                chain_cache[key] = {"calls": None, "puts": None}

        cached = chain_cache[key]
        df = cached["calls"] if opt_type == "call" else cached["puts"]
        if df is None or df.empty:
            return {}

        # Find the row matching this strike
        match = df[df["strike"] == strike]
        if match.empty:
            # Find closest strike
            closest_idx = (df["strike"] - strike).abs().idxmin()
            match = df.loc[[closest_idx]]

        row = match.iloc[0]
        return {
            "last_price": float(row.get("lastPrice", 0) or 0),
            "bid": float(row.get("bid", 0) or 0),
            "ask": float(row.get("ask", 0) or 0),
            "iv": float(row.get("impliedVolatility", 0) or 0),
            "volume": int(row.get("volume", 0) or 0),
            "open_interest": int(row.get("openInterest", 0) or 0),
            "in_the_money": bool(row.get("inTheMoney", False)),
        }

    for opt in options:
        ticker = opt["ticker"]
        contracts = opt["contracts"]
        premium = opt["premium"]
        strike = opt["strike"]
        current = current_prices.get(ticker, strike)
        position = opt.get("position", "long")

        # Days to expiry
        try:
            expiry_date = datetime.strptime(opt["expiry"], "%Y-%m-%d").date()
            dte = max((expiry_date - today).days, 0)
        except (ValueError, KeyError):
            dte = 0

        # Intrinsic value per share
        if opt["type"] == "call":
            intrinsic = max(current - strike, 0)
        else:
            intrinsic = max(strike - current, 0)

        # Fetch real market price from Yahoo Finance
        market = _get_market_price(ticker, opt["type"], strike, opt["expiry"])
        if market:
            # Use mid of bid/ask if available, else lastPrice
            bid = market.get("bid", 0)
            ask = market.get("ask", 0)
            if bid > 0 and ask > 0:
                market_price = (bid + ask) / 2
            else:
                market_price = market.get("last_price", 0)
            iv = market.get("iv", 0)
            volume = market.get("volume", 0)
            oi = market.get("open_interest", 0)
        else:
            # Fallback: intrinsic only
            market_price = intrinsic
            iv = 0
            volume = 0
            oi = 0

        # Cost and P/L depend on position direction
        cost = premium * 100 * contracts
        current_value = market_price * 100 * contracts

        if position == "long":
            pnl = current_value - cost
        else:
            pnl = cost - current_value

        pnl_pct = (pnl / cost * 100) if cost else 0

        details.append({
            "ticker": ticker,
            "type": opt["type"],
            "position": position,
            "strike": strike,
            "expiry": opt["expiry"],
            "dte": dte,
            "contracts": contracts,
            "premium": premium,
            "cost": round(cost, 2),
            "current_price": current,
            "intrinsic": round(intrinsic, 2),
            "market_price": round(market_price, 2),
            "bid": round(market.get("bid", 0), 2) if market else 0,
            "ask": round(market.get("ask", 0), 2) if market else 0,
            "iv": round(iv * 100, 1),  # as percentage
            "volume": volume,
            "open_interest": oi,
            "est_value": round(market_price, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })

    total_cost = sum(d["cost"] for d in details)
    total_pnl = sum(d["pnl"] for d in details)
    total_market = sum(d["market_price"] * d["contracts"] * 100 for d in details)

    return {
        "total_cost": round(total_cost, 2),
        "total_value": round(total_market, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round((total_pnl / total_cost * 100) if total_cost else 0, 2),
        "options": details,
    }
