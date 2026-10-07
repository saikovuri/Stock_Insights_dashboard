"""Watchlist symbols, their lists and notes, upcoming earnings, and symbol search."""

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

import market
import options_analytics
from api_common import get_current_user, limiter, upstream_error, valid_ticker
from database import (
    add_to_watchlist, get_user_watchlist, get_watchlist_items, remove_from_watchlist, update_watchlist_item,
)
from stock_data import get_key_metrics

router = APIRouter()


class WatchlistRequest(BaseModel):
    ticker: str
    list_name: Optional[str] = Field(None, max_length=40)


class WatchlistItemRequest(BaseModel):
    lists: list[str] = Field(..., min_length=1, max_length=10)
    note: Optional[str] = Field(None, max_length=500)

    @field_validator("lists")
    @classmethod
    def _list_lengths(cls, value):
        if any(len(name.strip()) > 40 for name in value):
            raise ValueError("List names are limited to 40 characters")
        return value


@router.get("/api/watchlist")
def watchlist_get(user: dict = Depends(get_current_user)):
    items = get_watchlist_items(user["user_id"])
    return {"tickers": [item["ticker"] for item in items], "items": items}


@router.put("/api/watchlist/{ticker}")
def watchlist_update(ticker: str, req: WatchlistItemRequest, user: dict = Depends(get_current_user)):
    if not update_watchlist_item(user["user_id"], valid_ticker(ticker), req.lists, req.note):
        raise HTTPException(status_code=404, detail="Not in watchlist")
    return {"ok": True}


@router.get("/api/watchlist/earnings")
@limiter.limit("10/minute")
def watchlist_earnings(request: Request, user: dict = Depends(get_current_user)):
    """Next earnings for watchlist symbols (canonical Finnhub + Yahoo dates, earlier date wins)."""
    tickers = get_user_watchlist(user["user_id"])[:60]
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = list(pool.map(options_analytics.earnings_info, tickers))
    return {"items": [{"ticker": t, "next": i.get("next"), "timing": i.get("next_timing"),
                       "confirmed": i.get("next_confirmed", False)} for t, i in zip(tickers, infos)]}


@router.post("/api/watchlist")
def watchlist_add(req: WatchlistRequest, user: dict = Depends(get_current_user)):
    ticker = valid_ticker(req.ticker)
    try:
        get_key_metrics(ticker)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")
    added = add_to_watchlist(user["user_id"], ticker, req.list_name)
    if not added:
        raise HTTPException(status_code=409, detail="Already in watchlist")
    return {"message": f"{ticker} added to watchlist"}


@router.delete("/api/watchlist/{ticker}")
def watchlist_remove(ticker: str, user: dict = Depends(get_current_user)):
    ticker = valid_ticker(ticker)
    removed = remove_from_watchlist(user["user_id"], ticker)
    if not removed:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    return {"message": f"{ticker} removed from watchlist"}


@router.get("/api/search")
@limiter.limit("60/minute")
def symbol_search(request: Request, q: str = Query(..., min_length=1, max_length=40)):
    try:
        return {"results": market.search_symbols(q)}
    except Exception as e:
        raise upstream_error(e)
