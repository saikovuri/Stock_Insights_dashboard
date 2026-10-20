"""Risk guard (open risk, stops, pre-trade check) and long-term investing (split, monthly plan, profit sweep, scorecard)."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

import accounts
import investing
import risk_guard
import trading_rules
from api_common import get_current_user, limiter, upstream_error, valid_ticker
from portfolio_models import ACCOUNT_PATTERN

router = APIRouter()
_TICKER = r"^[A-Za-z^][A-Za-z0-9.^=-]{0,19}$"


@router.get("/api/risk/heat")
@limiter.limit("20/minute")
def risk_heat(request: Request, user: dict = Depends(get_current_user)):
    try:
        return risk_guard.heat(int(user["user_id"]))
    except Exception as error:
        raise upstream_error(error)


class StopRequest(BaseModel):
    model_config = {"extra": "forbid"}
    account: Optional[str] = Field(None, pattern=ACCOUNT_PATTERN)
    ticker: str = Field(..., pattern=_TICKER)
    stop: Optional[float] = Field(None, gt=0, le=10_000_000, allow_inf_nan=False)


@router.put("/api/risk/stop")
@limiter.limit("60/minute")
def risk_stop(request: Request, req: StopRequest, user: dict = Depends(get_current_user)):
    return risk_guard.set_stop(int(user["user_id"]), req.account, valid_ticker(req.ticker), req.stop)


class CheckLeg(BaseModel):
    model_config = {"extra": "forbid"}
    position: Literal["long", "short"]
    option_type: Literal["call", "put"]
    strike: float = Field(..., gt=0)
    expiry: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    premium: float = Field(..., ge=0)
    ratio: int = Field(1, ge=1, le=10)


class CheckRequest(BaseModel):
    model_config = {"extra": "forbid", "allow_inf_nan": False}
    kind: Literal["stock", "option", "structure"]
    ticker: str = Field(..., pattern=_TICKER)
    account: Optional[str] = Field(None, pattern=ACCOUNT_PATTERN)
    shares: Optional[float] = Field(None, gt=0, le=100_000_000)
    price: Optional[float] = Field(None, gt=0, le=10_000_000)
    stop: Optional[float] = Field(None, gt=0, le=10_000_000)
    position: Optional[Literal["long", "short"]] = None
    option_type: Optional[Literal["call", "put"]] = None
    strike: Optional[float] = Field(None, gt=0)
    premium: Optional[float] = Field(None, ge=0)
    contracts: Optional[int] = Field(None, ge=1, le=10_000)
    legs: Optional[list[CheckLeg]] = Field(None, min_length=2, max_length=4)

    @model_validator(mode="after")
    def complete(self):
        needed = {"stock": ("shares", "price"), "option": ("position", "option_type", "strike", "premium", "contracts"),
                  "structure": ("legs", "contracts")}[self.kind]
        missing = [name for name in needed if getattr(self, name) is None]
        if missing:
            raise ValueError(f"Missing {', '.join(missing)}")
        return self


@router.post("/api/risk/check")
@limiter.limit("60/minute")
def risk_check(request: Request, req: CheckRequest, user: dict = Depends(get_current_user)):
    payload = req.model_dump()
    try:
        return risk_guard.check(int(user["user_id"]), {**payload, "ticker": valid_ticker(req.ticker)})
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise upstream_error(error)


class RoleRequest(BaseModel):
    model_config = {"extra": "forbid"}
    account: Optional[str] = Field(None, pattern=ACCOUNT_PATTERN)
    role: Literal["long_term", "trading"]


@router.put("/api/invest/role")
@limiter.limit("30/minute")
def invest_role(request: Request, req: RoleRequest, user: dict = Depends(get_current_user)):
    return accounts.set_role(int(user["user_id"]), req.account, req.role)


@router.get("/api/invest/overview")
@limiter.limit("20/minute")
def invest_overview(request: Request, user: dict = Depends(get_current_user)):
    uid = int(user["user_id"])
    rules = trading_rules.get_rules(uid)
    try:
        return {"split": investing.split(uid, rules), "plan": investing.plan_status(uid), "sweep": investing.sweep_status(uid, rules),
                "rules": {k: rules.get(k) for k in ("target_trading_pct", "profit_sweep_pct")}}
    except Exception as error:
        raise upstream_error(error)


class PlanTarget(BaseModel):
    model_config = {"extra": "forbid"}
    ticker: str = Field(..., pattern=_TICKER)
    pct: float = Field(..., gt=0, le=100)


class PlanRequest(BaseModel):
    model_config = {"extra": "forbid", "allow_inf_nan": False}
    account: Optional[str] = Field(None, pattern=ACCOUNT_PATTERN)
    monthly: float = Field(..., gt=0, le=10_000_000)
    day: int = Field(1, ge=1, le=28)
    targets: list[PlanTarget] = Field(..., min_length=1, max_length=20)
    goal: Optional[float] = Field(None, gt=0, le=1_000_000_000)
    assumed_return_pct: float = Field(7, ge=0, le=20)


@router.put("/api/invest/plan")
@limiter.limit("20/minute")
def invest_plan_save(request: Request, req: PlanRequest, user: dict = Depends(get_current_user)):
    plan = req.model_dump()
    plan["targets"] = [{"ticker": valid_ticker(t["ticker"]), "pct": t["pct"]} for t in plan["targets"]]
    try:
        investing.save_plan(int(user["user_id"]), plan)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return investing.plan_status(int(user["user_id"]))


@router.delete("/api/invest/plan")
def invest_plan_delete(user: dict = Depends(get_current_user)):
    if not investing.delete_plan(int(user["user_id"])):
        raise HTTPException(status_code=404, detail="No plan saved")
    return {"ok": True}


class SweepRequest(BaseModel):
    model_config = {"extra": "forbid", "allow_inf_nan": False}
    from_account: Optional[str] = Field(None, pattern=ACCOUNT_PATTERN)
    to_account: Optional[str] = Field(None, pattern=ACCOUNT_PATTERN)
    amount: float = Field(..., gt=0, le=1_000_000_000)


@router.post("/api/invest/sweep")
@limiter.limit("10/minute")
def invest_sweep(request: Request, req: SweepRequest, user: dict = Depends(get_current_user)):
    import database
    source = database.account_name(req.from_account) or database.DEFAULT_ACCOUNT
    target = database.account_name(req.to_account) or database.DEFAULT_ACCOUNT
    if source == target:
        raise HTTPException(status_code=400, detail="Pick two different accounts")
    try:
        return investing.record_sweep(int(user["user_id"]), source, target, round(req.amount, 2))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.get("/api/invest/scorecard")
@limiter.limit("20/minute")
def invest_scorecard(request: Request, scope: Literal["trading", "long_term", "all"] = "trading",
                     user: dict = Depends(get_current_user)):
    try:
        return investing.scorecard_cached(int(user["user_id"]), scope)
    except LookupError as error:
        raise HTTPException(status_code=503, detail=str(error))
    except Exception as error:
        raise upstream_error(error)
