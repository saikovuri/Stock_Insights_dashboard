"""Registration, login, refresh-token rotation and logout."""

import hmac
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api_common import get_current_user, limiter
from auth import create_refresh_token, create_token, hash_password, verify_password, REFRESH_EXPIRE_DAYS
from database import (
    consume_refresh_token, create_user, delete_user_refresh_tokens, get_user_by_username,
    get_user_by_username_by_id, store_refresh_token, utc_now,
)

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str
    invite_code: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


def _issue_tokens(user: dict) -> dict:
    """Create access + refresh tokens and return auth response."""
    access = create_token(user["id"], user["username"])
    refresh = create_refresh_token()
    expires_at = (utc_now() + timedelta(days=REFRESH_EXPIRE_DAYS)).isoformat()
    store_refresh_token(user["id"], refresh, expires_at)
    return {
        "token": access,
        "refresh_token": refresh,
        "user": {"id": user["id"], "username": user["username"], "display_name": user["display_name"]},
    }


@router.post("/api/auth/register")
@limiter.limit("5/minute")
def register(request: Request, req: RegisterRequest):
    # Unset = open sign-up; set REGISTRATION_CODE to make new accounts invite-only
    code = os.getenv("REGISTRATION_CODE", "").strip()
    if code and not hmac.compare_digest((req.invite_code or "").strip().encode(), code.encode()):
        raise HTTPException(status_code=403, detail="A valid invite code is required to create an account")
    if len(req.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if len(req.password.encode()) > 72:
        raise HTTPException(status_code=400, detail="Password must be at most 72 bytes")
    hashed = hash_password(req.password)
    user = create_user(req.username.strip(), hashed, req.display_name.strip())
    if not user:
        raise HTTPException(status_code=409, detail="Username already taken")
    return _issue_tokens(user)


@router.post("/api/auth/login")
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest):
    user = get_user_by_username(req.username.strip())
    if not user or len(req.password.encode()) > 72 or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return _issue_tokens(user)


@router.post("/api/auth/refresh")
@limiter.limit("30/minute")
def refresh(request: Request, req: RefreshRequest):
    stored = consume_refresh_token(req.refresh_token)
    if not stored:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    expires = datetime.fromisoformat(str(stored["expires_at"]).replace("+00:00", "").replace("Z", ""))
    if utc_now() > expires:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    user = get_user_by_username_by_id(stored["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return _issue_tokens(user)


@router.post("/api/auth/logout")
def logout(user: dict = Depends(get_current_user)):
    delete_user_refresh_tokens(user["user_id"])
    return {"message": "Logged out"}


@router.get("/api/auth/me")
def auth_me(user: dict = Depends(get_current_user)):
    db_user = get_user_by_username(user["username"])
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": db_user["id"], "username": db_user["username"], "display_name": db_user["display_name"]}
