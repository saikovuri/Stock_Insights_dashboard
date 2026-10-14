"""Saved Pre-Trade Checklist plans; the Journal review matches them to closed trades by ticker and date."""

import json
from datetime import datetime, timezone

import database

MAX_PLANS = 1000


def _row(row: dict) -> dict:
    return {**json.loads(row["plan"]), "id": row["id"], "ticker": row["ticker"], "created_at": row["created_at"]}


def save_plan(user_id: int, plan: dict) -> dict:
    PH = database.PH
    count = database._run(f"SELECT COUNT(*) AS n FROM trade_plans WHERE user_id={PH}", (user_id,), "one")["n"]
    if count >= MAX_PLANS:
        raise ValueError(f"You have {MAX_PLANS} saved plans; delete old ones first")
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = database._run(f"INSERT INTO trade_plans (user_id, ticker, plan, created_at) VALUES ({PH}, {PH}, {PH}, {PH}) RETURNING id",
                        (user_id, plan["ticker"], json.dumps(plan), created), "one")
    return {**plan, "id": row["id"], "created_at": created}


def list_plans(user_id: int, ticker: str | None = None, limit: int = 100) -> list[dict]:
    PH = database.PH
    where, params = f"user_id={PH}", [user_id]
    if ticker:
        where, params = where + f" AND ticker={PH}", params + [ticker]
    rows = database._run(f"SELECT * FROM trade_plans WHERE {where} ORDER BY created_at DESC, id DESC LIMIT {int(limit)}",
                         tuple(params), "all")
    return [_row(row) for row in rows]


def delete_plan(user_id: int, plan_id: int) -> bool:
    PH = database.PH
    return database._run(f"DELETE FROM trade_plans WHERE user_id={PH} AND id={PH}", (user_id, plan_id)) > 0
