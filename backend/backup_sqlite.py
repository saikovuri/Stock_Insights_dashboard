"""Consistent copy of the local SQLite database, safe while the app is running.

Usage (repo root):  .venv/Scripts/python backend/backup_sqlite.py [destination folder]
Default destination: backups/ in the repo root. Restore: stop the backend, delete backend/stockinsights.db-wal and
-shm if present, copy the backup over backend/stockinsights.db, then start the backend.
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")


def main() -> None:
    if os.getenv("DATABASE_URL"):
        sys.exit("DATABASE_URL is set, so the app uses PostgreSQL. Use deploy/backup.sh (pg_dump) instead.")
    source = Path(os.getenv("STOCKPILOT_DB_PATH", HERE / "stockinsights.db"))
    if not source.exists():
        sys.exit(f"No database at {source}")
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"stockinsights-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    print(f"Backed up {source} -> {target} ({target.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
