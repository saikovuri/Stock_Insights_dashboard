import bcrypt
import jwt
import os
import secrets
from datetime import datetime, timedelta, timezone

_default_secret = "stock-insights-dev-only-secret"
SECRET_KEY = os.getenv("JWT_SECRET", _default_secret)
if SECRET_KEY == _default_secret and os.getenv("DATABASE_URL"):
    raise RuntimeError("JWT_SECRET must be set in production (DATABASE_URL is present but JWT_SECRET is missing)")

ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_EXPIRE_DAYS = int(os.getenv("REFRESH_EXPIRE_DAYS", "30"))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: int, username: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        payload["sub"] = int(payload["sub"])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
