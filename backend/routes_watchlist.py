"""Watchlist symbols, their lists and notes, upcoming earnings, and symbol search."""

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

import market
import options_analytics
import watchlists
from api_common import get_current_user, limiter, upstream_error, valid_ticker
from database import add_to_watchlist, get_user_watchlist, remove_from_watchlist
from stock_data import get_key_metrics

router = APIRouter()


class WatchlistRequest(BaseModel):
    ticker: str
    list_name: Optional[str] = Field(None, max_length=40)


class WatchlistItemRequest(BaseModel):
    lists: list[str] = Field(..., min_length=1, max_length=watchlists.MAX_LISTS_PER_SYMBOL)
    note: Optional[str] = Field(None, max_length=500)


class ListNameRequest(BaseModel):
    name: str = Field(..., max_length=80)


class ListOrderRequest(BaseModel):
    names: list[str] = Field(..., min_length=1, max_length=watchlists.MAX_LISTS)


def _lists_call(action):
    try:
        return action()
    except watchlists.ListConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/watchlist")
def watchlist_get(user: dict = Depends(get_current_user)):
    data = watchlists.overview(int(user["user_id"]))
    return {"tickers": [item["ticker"] for item in data["items"]], **data}


@router.post("/api/watchlist/lists")
def watchlist_list_create(req: ListNameRequest, user: dict = Depends(get_current_user)):
    return _lists_call(lambda: watchlists.create(int(user["user_id"]), req.name))


@router.post("/api/watchlist/lists/order")
def watchlist_list_reorder(req: ListOrderRequest, user: dict = Depends(get_current_user)):
    return _lists_call(lambda: watchlists.reorder(int(user["user_id"]), req.names))


@router.put("/api/watchlist/lists/{name}")
def watchlist_list_rename(name: str, req: ListNameRequest, user: dict = Depends(get_current_user)):
    return _lists_call(lambda: watchlists.rename(int(user["user_id"]), name, req.name))


@router.delete("/api/watchlist/lists/{name}")
def watchlist_list_delete(name: str, user: dict = Depends(get_current_user)):
    return _lists_call(lambda: watchlists.delete(int(user["user_id"]), name))


@router.put("/api/watchlist/{ticker}")
def watchlist_update(ticker: str, req: WatchlistItemRequest, user: dict = Depends(get_current_user)):
    ticker = valid_ticker(ticker)
    result = _lists_call(lambda: watchlists.set_memberships(int(user["user_id"]), ticker, req.lists, req.note))
    if result is None:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    return result


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
    list_name = _lists_call(lambda: watchlists.clean_name(req.list_name)) if req.list_name else None
    try:
        get_key_metrics(ticker)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")
    added = add_to_watchlist(user["user_id"], ticker, list_name)
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
