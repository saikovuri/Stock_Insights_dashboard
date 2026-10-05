import argparse
import json
import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def install_schema(conn, postgres=False):
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS universe_snapshots (
        as_of TEXT NOT NULL, known_at TEXT NOT NULL, source TEXT NOT NULL,
        members_json TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(as_of, source)
    )""")
    if postgres:
        cursor.execute("ALTER TABLE universe_snapshots ENABLE ROW LEVEL SECURITY")
        for role in ("anon", "authenticated"):
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
            if cursor.fetchone():
                cursor.execute(f"REVOKE ALL ON universe_snapshots FROM {role}")


def save_snapshot(snapshot):
    import database
    as_of = date.fromisoformat(snapshot["as_of"])
    known_at = datetime.fromisoformat(snapshot["known_at"].replace("Z", "+00:00"))
    source = snapshot["source"].strip()
    if known_at.tzinfo is None or known_at > datetime.now(timezone.utc) or as_of > datetime.now(timezone.utc).date() or not source:
        raise ValueError("A dated source and non-future, timezone-aware publication timestamp are required")
    members = snapshot["members"]
    if not isinstance(members, list) or not members or len(members) > 10000:
        raise ValueError("Snapshot requires 1-10000 constituent symbols")
    if any(not isinstance(symbol, str) or not re.fullmatch(r"[A-Z^][A-Z0-9.^=-]{0,19}", symbol) for symbol in members):
        raise ValueError("Invalid constituent symbol")
    timestamp = known_at.astimezone(timezone.utc).isoformat()
    existing = database._run("SELECT * FROM universe_snapshots WHERE as_of=? AND source=?", (as_of.isoformat(), source), "one")
    encoded = json.dumps(sorted(set(members)))
    if existing:
        if existing["members_json"] != encoded or timestamp < existing["known_at"]:
            raise ValueError("Snapshot already exists; use a distinct, traceable source for a correction")
        return
    database._run("INSERT INTO universe_snapshots(as_of, known_at, source, members_json) VALUES (?, ?, ?, ?) ON CONFLICT(as_of, source) DO NOTHING",
                  (as_of.isoformat(), timestamp, source, encoded))


def members_at(as_of, source):
    import database
    day = date.fromisoformat(as_of).isoformat()
    cutoff = datetime.combine(date.fromisoformat(day), time(16), ZoneInfo("America/New_York")).astimezone(timezone.utc).isoformat()
    row = database._run("SELECT * FROM universe_snapshots WHERE as_of<=? AND known_at<=? AND source=? ORDER BY as_of DESC, known_at DESC LIMIT 1",
                        (day, cutoff, source), "one")
    if row is None:
        return {"as_of": day, "members": [], "available": False, "reason": "No constituent snapshot was known by this date"}
    return {"as_of": day, "snapshot_as_of": row["as_of"], "known_at": row["known_at"], "source": row["source"],
            "members": json.loads(row["members_json"]), "available": True,
            "note": "Source coverage and delisted price data must be verified independently. Observed-current snapshots are not complete historical index membership."}


def source_symbols(source):
    import database
    rows = database._run("SELECT members_json FROM universe_snapshots WHERE source=? ORDER BY as_of", (source,), "all")
    return sorted({symbol for row in rows for symbol in json.loads(row["members_json"])})


def main():
    parser = argparse.ArgumentParser(description="Import dated constituent snapshots from a documented historical provider")
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    snapshots = json.loads(args.file.read_text(encoding="utf-8"))
    if not isinstance(snapshots, list):
        raise ValueError("Expected a JSON array of snapshots")
    for snapshot in snapshots:
        save_snapshot(snapshot)
    print(f"Imported {len(snapshots)} dated constituent snapshots")


if __name__ == "__main__":
    main()