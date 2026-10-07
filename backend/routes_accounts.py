"""Brokerage accounts, cash balances, daily account value and corporate actions (splits, spin-offs, mergers)."""

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AfterValidator, BaseModel, Field, model_validator

import accounts
import corporate_actions
from api_common import get_current_user, limiter, upstream_error, valid_ticker
from database import utc_now
from portfolio_models import ACCOUNT_PATTERN

router = APIRouter()


class CashRequest(BaseModel):
    model_config = {"extra": "forbid"}
    account: Optional[str] = Field(None, pattern=ACCOUNT_PATTERN)
    cash: float = Field(..., ge=-100_000_000, le=1_000_000_000, allow_inf_nan=False)


class SplitRequest(BaseModel):
    ticker: str
    split_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")


def _past_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Use a YYYY-MM-DD date")
    if parsed > utc_now().date():
        raise ValueError("Record corporate actions on or after their effective date")
    return value


ActionDate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$"), AfterValidator(_past_date)]


class SpinoffRequest(BaseModel):
    model_config = {"extra": "forbid"}
    ticker: str
    new_ticker: str
    action_date: ActionDate
    ratio: float = Field(..., gt=0, le=1000, allow_inf_nan=False)
    basis_pct: float = Field(..., ge=0, lt=100, allow_inf_nan=False)


class MergerRequest(BaseModel):
    model_config = {"extra": "forbid"}
    ticker: str
    action_date: ActionDate
    new_ticker: Optional[str] = None
    ratio: float = Field(0, ge=0, le=1000, allow_inf_nan=False)
    cash_per_share: float = Field(0, ge=0, le=1_000_000, allow_inf_nan=False)

    @model_validator(mode="after")
    def _terms(self):
        if self.ratio > 0 and not self.new_ticker:
            raise ValueError("A stock deal needs the acquirer's ticker")
        if self.ratio == 0 and self.cash_per_share == 0:
            raise ValueError("Enter the shares and/or cash received per share")
        if self.ratio == 0 and self.new_ticker:
            raise ValueError("Enter how many acquirer shares each share became")
        return self


def _conflicts(action):
    try:
        return action()
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/api/portfolio/accounts")
def portfolio_accounts(user: dict = Depends(get_current_user)):
    return accounts.list_accounts(int(user["user_id"]))


@router.put("/api/portfolio/cash")
@limiter.limit("30/minute")
def portfolio_cash(request: Request, req: CashRequest, user: dict = Depends(get_current_user)):
    return accounts.set_cash(int(user["user_id"]), req.account, req.cash)


@router.get("/api/portfolio/nav-history")
def portfolio_nav_history(account: Optional[str] = None, user: dict = Depends(get_current_user)):
    return accounts.nav_history(int(user["user_id"]), account)


@router.post("/api/portfolio/nav-snapshot")
@limiter.limit("4/minute")
def portfolio_nav_snapshot(request: Request, user: dict = Depends(get_current_user)):
    try:
        return {"snapshots": accounts.snapshot(int(user["user_id"]))}
    except Exception as e:
        raise upstream_error(e)


@router.get("/api/portfolio/corporate-actions")
@limiter.limit("10/minute")
def portfolio_corporate_actions(request: Request, user: dict = Depends(get_current_user)):
    uid = int(user["user_id"])
    return {"splits": corporate_actions.pending_splits(uid), "stale": corporate_actions.stale_holdings(uid),
            "applied": corporate_actions.applied_actions(uid)}


@router.post("/api/portfolio/corporate-actions/apply")
@limiter.limit("10/minute")
def portfolio_apply_split(request: Request, req: SplitRequest, user: dict = Depends(get_current_user)):
    ticker = valid_ticker(req.ticker)
    return _conflicts(lambda: corporate_actions.apply_split(int(user["user_id"]), ticker, req.split_date))


@router.post("/api/portfolio/corporate-actions/spinoff")
@limiter.limit("10/minute")
def portfolio_record_spinoff(request: Request, req: SpinoffRequest, user: dict = Depends(get_current_user)):
    parent, child = valid_ticker(req.ticker), valid_ticker(req.new_ticker)
    if parent == child:
        raise HTTPException(status_code=422, detail="The spun-off company needs a different ticker")
    return _conflicts(lambda: corporate_actions.apply_spinoff(int(user["user_id"]), parent, child, req.action_date,
                                                              req.ratio, req.basis_pct))


@router.post("/api/portfolio/corporate-actions/merger")
@limiter.limit("10/minute")
def portfolio_record_merger(request: Request, req: MergerRequest, user: dict = Depends(get_current_user)):
    target = valid_ticker(req.ticker)
    acquirer = valid_ticker(req.new_ticker) if req.new_ticker else None
    if acquirer == target:
        raise HTTPException(status_code=422, detail="The acquirer needs a different ticker")
    return _conflicts(lambda: corporate_actions.apply_merger(int(user["user_id"]), target, req.action_date, acquirer,
                                                             req.ratio, req.cash_per_share))
