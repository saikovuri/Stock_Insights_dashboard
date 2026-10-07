"""Read-only system status: what is configured, whether data providers answer, and what the scheduler last ran."""

import os
import platform
import re
import subprocess
import time
from datetime import datetime, timezone

import config
import scheduler
from cache import get_or_fetch

STARTED_AT = datetime.now(timezone.utc)
_SECRETS = [v for v in (config.FINNHUB_API_KEY, config.TWELVEDATA_API_KEY, config.GROQ_API_KEY,
                        config.GEMINI_API_KEY, config.OPENAI_API_KEY) if v]


def _version() -> str | None:
    commit = os.getenv("RENDER_GIT_COMMIT")
    if commit:
        return commit[:7]
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=os.path.dirname(os.path.abspath(__file__)),
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


VERSION = _version()


def _redact(text: str) -> str:
    for secret in _SECRETS:
        text = text.replace(secret, "***")
    return re.sub(r"(?i)(token|apikey|api_key|key)=[^&\s]+", r"\1=***", text)[:200]


def _check(name: str, fn) -> dict:
    began = time.monotonic()
    try:
        ok, detail = fn()
    except Exception as error:
        ok, detail = False, _redact(f"{type(error).__name__}: {error}")
    return {"name": name, "ok": ok, "detail": detail, "ms": round((time.monotonic() - began) * 1000)}


def _database():
    import database
    conn = database.get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
    finally:
        database._release(conn)
    return True, "PostgreSQL" if database.USE_PG else "SQLite (local file)"


def _finnhub():
    from providers import finnhub_enabled, finnhub_quote
    if not finnhub_enabled():
        return None, "Not configured: quotes come from Yahoo (slower, can be delayed). Set FINNHUB_API_KEY."
    q = finnhub_quote("SPY")
    return (True, f"SPY ${q['c']}") if q and q.get("c") else (False, "No quote returned (key invalid or rate-limited?)")


def _yahoo():
    from stock_data import get_stock_data
    df = get_stock_data("SPY", period="5d", interval="1d")
    return True, f"SPY daily bars to {df.index[-1].date()}"


def _checks() -> list[dict]:
    return [_check("Database", _database), _check("Finnhub quotes", _finnhub), _check("Yahoo price history", _yahoo)]


def report() -> dict:
    ai = [name for name, key, *_ in config._ALL_PROVIDERS if key]
    beat = scheduler.HEARTBEAT
    return {
        "version": VERSION, "started_at": STARTED_AT.isoformat(timespec="seconds"),
        "uptime_seconds": int((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
        "python": platform.python_version(),
        "checks": get_or_fetch("status:checks", _checks, ttl=300),
        "config": [
            {"name": "AI providers", "ok": bool(ai) or None,
             "detail": ", ".join(ai) + f" (tried first: {config.AI_PROVIDER})" if ai else "None: AI brief, chat and reviews fall back to rules. Set GROQ_API_KEY or GEMINI_API_KEY."},
            {"name": "Twelve Data fallback", "ok": bool(config.TWELVEDATA_API_KEY) or None,
             "detail": "Configured" if config.TWELVEDATA_API_KEY else "Not configured (optional)"},
            {"name": "Error tracking (Sentry)", "ok": bool(config.SENTRY_DSN) or None,
             "detail": "Configured" if config.SENTRY_DSN else "Not configured (optional)"},
            {"name": "Phone push (ntfy)", "ok": True, "detail": config.NTFY_SERVER},
        ],
        "scheduler": {"enabled": config.SCHEDULER_ENABLED, "started_at": beat["started_at"], "last_tick": beat["last_tick"],
                      "jobs": beat["jobs"], "last_error": beat["last_error"]},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
