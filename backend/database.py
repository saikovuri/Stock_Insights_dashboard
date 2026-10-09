import sqlite3
import os
import json
import math
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Naive UTC, matching the timestamps already stored by datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

DATABASE_URL = os.getenv("DATABASE_URL")
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
    from psycopg2 import pool as pg_pool

DB_PATH = os.getenv("STOCKPILOT_DB_PATH", os.path.join(os.path.dirname(__file__), "stockinsights.db"))
DEFAULT_ACCOUNT = "Default"


def account_name(value) -> str | None:
    """Stored account label; the default account is stored as NULL."""
    value = (value or "").strip()
    return None if not value or value == DEFAULT_ACCOUNT else value


def in_account(row: dict, account: str | None) -> bool:
    return account is None or (row.get("account") or DEFAULT_ACCOUNT) == account


def _quantity(value, name, *, integer=False, zero=False):
    if not math.isfinite(value) or value < 0 or (not zero and value == 0) or (integer and int(value) != value):
        raise ValueError(f"Invalid {name}")


def _option_values(option_type, position, strike, expiry, premium, contracts):
    if option_type not in {"call", "put"} or position not in {"long", "short"}:
        raise ValueError("Invalid option type or position")
    datetime.strptime(expiry, "%Y-%m-%d")
    _quantity(strike, "strike")
    _quantity(premium, "premium", zero=True)
    _quantity(contracts, "contracts", integer=True)

# ── Placeholder helper ──────────────────────────────────────────────────
# SQLite uses ?, PostgreSQL uses %s
PH = "%s" if USE_PG else "?"

# ── Lazy connection pool ────────────────────────────────────────────────
_pg_pool_instance = None

def _get_pg_pool():
    global _pg_pool_instance
    if _pg_pool_instance is None:
        _pg_pool_instance = pg_pool.ThreadedConnectionPool(2, 20, DATABASE_URL)
    return _pg_pool_instance


def get_db():
    if USE_PG:
        conn = _get_pg_pool().getconn()
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _release(conn):
    """Return a PG connection to the pool, or close SQLite."""
    if USE_PG:
        _get_pg_pool().putconn(conn)
    else:
        conn.close()


def _fetchone(cur):
    """Return a dict from cursor's last fetchone, works for both SQLite and PG."""
    if USE_PG:
        if cur.description is None:
            return None
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else None
    else:
        row = cur.fetchone()
        return dict(row) if row else None


def _fetchall(cur):
    """Return list of dicts from cursor's fetchall."""
    if USE_PG:
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    else:
        return [dict(r) for r in cur.fetchall()]


def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    cur = conn.cursor()

    if USE_PG:
        # PostgreSQL schema
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS holdings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                ticker TEXT NOT NULL,
                shares DOUBLE PRECISION NOT NULL,
                buy_price DOUBLE PRECISION NOT NULL,
                date_added TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS options (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                ticker TEXT NOT NULL,
                option_type TEXT NOT NULL,
                position TEXT NOT NULL DEFAULT 'long',
                strike DOUBLE PRECISION NOT NULL,
                expiry TEXT NOT NULL,
                premium DOUBLE PRECISION NOT NULL,
                contracts INTEGER NOT NULL DEFAULT 1,
                date_added TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                action TEXT NOT NULL,
                ticker TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                ticker TEXT NOT NULL,
                added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, ticker)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS closed_trades (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                ticker TEXT NOT NULL,
                shares DOUBLE PRECISION NOT NULL,
                buy_price DOUBLE PRECISION NOT NULL,
                sell_price DOUBLE PRECISION NOT NULL,
                pnl DOUBLE PRECISION NOT NULL,
                pnl_pct DOUBLE PRECISION NOT NULL,
                closed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS closed_options (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                ticker TEXT NOT NULL,
                option_type TEXT NOT NULL,
                position TEXT NOT NULL,
                strike DOUBLE PRECISION NOT NULL,
                expiry TEXT NOT NULL,
                open_premium DOUBLE PRECISION NOT NULL,
                close_premium DOUBLE PRECISION NOT NULL,
                contracts INTEGER NOT NULL,
                pnl DOUBLE PRECISION NOT NULL,
                pnl_pct DOUBLE PRECISION NOT NULL,
                closed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                kind TEXT NOT NULL,
                ticker TEXT,
                title TEXT NOT NULL,
                body TEXT,
                data TEXT,
                dedup_key TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                read_at TIMESTAMPTZ,
                UNIQUE(user_id, dedup_key)
            )
        """)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ntfy_topic TEXT")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS iv_history (
                ticker TEXT NOT NULL,
                day TEXT NOT NULL,
                iv DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (ticker, day)
            )
        """)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trader_profile TEXT")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_alerts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                ticker TEXT NOT NULL,
                kind TEXT NOT NULL,
                value DOUBLE PRECISION NOT NULL,
                note TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                triggered_at TIMESTAMPTZ
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS journal (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                ticker TEXT NOT NULL,
                side TEXT NOT NULL DEFAULT 'long',
                shares DOUBLE PRECISION NOT NULL,
                entry_date TEXT NOT NULL,
                entry_price DOUBLE PRECISION NOT NULL,
                exit_date TEXT,
                exit_price DOUBLE PRECISION,
                stop DOUBLE PRECISION,
                target DOUBLE PRECISION,
                setup TEXT,
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kv_cache (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.commit()
    else:
        # SQLite schema
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                shares REAL NOT NULL,
                buy_price REAL NOT NULL,
                date_added TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                option_type TEXT NOT NULL,
                position TEXT NOT NULL DEFAULT 'long',
                strike REAL NOT NULL,
                expiry TEXT NOT NULL,
                premium REAL NOT NULL,
                contracts INTEGER NOT NULL DEFAULT 1,
                date_added TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                ticker TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, ticker)
            );
            CREATE TABLE IF NOT EXISTS closed_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                shares REAL NOT NULL,
                buy_price REAL NOT NULL,
                sell_price REAL NOT NULL,
                pnl REAL NOT NULL,
                pnl_pct REAL NOT NULL,
                closed_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS closed_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                option_type TEXT NOT NULL,
                position TEXT NOT NULL,
                strike REAL NOT NULL,
                expiry TEXT NOT NULL,
                open_premium REAL NOT NULL,
                close_premium REAL NOT NULL,
                contracts INTEGER NOT NULL,
                pnl REAL NOT NULL,
                pnl_pct REAL NOT NULL,
                closed_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                ticker TEXT,
                title TEXT NOT NULL,
                body TEXT,
                data TEXT,
                dedup_key TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                read_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, dedup_key)
            );
            CREATE TABLE IF NOT EXISTS iv_history (
                ticker TEXT NOT NULL,
                day TEXT NOT NULL,
                iv REAL NOT NULL,
                PRIMARY KEY (ticker, day)
            );
            CREATE TABLE IF NOT EXISTS user_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                kind TEXT NOT NULL,
                value REAL NOT NULL,
                note TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                triggered_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL DEFAULT 'long',
                shares REAL NOT NULL,
                entry_date TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_date TEXT,
                exit_price REAL,
                stop REAL,
                target REAL,
                setup TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS kv_cache (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        cols = [r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
        if "ntfy_topic" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN ntfy_topic TEXT")
        if "trader_profile" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN trader_profile TEXT")
        conn.commit()

    serial = "SERIAL PRIMARY KEY" if USE_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMPTZ NOT NULL DEFAULT NOW()" if USE_PG else "TEXT NOT NULL DEFAULT (datetime('now'))"
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS theses (
            id {serial},
            user_id INTEGER NOT NULL REFERENCES users(id),
            ticker TEXT NOT NULL,
            thesis TEXT NOT NULL,
            next_earnings TEXT,
            last_check TEXT,
            last_checked_at TEXT,
            created_at {ts},
            updated_at {ts},
            UNIQUE(user_id, ticker)
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS idea_log (
            id {serial},
            kind TEXT NOT NULL,
            label TEXT,
            ticker TEXT NOT NULL,
            expiry TEXT NOT NULL,
            legs TEXT NOT NULL,
            legs_key TEXT NOT NULL,
            net DOUBLE PRECISION NOT NULL,
            risk DOUBLE PRECISION,
            spot DOUBLE PRECISION NOT NULL,
            delta DOUBLE PRECISION,
            created_day TEXT NOT NULL,
            settle_price DOUBLE PRECISION,
            pnl DOUBLE PRECISION,
            UNIQUE(kind, ticker, expiry, legs_key)
        )
    """)
    if USE_PG:
        cur.execute("ALTER TABLE public.idea_log ENABLE ROW LEVEL SECURITY")
    for column in ("opened_at", "notes"):
        if USE_PG:
            cur.execute(f"ALTER TABLE closed_options ADD COLUMN IF NOT EXISTS {column} TEXT")
        elif column not in [r[1] for r in cur.execute("PRAGMA table_info(closed_options)").fetchall()]:
            cur.execute(f"ALTER TABLE closed_options ADD COLUMN {column} TEXT")
    conn.commit()

    # ── Indexes (idempotent for both PG and SQLite) ──
    idx = conn.cursor()
    idx_stmts = [
        "CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_holdings_ticker ON holdings(user_id, ticker)",
        "CREATE INDEX IF NOT EXISTS idx_options_user ON options(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_closed_trades_user ON closed_trades(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_closed_options_user ON closed_options(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token ON refresh_tokens(token)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_user_alerts_active ON user_alerts(active)",
        "CREATE INDEX IF NOT EXISTS idx_journal_user ON journal(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_idea_log_open ON idea_log(pnl, expiry)",
    ]
    for stmt in idx_stmts:
        idx.execute(stmt)
    # Columns must exist before audit triggers are rebuilt so snapshots include them.
    added_columns = {table: {"account": "TEXT"} for table in ("holdings", "options", "closed_trades", "closed_options", "journal")}
    added_columns["watchlist"] = {"list_name": "TEXT", "note": "TEXT"}
    for table, columns in added_columns.items():
        for column, datatype in columns.items():
            if USE_PG:
                idx.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {datatype}")
            elif column not in [row[1] for row in idx.execute(f"PRAGMA table_info({table})").fetchall()]:
                idx.execute(f"ALTER TABLE {table} ADD COLUMN {column} {datatype}")
    from accounting import install_audit_schema
    install_audit_schema(conn, USE_PG)
    from research_universe import install_schema
    install_schema(conn, USE_PG)
    import accounts
    accounts.install_schema(conn, USE_PG)
    for column, datatype in {"cost_per_share": "DOUBLE PRECISION", "cost_model": "TEXT"}.items():
        if USE_PG:
            idx.execute(f"ALTER TABLE idea_log ADD COLUMN IF NOT EXISTS {column} {datatype}")
        elif column not in [row[1] for row in idx.execute("PRAGMA table_info(idea_log)").fetchall()]:
            idx.execute(f"ALTER TABLE idea_log ADD COLUMN {column} {datatype}")
    conn.commit()
    _release(conn)


# ── User operations ──────────────────────────────────────────────────────

def create_user(username: str, password_hash: str, display_name: str) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            f"INSERT INTO users (username, password_hash, display_name) VALUES ({PH}, {PH}, {PH})",
            (username, password_hash, display_name),
        )
        conn.commit()
        cur.execute(f"SELECT id, username, display_name FROM users WHERE username = {PH}", (username,))
        return _fetchone(cur)
    except Exception:
        conn.rollback()
        return None
    finally:
        _release(conn)


def get_user_by_username(username: str) -> dict | None:
    return _run(f"SELECT * FROM users WHERE username = {PH}", (username,), "one")


def get_user_by_username_by_id(user_id: int) -> dict | None:
    return _run(f"SELECT * FROM users WHERE id = {PH}", (user_id,), "one")


# ── Holdings operations ──────────────────────────────────────────────────

def get_user_holdings(user_id: int) -> list[dict]:
    return _run(f"SELECT * FROM holdings WHERE user_id = {PH} ORDER BY id", (user_id,), "all")


def add_user_holding(user_id: int, ticker: str, shares: float, buy_price: float,
                     acquired: str | None = None, *, account: str | None = None, _conn=None) -> dict:
    _quantity(shares, "shares")
    _quantity(buy_price, "price", zero=True)
    conn = _conn or get_db()
    try:
        cur = conn.cursor()
        cols, vals = "user_id, ticker, shares, buy_price, account", [user_id, ticker.upper(), shares, buy_price, account_name(account)]
        if acquired:
            cols += ", date_added"
            vals.append(acquired)
        ph = ", ".join([PH] * len(vals))
        if USE_PG:
            cur.execute(f"INSERT INTO holdings ({cols}) VALUES ({ph}) RETURNING *", tuple(vals))
            new_row = _fetchone(cur)
        else:
            cur.execute(f"INSERT INTO holdings ({cols}) VALUES ({ph})", tuple(vals))
            cur.execute(f"SELECT * FROM holdings WHERE id = {PH}", (cur.lastrowid,))
            new_row = _fetchone(cur)
        cur.execute(
            f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'BUY', {PH}, {PH})",
            (user_id, ticker.upper(), json.dumps({"shares": shares, "price": buy_price})),
        )
        if _conn is None:
            conn.commit()
        return new_row
    except Exception:
        if _conn is None:
            conn.rollback()
        raise
    finally:
        if _conn is None:
            _release(conn)


def update_user_holding(user_id: int, holding_id: int, ticker: str, shares: float, buy_price: float,
                        account=..., acquired: str | None = None) -> dict | None:
    _quantity(shares, "shares")
    _quantity(buy_price, "price", zero=True)
    conn = get_db()
    try:
        cur = conn.cursor()
        extra, values = ("", ()) if account is ... else (f", account={PH}", (account_name(account),))
        if acquired:
            extra += f", date_added={PH}"
            values += (f"{acquired} 00:00:00",)
        cur.execute(
            f"UPDATE holdings SET ticker={PH}, shares={PH}, buy_price={PH}{extra} WHERE id={PH} AND user_id={PH}",
            (ticker.upper(), shares, buy_price, *values, holding_id, user_id),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return None
        cur.execute(
            f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'EDIT', {PH}, {PH})",
            (user_id, ticker.upper(), json.dumps({"shares": shares, "price": buy_price})),
        )
        conn.commit()
        cur.execute(f"SELECT * FROM holdings WHERE id = {PH}", (holding_id,))
        return _fetchone(cur)
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def delete_user_holding(user_id: int, holding_id: int) -> dict | None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM holdings WHERE id={PH} AND user_id={PH}", (holding_id, user_id))
        removed = _fetchone(cur)
        if not removed:
            conn.rollback()
            return None
        cur.execute(f"DELETE FROM holdings WHERE id={PH} AND user_id={PH}", (holding_id, user_id))
        cur.execute(
            f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'DELETE', {PH}, {PH})",
            (user_id, removed["ticker"], json.dumps({"shares": removed["shares"]})),
        )
        conn.commit()
        return removed
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def sell_user_holding(user_id: int, ticker: str, shares: float, sell_price: float,
                      account: str | None = None) -> dict | None:
    _quantity(shares, "shares")
    _quantity(sell_price, "price", zero=True)
    conn = get_db()
    ticker = ticker.upper()
    try:
        cur = conn.cursor()
        if not USE_PG:
            cur.execute("BEGIN IMMEDIATE")
        cur.execute(f"SELECT * FROM holdings WHERE user_id={PH} AND ticker={PH} ORDER BY date_added, id"
                    + (" FOR UPDATE" if USE_PG else ""), (user_id, ticker))
        lots = [lot for lot in _fetchall(cur) if in_account(lot, account)]
        if not lots:
            return None
        if shares > sum(lot["shares"] for lot in lots):
            raise ValueError("Sale exceeds recorded shares")
        left, pnl = shares, 0.0
        for lot in lots:
            if left <= 0:
                break
            result = sell_user_holding_by_lot(user_id, lot["id"], min(left, lot["shares"]), sell_price, _conn=conn)
            left -= result["shares"]
            pnl += result["pnl"]
        conn.commit()
        return {"action": "SELL", "ticker": ticker, "shares": shares, "sell_price": sell_price, "pnl": round(pnl, 2)}
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def sell_user_holding_by_lot(user_id: int, holding_id: int, shares: float, sell_price: float, *, _conn=None,
                             closed_at: str | None = None) -> dict | None:
    """Sell shares from a specific lot (holding_id)."""
    _quantity(shares, "shares")
    _quantity(sell_price, "price", zero=True)
    if _conn is None:
        conn = get_db()
        try:
            if not USE_PG:
                conn.execute("BEGIN IMMEDIATE")
            result = sell_user_holding_by_lot(user_id, holding_id, shares, sell_price, _conn=conn, closed_at=closed_at)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            _release(conn)
    conn = _conn or get_db()
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM holdings WHERE id={PH} AND user_id={PH}" + (" FOR UPDATE" if USE_PG else ""), (holding_id, user_id)
    )
    row = _fetchone(cur)
    if not row:
        if _conn is None:
            _release(conn)
        return None
    h = row
    if shares > h["shares"]:
        if _conn is None:
            _release(conn)
        raise ValueError("Sale exceeds shares in this lot")
    sold_shares = min(shares, h["shares"])
    if shares >= h["shares"]:
        cur.execute(f"DELETE FROM holdings WHERE id={PH}", (h["id"],))
    else:
        cur.execute(f"UPDATE holdings SET shares = shares - {PH} WHERE id={PH}", (sold_shares, h["id"]))
    pnl = (sell_price - h["buy_price"]) * sold_shares
    invested = h["buy_price"] * sold_shares
    pnl_pct = (pnl / invested * 100) if invested else 0
    dated = ", closed_at" if closed_at else ""
    cur.execute(
        f"INSERT INTO closed_trades (user_id, ticker, shares, buy_price, sell_price, pnl, pnl_pct, source_lot_id, acquired_at, account{dated}) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}{f', {PH}' if closed_at else ''})",
        (user_id, h["ticker"], sold_shares, h["buy_price"], sell_price, round(pnl, 2), round(pnl_pct, 2), h["id"], str(h.get("date_added") or "")[:10] or None, h.get("account"),
         *((closed_at,) if closed_at else ())),
    )
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'SELL', {PH}, {PH})",
        (user_id, h["ticker"], json.dumps({"shares": sold_shares, "price": sell_price, "buy_price": h["buy_price"], "pnl": round(pnl, 2)})),
    )
    if _conn is None:
        conn.commit()
        _release(conn)
    return {"action": "SELL", "ticker": h["ticker"], "shares": sold_shares, "sell_price": sell_price, "pnl": round(pnl, 2)}


# ── Options operations ──────────────────────────────────────────────────

def get_user_options(user_id: int) -> list[dict]:
    return _run(f"SELECT * FROM options WHERE user_id = {PH} ORDER BY id", (user_id,), "all")


def add_user_option(user_id: int, ticker: str, option_type: str, strike: float,
                    expiry: str, premium: float, contracts: int, position: str = "long",
                    account: str | None = None) -> dict:
    _option_values(option_type, position, strike, expiry, premium, contracts)
    conn = get_db()
    try:
        cur = conn.cursor()
        action = "BTO" if position == "long" else "STO"
        values = (user_id, ticker.upper(), option_type.lower(), position.lower(), strike, expiry, premium, contracts, account_name(account))
        sql = f"INSERT INTO options (user_id, ticker, option_type, position, strike, expiry, premium, contracts, account) VALUES ({', '.join([PH] * 9)})"
        if USE_PG:
            cur.execute(sql + " RETURNING *", values)
            new_row = _fetchone(cur)
        else:
            cur.execute(sql, values)
            cur.execute(f"SELECT * FROM options WHERE id = {PH}", (cur.lastrowid,))
            new_row = _fetchone(cur)
        cur.execute(
            f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, {PH}, {PH}, {PH})",
            (user_id, f"{action}_{option_type.upper()}", ticker.upper(),
             json.dumps({"strike": strike, "expiry": expiry, "premium": premium, "contracts": contracts})),
        )
        conn.commit()
        return new_row
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def close_user_option(user_id: int, ticker: str, option_type: str, strike: float,
                      expiry: str, close_premium: float, contracts: int, position: str = "long",
                      *, option_id: int | None = None, closed_at: str | None = None, _conn=None) -> dict | None:
    _option_values(option_type, position, strike, expiry, close_premium, contracts)
    if _conn is None:
        conn = get_db()
        try:
            if not USE_PG:
                conn.execute("BEGIN IMMEDIATE")
            result = close_user_option(user_id, ticker, option_type, strike, expiry, close_premium,
                                       contracts, position, option_id=option_id, closed_at=closed_at, _conn=conn)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            _release(conn)
    conn = _conn or get_db()
    cur = conn.cursor()
    ticker = ticker.upper()
    query = f"SELECT * FROM options WHERE user_id={PH} AND ticker={PH} AND option_type={PH} AND position={PH} AND strike={PH} AND expiry={PH}"
    params = (user_id, ticker, option_type.lower(), position.lower(), strike, expiry)
    if option_id is not None:
        query += f" AND id={PH}"
        params += (option_id,)
    cur.execute(query + " ORDER BY id" + (" FOR UPDATE" if USE_PG else ""), params)
    rows = _fetchall(cur)
    if len(rows) > 1:
        if _conn is None:
            conn.rollback()
            _release(conn)
        raise ValueError("Select an option lot to close")
    row = rows[0] if rows else None
    if not row:
        if _conn is None:
            _release(conn)
        return None
    opt = row
    if contracts > opt["contracts"]:
        if _conn is None:
            conn.rollback()
            _release(conn)
        raise ValueError("Close exceeds contracts in this lot")
    if contracts >= opt["contracts"]:
        cur.execute(f"DELETE FROM options WHERE id={PH}", (opt["id"],))
        closed = opt["contracts"]
    else:
        cur.execute(f"UPDATE options SET contracts = contracts - {PH} WHERE id={PH}", (contracts, opt["id"]))
        closed = contracts
    if position.lower() == "long":
        pnl = (close_premium - opt["premium"]) * closed * 100
    else:
        pnl = (opt["premium"] - close_premium) * closed * 100
    cost_basis = opt["premium"] * closed * 100
    pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0
    columns = "user_id, ticker, option_type, position, strike, expiry, open_premium, close_premium, contracts, pnl, pnl_pct, opened_at, source_lot_id, account"
    values = (user_id, ticker, option_type.lower(), position.lower(), strike, expiry, opt["premium"], close_premium, closed,
              round(pnl, 2), round(pnl_pct, 2), str(opt.get("date_added") or "")[:10] or None, opt["id"], opt.get("account"))
    if closed_at:
        columns += ", closed_at"
        values += (closed_at,)
    cur.execute(f"INSERT INTO closed_options ({columns}) VALUES ({', '.join([PH] * len(values))})"
                + (" RETURNING id" if USE_PG else ""), values)
    closed_id = _fetchone(cur)["id"] if USE_PG else cur.lastrowid
    close_action = "STC" if position == "long" else "BTC"
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, {PH}, {PH}, {PH})",
        (user_id, f"{close_action}_{option_type.upper()}", ticker,
         json.dumps({"strike": strike, "expiry": expiry, "premium": close_premium, "contracts": closed, "pnl": round(pnl, 2)})),
    )
    if _conn is None:
        conn.commit()
        _release(conn)
    return {"action": close_action, "ticker": ticker, "type": option_type, "strike": strike,
            "expiry": expiry, "close_premium": close_premium, "contracts": closed, "pnl": round(pnl, 2),
            "closed_id": closed_id}


def assign_user_option(user_id: int, option_id: int) -> dict:
    """Record physical assignment atomically against the selected lot."""
    conn = get_db()
    try:
        cur = conn.cursor()
        if not USE_PG:
            cur.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if USE_PG else ""
        cur.execute(f"SELECT * FROM options WHERE id={PH} AND user_id={PH}" + lock, (option_id, user_id))
        opt = _fetchone(cur)
        if not opt:
            raise LookupError("Option not found")
        if opt["position"] != "short":
            raise ValueError("Only short options get assigned")
        if opt["ticker"].lstrip("^") in {"SPX", "XSP", "NDX", "RUT", "VIX", "DJX", "OEX"}:
            raise ValueError("Cash-settled index options must be closed at their settlement value")
        shares = 100 * opt["contracts"]
        cur.execute(f"SELECT * FROM holdings WHERE user_id={PH} AND ticker={PH} ORDER BY date_added, id" + lock,
                    (user_id, opt["ticker"]))
        lots = [lot for lot in _fetchall(cur) if lot.get("account") == opt.get("account")]
        if opt["option_type"] == "call" and sum(lot["shares"] for lot in lots) < shares:
            raise ValueError(f"Assignment needs {shares} recorded shares in the option's account")
        closed = close_user_option(user_id, opt["ticker"], opt["option_type"], opt["strike"], opt["expiry"], 0.0,
                                   opt["contracts"], "short", option_id=option_id, _conn=conn)
        pnl = 0.0
        if opt["option_type"] == "put":
            add_user_holding(user_id, opt["ticker"], shares, opt["strike"], account=opt.get("account"), _conn=conn)
        else:
            left = shares
            for lot in lots:
                if left <= 0:
                    break
                result = sell_user_holding_by_lot(user_id, lot["id"], min(left, lot["shares"]), opt["strike"], _conn=conn)
                left -= result["shares"]
                pnl += result["pnl"]
        cur.execute(f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'ASSIGN', {PH}, {PH})",
                    (user_id, opt["ticker"], json.dumps({"option_id": option_id, "shares": shares})))
        conn.commit()
        return {"action": "ASSIGNED_PUT" if opt["option_type"] == "put" else "CALLED_AWAY",
                "ticker": opt["ticker"], "shares": shares, "price": opt["strike"], "pnl": round(pnl, 2),
                "closed_id": closed["closed_id"], "contracts": opt["contracts"]}
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def update_user_option(user_id: int, option_id: int, ticker: str, option_type: str,
                       strike: float, expiry: str, premium: float, contracts: int,
                       position: str = "long", account=...) -> dict | None:
    _option_values(option_type, position, strike, expiry, premium, contracts)
    conn = get_db()
    try:
        cur = conn.cursor()
        extra, values = ("", ()) if account is ... else (f", account={PH}", (account_name(account),))
        cur.execute(
            f"UPDATE options SET ticker={PH}, option_type={PH}, position={PH}, strike={PH}, expiry={PH}, premium={PH}, contracts={PH}{extra} WHERE id={PH} AND user_id={PH}",
            (ticker.upper(), option_type.lower(), position.lower(), strike, expiry, premium, contracts, *values, option_id, user_id),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return None
        cur.execute(
            f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'EDIT_OPTION', {PH}, {PH})",
            (user_id, ticker.upper(), json.dumps({"strike": strike, "expiry": expiry})),
        )
        conn.commit()
        cur.execute(f"SELECT * FROM options WHERE id = {PH}", (option_id,))
        return _fetchone(cur)
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def delete_user_option(user_id: int, option_id: int) -> dict | None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM options WHERE id={PH} AND user_id={PH}", (option_id, user_id))
        removed = _fetchone(cur)
        if not removed:
            conn.rollback()
            return None
        cur.execute(f"DELETE FROM options WHERE id={PH} AND user_id={PH}", (option_id, user_id))
        cur.execute(
            f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'DELETE_OPTION', {PH}, {PH})",
            (user_id, removed["ticker"], json.dumps({"strike": removed["strike"]})),
        )
        conn.commit()
        return removed
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def get_user_transactions(user_id: int) -> list[dict]:
    return _run(f"SELECT * FROM transactions WHERE user_id={PH} ORDER BY created_at DESC", (user_id,), "all")


# ── Watchlist operations ─────────────────────────────────────────────────

def get_user_watchlist(user_id: int) -> list[str]:
    rows = _run(f"SELECT ticker FROM watchlist WHERE user_id={PH} ORDER BY added_at", (user_id,), "all")
    return [r["ticker"] for r in rows]


def add_to_watchlist(user_id: int, ticker: str, list_name: str | None = None) -> bool:
    try:
        _run(f"INSERT INTO watchlist (user_id, ticker, list_name) VALUES ({PH}, {PH}, {PH})",
             (user_id, ticker.upper(), (list_name or "").strip() or None))
        return True
    except Exception:
        return False


def remove_from_watchlist(user_id: int, ticker: str) -> bool:
    _run(f"DELETE FROM watchlist_lists WHERE user_id={PH} AND ticker={PH}", (user_id, ticker.upper()))
    return _run(f"DELETE FROM watchlist WHERE user_id={PH} AND ticker={PH}", (user_id, ticker.upper())) > 0


# ── Closed trades operations ─────────────────────────────────────────────

def get_closed_trades(user_id: int) -> list[dict]:
    rows = _run(f"SELECT * FROM closed_trades WHERE user_id={PH} ORDER BY closed_at DESC", (user_id,), "all")
    if rows:
        from accounting import report
        details = {lot["source_id"]: lot for lot in report(user_id)["tax_lots"] if lot["source"] == "closed_trades"}
        for row in rows:
            detail = details.get(row["id"], {})
            row["ledger_event_id"] = detail.get("opening_event_id")
            row["review"] = detail.get("review")
            row["fees"] = detail.get("fees")
            row["net_pnl"] = detail.get("gain")
    return rows


def _reverse_closed_option_entries(cur, user_id, trade_id, *, contracts=None, deleting=False):
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import uuid4
    from accounting import _active_manual
    from portfolio_models import AccountingEntryRequest

    cur.execute(f"SELECT * FROM accounting_events WHERE user_id={PH} ORDER BY id", (user_id,))
    events = _fetchall(cur)
    targets = {event["id"] for event in events if event["source"] == "closed_options" and event["source_id"] == trade_id}
    entries = [(event, json.loads(event["after_json"])) for event in _active_manual(events)]
    entries = [(event, payload) for event, payload in entries if payload.get("event_id") in targets]
    linked = sum((Decimal(payload["quantity"]) for _, payload in entries if payload["kind"] == "link"), Decimal("0"))
    if contracts is not None and linked > contracts:
        raise ValueError("Reverse cycle allocations before reducing contracts below the linked quantity")
    for event, payload in entries:
        if payload["kind"] != "fee" and not (deleting and payload["kind"] == "link"):
            continue
        reversal = AccountingEntryRequest(kind="reverse", event_id=event["id"], occurred_at=datetime.now(timezone.utc),
            note="Historical option removed" if deleting else "Historical option corrected", idempotency_key=uuid4().hex)
        cur.execute(f"""INSERT INTO accounting_events(user_id, source, source_id, operation, after_json, idempotency_key)
            VALUES ({PH}, 'manual', {PH}, 'REVERSE', {PH}, {PH})""",
            (user_id, event["id"], json.dumps(reversal.model_dump(mode="json")), reversal.idempotency_key))


def record_closed_option(user_id: int, request, *, trade_id: int | None = None) -> dict:
    from decimal import Decimal
    from uuid import uuid4
    from portfolio_models import ClosedOptionRequest, AccountingEntryRequest

    request = ClosedOptionRequest.model_validate(request)
    payload = request.model_dump(mode="json")
    if payload.get("account") is None:
        payload.pop("account", None)  # keeps retries of entries recorded before accounts existed comparable
    source = "closed_option_import" if trade_id is None else "closed_option_edit"
    conn = get_db()
    try:
        cur = conn.cursor()
        if USE_PG:
            cur.execute(f"SELECT id FROM users WHERE id={PH} FOR UPDATE", (user_id,))
        else:
            cur.execute("BEGIN IMMEDIATE")
        cur.execute(f"SELECT * FROM accounting_events WHERE user_id={PH} AND idempotency_key={PH}",
                    (user_id, request.idempotency_key))
        previous = _fetchone(cur)
        if previous:
            if previous["source"] != source or (trade_id is not None and previous["source_id"] != trade_id) or json.loads(previous["after_json"]) != payload:
                raise ValueError("Request key already used for a different entry")
            cur.execute(f"SELECT * FROM closed_options WHERE user_id={PH} AND id={PH}", (user_id, previous["source_id"]))
            result = _fetchone(cur)
            if result is None:
                raise ValueError("This historical entry was already recorded and later removed")
        else:
            pnl = (request.close_premium - request.open_premium) * request.contracts * 100
            if request.position == "short":
                pnl = -pnl
            pnl = pnl.quantize(Decimal("0.01"))
            pnl_pct = (pnl / (request.open_premium * request.contracts * 100) * 100).quantize(Decimal("0.01"))
            values = (request.ticker, request.option_type, request.position, float(request.strike),
                      request.expiry.isoformat(), float(request.open_premium), float(request.close_premium),
                      request.contracts, float(pnl), float(pnl_pct), request.opened_at.isoformat(),
                      request.closed_at.isoformat(), request.notes, account_name(request.account))
            if trade_id is None:
                cur.execute(f"""INSERT INTO closed_options
                    (user_id, ticker, option_type, position, strike, expiry, open_premium, close_premium,
                     contracts, pnl, pnl_pct, opened_at, closed_at, notes, account)
                    VALUES ({', '.join([PH] * 15)})""" + (" RETURNING id" if USE_PG else ""), (user_id, *values))
                trade_id = _fetchone(cur)["id"] if USE_PG else cur.lastrowid
            else:
                cur.execute(f"""SELECT id FROM closed_options WHERE user_id={PH} AND id={PH}
                    AND EXISTS (SELECT 1 FROM accounting_events WHERE user_id={PH} AND source_id={PH}
                        AND source='closed_option_import')""", (user_id, trade_id, user_id, trade_id))
                if not _fetchone(cur):
                    raise LookupError("Manual closed option not found")
                _reverse_closed_option_entries(cur, user_id, trade_id, contracts=request.contracts)
                cur.execute(f"""UPDATE closed_options SET ticker={PH}, option_type={PH}, position={PH}, strike={PH}, expiry={PH},
                    open_premium={PH}, close_premium={PH}, contracts={PH}, pnl={PH}, pnl_pct={PH}, opened_at={PH}, closed_at={PH}, notes={PH}, account={PH}
                    WHERE user_id={PH} AND id={PH}""", (*values, user_id, trade_id))
            cur.execute(f"SELECT id FROM accounting_events WHERE user_id={PH} AND source='closed_options' AND source_id={PH} AND operation='INSERT' ORDER BY id DESC",
                        (user_id, trade_id))
            event_id = _fetchone(cur)["id"]
            if request.fees:
                fee = AccountingEntryRequest(kind="fee", amount=request.fees,
                    occurred_at=f"{request.closed_at.isoformat()}T00:00:00+00:00", event_id=event_id,
                    note="Total recorded fees for historical option trade", idempotency_key=uuid4().hex)
                cur.execute(f"""INSERT INTO accounting_events(user_id, source, source_id, operation, after_json, idempotency_key)
                    VALUES ({PH}, 'manual', 0, 'FEE', {PH}, {PH})""",
                    (user_id, json.dumps(fee.model_dump(mode="json")), fee.idempotency_key))
            cur.execute(f"""INSERT INTO accounting_events(user_id, source, source_id, operation, after_json, idempotency_key)
                VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH})""",
                (user_id, source, trade_id, "IMPORT" if source == "closed_option_import" else "EDIT", json.dumps(payload), request.idempotency_key))
            cur.execute(f"SELECT * FROM closed_options WHERE user_id={PH} AND id={PH}", (user_id, trade_id))
            result = _fetchone(cur)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def get_closed_options(user_id: int) -> list[dict]:
    rows = _run(f"""SELECT closed_options.*, EXISTS (SELECT 1 FROM accounting_events event
        WHERE event.user_id=closed_options.user_id AND event.source_id=closed_options.id
        AND event.source='closed_option_import') AS is_manual
        FROM closed_options WHERE user_id={PH} ORDER BY closed_at DESC""", (user_id,), "all")
    if rows:
        from accounting import report
        details = {lot["source_id"]: lot for lot in report(user_id)["tax_lots"] if lot["source"] == "closed_options"}
        for row in rows:
            detail = details.get(row["id"], {})
            row["ledger_event_id"] = detail.get("opening_event_id")
            row["review"] = detail.get("review")
            row["fees"] = detail.get("fees", 0)
            row["net_pnl"] = round(row["pnl"] - row["fees"], 2)
    return rows


def delete_closed_trade(user_id: int, trade_id: int) -> bool:
    return _run(f"DELETE FROM closed_trades WHERE id={PH} AND user_id={PH}", (trade_id, user_id)) > 0


def delete_closed_option(user_id: int, trade_id: int) -> bool:
    conn = get_db()
    try:
        cur = conn.cursor()
        if USE_PG:
            cur.execute(f"SELECT id FROM users WHERE id={PH} FOR UPDATE", (user_id,))
        else:
            cur.execute("BEGIN IMMEDIATE")
        cur.execute(f"SELECT id FROM closed_options WHERE user_id={PH} AND id={PH}", (user_id, trade_id))
        if not _fetchone(cur):
            conn.rollback()
            return False
        cur.execute(f"SELECT id FROM accounting_events WHERE user_id={PH} AND source_id={PH} AND source='closed_option_import'",
                    (user_id, trade_id))
        if _fetchone(cur):
            _reverse_closed_option_entries(cur, user_id, trade_id, deleting=True)
        cur.execute(f"DELETE FROM closed_options WHERE id={PH} AND user_id={PH}", (trade_id, user_id))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


# ── Refresh token operations ─────────────────────────────────────────────

def _token_digest(token: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()


def store_refresh_token(user_id: int, token: str, expires_at: str) -> None:
    """Only a SHA-256 digest is stored, so a database leak does not expose usable session tokens."""
    _run(f"INSERT INTO refresh_tokens (user_id, token, expires_at) VALUES ({PH}, {PH}, {PH})",
         (user_id, _token_digest(token), expires_at))


def consume_refresh_token(token: str) -> dict | None:
    """Atomically delete and return a refresh token so concurrent requests cannot reuse it.
    Rows stored before hashing hold the raw token; they are accepted once and replaced by a hashed one.
    Issued tokens are URL-safe base64 (no ':'), so a stored 'sha256:' digest can never match as a raw token."""
    candidates = (_token_digest(token),) if ":" in token else (_token_digest(token), token)
    return _run(f"DELETE FROM refresh_tokens WHERE token IN ({', '.join([PH] * len(candidates))}) RETURNING *",
                candidates, "one")


def delete_user_refresh_tokens(user_id: int) -> None:
    _run(f"DELETE FROM refresh_tokens WHERE user_id = {PH}", (user_id,))


def cleanup_expired_refresh_tokens() -> None:
    _run(f"DELETE FROM refresh_tokens WHERE expires_at < {PH}", (utc_now().isoformat(),))


# ── Notifications ─────────────────────────────────────────────────────────────────

def add_notification(user_id: int, kind: str, title: str, body: str, dedup_key: str,
                     ticker: str | None = None, data: dict | None = None) -> bool:
    """Insert unless (user_id, dedup_key) exists. Returns True if a row was inserted."""
    conn = get_db()
    cur = conn.cursor()
    verb = "INSERT INTO" if USE_PG else "INSERT OR IGNORE INTO"
    suffix = " ON CONFLICT (user_id, dedup_key) DO NOTHING" if USE_PG else ""
    try:
        cur.execute(
            f"{verb} notifications (user_id, kind, ticker, title, body, data, dedup_key) "
            f"VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}){suffix}",
            (user_id, kind, ticker, title, body, json.dumps(data) if data else None, dedup_key),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def delete_notification(user_id: int, dedup_key: str) -> None:
    _run(f"DELETE FROM notifications WHERE user_id={PH} AND dedup_key={PH}", (user_id, dedup_key))


def _decode_notification(row: dict) -> dict:
    if "data" in row:
        row["data"] = json.loads(row["data"]) if row["data"] else None
    for k in ("created_at", "read_at"):
        if row.get(k) is not None:
            row[k] = str(row[k])
    return row


def get_notification(user_id: int, dedup_key: str) -> dict | None:
    row = _run(f"SELECT * FROM notifications WHERE user_id={PH} AND dedup_key={PH}", (user_id, dedup_key), "one")
    return _decode_notification(row) if row else None


def list_notifications(user_id: int, limit: int = 50) -> list[dict]:
    rows = _run(
        f"SELECT id, kind, ticker, title, body, created_at, read_at FROM notifications "
        f"WHERE user_id={PH} ORDER BY created_at DESC, id DESC LIMIT {PH}",
        (user_id, limit), "all",
    )
    return [_decode_notification(r) for r in rows]


def mark_notifications_read(user_id: int) -> None:
    now = utc_now().strftime("%Y-%m-%d %H:%M:%S")
    _run(f"UPDATE notifications SET read_at={PH} WHERE user_id={PH} AND read_at IS NULL", (now, user_id))


def delete_old_notifications(days: int = 30) -> None:
    from datetime import timedelta
    cutoff = (utc_now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    _run(f"DELETE FROM notifications WHERE created_at < {PH}", (cutoff,))


def get_all_user_tickers() -> dict[int, set[str]]:
    """Map of user_id -> tickers they hold or watch (for scheduled alerts/briefings)."""
    rows = _run("SELECT user_id, ticker FROM holdings UNION SELECT user_id, ticker FROM watchlist", (), "all")
    out: dict[int, set[str]] = {}
    for r in rows:
        out.setdefault(r["user_id"], set()).add(r["ticker"].upper())
    return out


def get_option_user_ids() -> list[int]:
    return [r["user_id"] for r in _run("SELECT DISTINCT user_id FROM options", (), "all")]


def get_ntfy_topic(user_id: int) -> str | None:
    row = _run(f"SELECT ntfy_topic FROM users WHERE id={PH}", (user_id,), "one")
    return row["ntfy_topic"] if row else None


def set_ntfy_topic(user_id: int, topic: str | None) -> None:
    _run(f"UPDATE users SET ntfy_topic={PH} WHERE id={PH}", (topic, user_id))


# ── Implied volatility history (for true IV rank) ─────────────────────────────────

def record_iv(ticker: str, day: str, iv: float) -> None:
    conn = get_db()
    cur = conn.cursor()
    sql = (f"INSERT INTO iv_history (ticker, day, iv) VALUES ({PH}, {PH}, {PH}) "
           + ("ON CONFLICT (ticker, day) DO UPDATE SET iv = EXCLUDED.iv" if USE_PG
              else "ON CONFLICT (ticker, day) DO UPDATE SET iv = excluded.iv"))
    try:
        cur.execute(sql, (ticker.upper(), day, iv))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def get_iv_history(ticker: str, since_day: str) -> list[float]:
    rows = _run(f"SELECT iv FROM iv_history WHERE ticker={PH} AND day >= {PH} ORDER BY day",
                (ticker.upper(), since_day), "all")
    return [float(r["iv"]) for r in rows]


# ── Generic helpers ──────────────────────────────────────────────────────────────────

def _run(sql: str, params: tuple = (), fetch: str | None = None):
    """Execute one statement; fetch='one'|'all' returns rows, otherwise returns rowcount/lastrowid."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        if fetch == "one":
            result = _fetchone(cur)
        elif fetch == "all":
            result = _fetchall(cur)
        else:
            result = cur.rowcount
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def _stringify(rows):
    for r in rows:
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat()
    return rows


# ── Trader profile ───────────────────────────────────────────────────────────────────

def get_trader_profile(user_id: int) -> str | None:
    row = _run(f"SELECT trader_profile FROM users WHERE id={PH}", (user_id,), "one")
    return row["trader_profile"] if row else None


def set_trader_profile(user_id: int, profile: str) -> None:
    _run(f"UPDATE users SET trader_profile={PH} WHERE id={PH}", (profile, user_id))


# ── Custom price/indicator alerts ─────────────────────────────────────────────────

def list_user_alerts(user_id: int, ticker: str | None = None) -> list[dict]:
    if ticker:
        rows = _run(f"SELECT * FROM user_alerts WHERE user_id={PH} AND ticker={PH} ORDER BY id DESC",
                    (user_id, ticker.upper()), "all")
    else:
        rows = _run(f"SELECT * FROM user_alerts WHERE user_id={PH} ORDER BY active DESC, id DESC", (user_id,), "all")
    return _stringify(rows)


def count_active_alerts(user_id: int) -> int:
    row = _run(f"SELECT COUNT(*) AS n FROM user_alerts WHERE user_id={PH} AND active=1", (user_id,), "one")
    return int(row["n"]) if row else 0


def add_user_alert(user_id: int, ticker: str, kind: str, value: float, note: str | None) -> None:
    _run(f"INSERT INTO user_alerts (user_id, ticker, kind, value, note) VALUES ({PH}, {PH}, {PH}, {PH}, {PH})",
         (user_id, ticker.upper(), kind, value, note))


def delete_user_alert(user_id: int, alert_id: int) -> bool:
    return _run(f"DELETE FROM user_alerts WHERE id={PH} AND user_id={PH}", (alert_id, user_id)) > 0


def get_active_alerts() -> list[dict]:
    return _run("SELECT * FROM user_alerts WHERE active=1", (), "all")


def mark_alert_triggered(alert_id: int) -> bool:
    """Returns False if another worker already triggered it."""
    now = utc_now().strftime("%Y-%m-%d %H:%M:%S")
    return _run(f"UPDATE user_alerts SET active=0, triggered_at={PH} WHERE id={PH} AND active=1",
                (now, alert_id)) > 0


# ── Trade journal ────────────────────────────────────────────────────────────────────

_JOURNAL_FIELDS = ("ticker", "side", "shares", "entry_date", "entry_price", "exit_date", "exit_price",
                   "stop", "target", "setup", "notes", "account")


def list_journal(user_id: int) -> list[dict]:
    return _stringify(_run(f"SELECT * FROM journal WHERE user_id={PH} ORDER BY entry_date DESC, id DESC",
                           (user_id,), "all"))


def add_journal(user_id: int, entry: dict) -> None:
    cols = ", ".join(_JOURNAL_FIELDS)
    ph = ", ".join([PH] * (len(_JOURNAL_FIELDS) + 1))
    _run(f"INSERT INTO journal (user_id, {cols}) VALUES ({ph})",
         (user_id, *[entry.get(f) for f in _JOURNAL_FIELDS]))


def update_journal(user_id: int, entry_id: int, entry: dict) -> bool:
    sets = ", ".join(f"{f}={PH}" for f in _JOURNAL_FIELDS)
    return _run(f"UPDATE journal SET {sets} WHERE id={PH} AND user_id={PH}",
                (*[entry.get(f) for f in _JOURNAL_FIELDS], entry_id, user_id)) > 0


def delete_journal(user_id: int, entry_id: int) -> bool:
    return _run(f"DELETE FROM journal WHERE id={PH} AND user_id={PH}", (entry_id, user_id)) > 0


# ── Investment theses ─────────────────────────────────────────────────────────────────────────

def _decode_thesis(row: dict | None) -> dict | None:
    if row:
        row["last_check"] = json.loads(row["last_check"]) if row.get("last_check") else None
        _stringify([row])
    return row


def get_thesis(user_id: int, ticker: str) -> dict | None:
    return _decode_thesis(_run(f"SELECT * FROM theses WHERE user_id={PH} AND ticker={PH}",
                               (user_id, ticker.upper()), "one"))


def list_theses(user_id: int | None = None) -> list[dict]:
    if user_id is None:
        rows = _run("SELECT * FROM theses", (), "all")
    else:
        rows = _run(f"SELECT * FROM theses WHERE user_id={PH} ORDER BY ticker", (user_id,), "all")
    return [_decode_thesis(r) for r in rows]


def save_thesis(user_id: int, ticker: str, thesis: str, next_earnings: str | None) -> None:
    now = utc_now().strftime("%Y-%m-%d %H:%M:%S")
    _run(f"INSERT INTO theses (user_id, ticker, thesis, next_earnings, updated_at) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}) "
         f"ON CONFLICT (user_id, ticker) DO UPDATE SET thesis=excluded.thesis, next_earnings=excluded.next_earnings, "
         f"updated_at=excluded.updated_at", (user_id, ticker.upper(), thesis, next_earnings, now))


def save_thesis_check(thesis_id: int, check: dict, next_earnings: str | None) -> None:
    now = utc_now().strftime("%Y-%m-%d %H:%M:%S")
    _run(f"UPDATE theses SET last_check={PH}, last_checked_at={PH}, next_earnings={PH} WHERE id={PH}",
         (json.dumps(check), now, next_earnings, thesis_id))


def delete_thesis(user_id: int, ticker: str) -> bool:
    return _run(f"DELETE FROM theses WHERE user_id={PH} AND ticker={PH}", (user_id, ticker.upper())) > 0


# ── Persistent key/value cache (survives restarts; used for nightly scans) ──────────

def kv_get(key: str) -> dict | None:
    row = _run(f"SELECT data, updated_at FROM kv_cache WHERE key={PH}", (key,), "one")
    if not row:
        return None
    return {"data": json.loads(row["data"]), "updated_at": str(row["updated_at"])}


def kv_set(key: str, data) -> None:
    now = utc_now().strftime("%Y-%m-%d %H:%M:%S")
    _run(f"INSERT INTO kv_cache (key, data, updated_at) VALUES ({PH}, {PH}, {PH}) "
         f"ON CONFLICT (key) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
         (key, json.dumps(data), now))


# ── Idea track record ─────────────────────────────────────────────────────────────────────────

_IDEA_COLS = ("kind", "label", "ticker", "expiry", "legs", "legs_key", "net", "risk", "spot", "delta", "created_day", "cost_per_share", "cost_model")


def log_ideas(rows: list[dict]) -> None:
    """Insert ideas; one already logged for the same contract(s) is kept as first shown."""
    if not rows:
        return
    verb = "INSERT INTO" if USE_PG else "INSERT OR IGNORE INTO"
    suffix = " ON CONFLICT (kind, ticker, expiry, legs_key) DO NOTHING" if USE_PG else ""
    sql = f"{verb} idea_log ({', '.join(_IDEA_COLS)}) VALUES ({', '.join([PH] * len(_IDEA_COLS))}){suffix}"
    conn = get_db()
    cur = conn.cursor()
    try:
        for r in rows:
            cur.execute(sql, tuple(json.dumps(r[c]) if c == "legs" else r.get(c) for c in _IDEA_COLS))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _release(conn)


def unsettled_ideas(through_day: str) -> list[dict]:
    rows = _run(f"SELECT * FROM idea_log WHERE pnl IS NULL AND expiry <= {PH}", (through_day,), "all")
    for r in rows:
        r["legs"] = json.loads(r["legs"])
    return rows


def settle_idea(idea_id: int, price: float, pnl: float) -> None:
    _run(f"UPDATE idea_log SET settle_price={PH}, pnl={PH} WHERE id={PH}", (price, pnl, idea_id))


def idea_log_rows() -> list[dict]:
    return _run("SELECT kind, label, ticker, expiry, net, risk, delta, created_day, settle_price, pnl, cost_per_share, cost_model FROM idea_log",
                (), "all")


# Initialize DB on import
init_db()
