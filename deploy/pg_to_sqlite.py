"""Copy every StockPilot table from PostgreSQL (Supabase or local) into a new SQLite file.

Run from backend/ with the app's virtualenv:
  SOURCE_DATABASE_URL='postgresql://...' STOCKPILOT_DB_PATH=/path/new.db venv/bin/python ../deploy/pg_to_sqlite.py

The SQLite file must not exist yet. The app's own init_db() creates the schema first, so
column types and triggers match a normal SQLite install. See move_to_local_db.md.
"""
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

source_url = os.environ.get("SOURCE_DATABASE_URL")
target = os.environ.get("STOCKPILOT_DB_PATH")
if not source_url or not target:
    sys.exit("Set SOURCE_DATABASE_URL and STOCKPILOT_DB_PATH")
if os.path.exists(target):
    sys.exit(f"{target} already exists; move it away first")

os.environ["DATABASE_URL"] = ""  # empty wins over backend/.env, so database.py picks SQLite
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import database  # noqa: E402
import psycopg2  # noqa: E402

database.init_db()


def convert(value, declared_type):
    if isinstance(value, datetime):
        if value.tzinfo:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.strftime("%Y-%m-%d %H:%M:%S")  # same format as SQLite's datetime('now')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value) if "TEXT" in declared_type.upper() else float(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


source = psycopg2.connect(source_url)
lite = sqlite3.connect(target)
triggers = lite.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND sql IS NOT NULL").fetchall()
for name, _ in triggers:
    lite.execute(f'DROP TRIGGER "{name}"')  # audit triggers would log every copied row as a new change

problems = []
tables = [r[0] for r in lite.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
for table in tables:
    lite_columns = {r[1]: r[2] or "" for r in lite.execute(f'PRAGMA table_info("{table}")')}
    with source.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s",
                    (table,))
        pg_columns = {r[0] for r in cur.fetchall()}
    if not pg_columns:
        print(f"  {table}: not in the source database, left empty")
        continue
    columns = [c for c in lite_columns if c in pg_columns]
    dropped = sorted(pg_columns - set(lite_columns))
    if dropped:
        problems.append(f"{table}: source columns not in SQLite, not copied: {', '.join(dropped)}")
    quoted = ", ".join(f'"{c}"' for c in columns)
    with source.cursor() as cur:
        cur.execute(f'SELECT {quoted} FROM public."{table}"')
        rows = [tuple(convert(v, lite_columns[c]) for v, c in zip(row, columns)) for row in cur.fetchall()]
    lite.execute(f'DELETE FROM "{table}"')
    lite.executemany(f'INSERT INTO "{table}" ({quoted}) VALUES ({", ".join("?" * len(columns))})', rows)
    copied = lite.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    print(f"  {table}: {copied} rows")
    if copied != len(rows):
        problems.append(f"{table}: read {len(rows)} rows but SQLite has {copied}")

for _, sql in triggers:
    lite.execute(sql)
lite.commit()
lite.close()
source.close()

if problems:
    print("\nCheck these:\n  " + "\n  ".join(problems))
    sys.exit(1)
print(f"\nDone: {target}")
