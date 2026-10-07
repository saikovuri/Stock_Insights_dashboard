"""Shared API pieces used by main.py and the route modules: rate limiter, auth dependency and validation helpers."""

import logging
import re
from typing import Optional

from fastapi import Header, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address

from auth import decode_token

log = logging.getLogger("api")

# request.client.host is the real client only because uvicorn runs with --proxy-headers and a trusted-proxy list;
# reading X-Forwarded-For directly would let any caller pick their own rate-limit bucket.
limiter = Limiter(key_func=get_remote_address)

_TICKER_RE = re.compile(r"^[A-Za-z0-9\.\-\^]{1,10}$")


def valid_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")
    return t


def upstream_error(e: Exception, status: int = 500) -> HTTPException:
    """Log the real error; return a generic message so internals aren't exposed."""
    log.warning("Request failed: %s: %s", type(e).__name__, e)
    if status == 404:
        return HTTPException(status_code=404, detail="Ticker not found or data unavailable")
    return HTTPException(status_code=status, detail="Data provider error. Please try again shortly.")


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"user_id": payload["sub"], "username": payload["username"]}
