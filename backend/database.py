import sqlite3
import os
import json
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
    from psycopg2 import pool as pg_pool
    _pg_pool = pg_pool.ThreadedConnectionPool(2, 20, DATABASE_URL)

DB_PATH = os.path.join(os.path.dirname(__file__), "stockinsights.db")

# ── Placeholder helper ──────────────────────────────────────────────────
# SQLite uses ?, PostgreSQL uses %s
PH = "%s" if USE_PG else "?"


def get_db():
    if USE_PG:
        conn = _pg_pool.getconn()
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
        _pg_pool.putconn(conn)
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
        """)
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
    ]
    for stmt in idx_stmts:
        idx.execute(stmt)
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
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM users WHERE username = {PH}", (username,))
    result = _fetchone(cur)
    _release(conn)
    return result


def get_user_by_username_by_id(user_id: int) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM users WHERE id = {PH}", (user_id,))
    result = _fetchone(cur)
    _release(conn)
    return result


# ── Holdings operations ──────────────────────────────────────────────────

def get_user_holdings(user_id: int) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM holdings WHERE user_id = {PH} ORDER BY id", (user_id,))
    rows = _fetchall(cur)
    _release(conn)
    return rows


def add_user_holding(user_id: int, ticker: str, shares: float, buy_price: float) -> dict:
    conn = get_db()
    cur = conn.cursor()
    if USE_PG:
        cur.execute(
            f"INSERT INTO holdings (user_id, ticker, shares, buy_price) VALUES ({PH}, {PH}, {PH}, {PH}) RETURNING *",
            (user_id, ticker.upper(), shares, buy_price),
        )
        new_row = _fetchone(cur)
    else:
        cur.execute(
            f"INSERT INTO holdings (user_id, ticker, shares, buy_price) VALUES ({PH}, {PH}, {PH}, {PH})",
            (user_id, ticker.upper(), shares, buy_price),
        )
        cur.execute(f"SELECT * FROM holdings WHERE id = {PH}", (cur.lastrowid,))
        new_row = _fetchone(cur)
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'BUY', {PH}, {PH})",
        (user_id, ticker.upper(), json.dumps({"shares": shares, "price": buy_price})),
    )
    conn.commit()
    _release(conn)
    return new_row


def update_user_holding(user_id: int, holding_id: int, ticker: str, shares: float, buy_price: float) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE holdings SET ticker={PH}, shares={PH}, buy_price={PH} WHERE id={PH} AND user_id={PH}",
        (ticker.upper(), shares, buy_price, holding_id, user_id),
    )
    if cur.rowcount == 0:
        _release(conn)
        return None
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'EDIT', {PH}, {PH})",
        (user_id, ticker.upper(), json.dumps({"shares": shares, "price": buy_price})),
    )
    conn.commit()
    cur.execute(f"SELECT * FROM holdings WHERE id = {PH}", (holding_id,))
    result = _fetchone(cur)
    _release(conn)
    return result


def delete_user_holding(user_id: int, holding_id: int) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM holdings WHERE id={PH} AND user_id={PH}", (holding_id, user_id))
    row = _fetchone(cur)
    if not row:
        _release(conn)
        return None
    removed = row
    cur.execute(f"DELETE FROM holdings WHERE id={PH} AND user_id={PH}", (holding_id, user_id))
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'DELETE', {PH}, {PH})",
        (user_id, removed["ticker"], json.dumps({"shares": removed["shares"]})),
    )
    conn.commit()
    _release(conn)
    return removed


def sell_user_holding(user_id: int, ticker: str, shares: float, sell_price: float) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    ticker = ticker.upper()
    cur.execute(
        f"SELECT * FROM holdings WHERE user_id={PH} AND ticker={PH} LIMIT 1", (user_id, ticker)
    )
    row = _fetchone(cur)
    if not row:
        _release(conn)
        return None
    h = row
    if shares >= h["shares"]:
        cur.execute(f"DELETE FROM holdings WHERE id={PH}", (h["id"],))
        sold_shares = h["shares"]
    else:
        cur.execute(f"UPDATE holdings SET shares = shares - {PH} WHERE id={PH}", (shares, h["id"]))
        sold_shares = shares
    pnl = (sell_price - h["buy_price"]) * sold_shares
    invested = h["buy_price"] * sold_shares
    pnl_pct = (pnl / invested * 100) if invested else 0
    cur.execute(
        f"INSERT INTO closed_trades (user_id, ticker, shares, buy_price, sell_price, pnl, pnl_pct) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})",
        (user_id, ticker, sold_shares, h["buy_price"], sell_price, round(pnl, 2), round(pnl_pct, 2)),
    )
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'SELL', {PH}, {PH})",
        (user_id, ticker, json.dumps({"shares": sold_shares, "price": sell_price, "pnl": round(pnl, 2)})),
    )
    conn.commit()
    _release(conn)
    return {"action": "SELL", "ticker": ticker, "shares": sold_shares, "sell_price": sell_price, "pnl": round(pnl, 2)}


def sell_user_holding_by_lot(user_id: int, holding_id: int, shares: float, sell_price: float) -> dict | None:
    """Sell shares from a specific lot (holding_id)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM holdings WHERE id={PH} AND user_id={PH}", (holding_id, user_id)
    )
    row = _fetchone(cur)
    if not row:
        _release(conn)
        return None
    h = row
    sold_shares = min(shares, h["shares"])
    if shares >= h["shares"]:
        cur.execute(f"DELETE FROM holdings WHERE id={PH}", (h["id"],))
    else:
        cur.execute(f"UPDATE holdings SET shares = shares - {PH} WHERE id={PH}", (sold_shares, h["id"]))
    pnl = (sell_price - h["buy_price"]) * sold_shares
    invested = h["buy_price"] * sold_shares
    pnl_pct = (pnl / invested * 100) if invested else 0
    cur.execute(
        f"INSERT INTO closed_trades (user_id, ticker, shares, buy_price, sell_price, pnl, pnl_pct) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})",
        (user_id, h["ticker"], sold_shares, h["buy_price"], sell_price, round(pnl, 2), round(pnl_pct, 2)),
    )
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'SELL', {PH}, {PH})",
        (user_id, h["ticker"], json.dumps({"shares": sold_shares, "price": sell_price, "buy_price": h["buy_price"], "pnl": round(pnl, 2)})),
    )
    conn.commit()
    _release(conn)
    return {"action": "SELL", "ticker": h["ticker"], "shares": sold_shares, "sell_price": sell_price, "pnl": round(pnl, 2)}


# ── Options operations ──────────────────────────────────────────────────

def get_user_options(user_id: int) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM options WHERE user_id = {PH} ORDER BY id", (user_id,))
    rows = _fetchall(cur)
    _release(conn)
    return rows


def add_user_option(user_id: int, ticker: str, option_type: str, strike: float,
                    expiry: str, premium: float, contracts: int, position: str = "long") -> dict:
    conn = get_db()
    cur = conn.cursor()
    action = "BTO" if position == "long" else "STO"
    if USE_PG:
        cur.execute(
            f"INSERT INTO options (user_id, ticker, option_type, position, strike, expiry, premium, contracts) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}) RETURNING *",
            (user_id, ticker.upper(), option_type.lower(), position.lower(), strike, expiry, premium, contracts),
        )
        new_row = _fetchone(cur)
    else:
        cur.execute(
            f"INSERT INTO options (user_id, ticker, option_type, position, strike, expiry, premium, contracts) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})",
            (user_id, ticker.upper(), option_type.lower(), position.lower(), strike, expiry, premium, contracts),
        )
        cur.execute(f"SELECT * FROM options WHERE id = {PH}", (cur.lastrowid,))
        new_row = _fetchone(cur)
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, {PH}, {PH}, {PH})",
        (user_id, f"{action}_{option_type.upper()}", ticker.upper(),
         json.dumps({"strike": strike, "expiry": expiry, "premium": premium, "contracts": contracts})),
    )
    conn.commit()
    _release(conn)
    return new_row


def close_user_option(user_id: int, ticker: str, option_type: str, strike: float,
                      expiry: str, close_premium: float, contracts: int, position: str = "long") -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    ticker = ticker.upper()
    cur.execute(
        f"SELECT * FROM options WHERE user_id={PH} AND ticker={PH} AND option_type={PH} AND position={PH} AND strike={PH} AND expiry={PH}",
        (user_id, ticker, option_type.lower(), position.lower(), strike, expiry),
    )
    row = _fetchone(cur)
    if not row:
        _release(conn)
        return None
    opt = row
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
    cur.execute(
        f"INSERT INTO closed_options (user_id, ticker, option_type, position, strike, expiry, open_premium, close_premium, contracts, pnl, pnl_pct) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})",
        (user_id, ticker, option_type.lower(), position.lower(), strike, expiry, opt["premium"], close_premium, closed, round(pnl, 2), round(pnl_pct, 2)),
    )
    close_action = "STC" if position == "long" else "BTC"
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, {PH}, {PH}, {PH})",
        (user_id, f"{close_action}_{option_type.upper()}", ticker,
         json.dumps({"strike": strike, "expiry": expiry, "premium": close_premium, "contracts": closed, "pnl": round(pnl, 2)})),
    )
    conn.commit()
    _release(conn)
    return {"action": close_action, "ticker": ticker, "type": option_type, "strike": strike,
            "expiry": expiry, "close_premium": close_premium, "contracts": closed, "pnl": round(pnl, 2)}


def update_user_option(user_id: int, option_id: int, ticker: str, option_type: str,
                       strike: float, expiry: str, premium: float, contracts: int,
                       position: str = "long") -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE options SET ticker={PH}, option_type={PH}, position={PH}, strike={PH}, expiry={PH}, premium={PH}, contracts={PH} WHERE id={PH} AND user_id={PH}",
        (ticker.upper(), option_type.lower(), position.lower(), strike, expiry, premium, contracts, option_id, user_id),
    )
    if cur.rowcount == 0:
        _release(conn)
        return None
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'EDIT_OPTION', {PH}, {PH})",
        (user_id, ticker.upper(), json.dumps({"strike": strike, "expiry": expiry})),
    )
    conn.commit()
    cur.execute(f"SELECT * FROM options WHERE id = {PH}", (option_id,))
    result = _fetchone(cur)
    _release(conn)
    return result


def delete_user_option(user_id: int, option_id: int) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM options WHERE id={PH} AND user_id={PH}", (option_id, user_id))
    row = _fetchone(cur)
    if not row:
        _release(conn)
        return None
    removed = row
    cur.execute(f"DELETE FROM options WHERE id={PH} AND user_id={PH}", (option_id, user_id))
    cur.execute(
        f"INSERT INTO transactions (user_id, action, ticker, details) VALUES ({PH}, 'DELETE_OPTION', {PH}, {PH})",
        (user_id, removed["ticker"], json.dumps({"strike": removed["strike"]})),
    )
    conn.commit()
    _release(conn)
    return removed


def get_user_transactions(user_id: int) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM transactions WHERE user_id={PH} ORDER BY created_at DESC", (user_id,))
    rows = _fetchall(cur)
    _release(conn)
    return rows


# ── Watchlist operations ─────────────────────────────────────────────────

def get_user_watchlist(user_id: int) -> list[str]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT ticker FROM watchlist WHERE user_id={PH} ORDER BY added_at", (user_id,))
    rows = _fetchall(cur)
    _release(conn)
    return [r["ticker"] for r in rows]


def add_to_watchlist(user_id: int, ticker: str) -> bool:
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"INSERT INTO watchlist (user_id, ticker) VALUES ({PH}, {PH})", (user_id, ticker.upper()))
        conn.commit()
        _release(conn)
        return True
    except Exception:
        conn.rollback()
        _release(conn)
        return False


def remove_from_watchlist(user_id: int, ticker: str) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM watchlist WHERE user_id={PH} AND ticker={PH}", (user_id, ticker.upper()))
    conn.commit()
    removed = cur.rowcount > 0
    _release(conn)
    return removed


# ── Closed trades operations ─────────────────────────────────────────────

def get_closed_trades(user_id: int) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM closed_trades WHERE user_id={PH} ORDER BY closed_at DESC", (user_id,))
    rows = _fetchall(cur)
    _release(conn)
    return rows


def get_closed_options(user_id: int) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM closed_options WHERE user_id={PH} ORDER BY closed_at DESC", (user_id,))
    rows = _fetchall(cur)
    _release(conn)
    return rows


# ── Refresh token operations ─────────────────────────────────────────────

def store_refresh_token(user_id: int, token: str, expires_at: str) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO refresh_tokens (user_id, token, expires_at) VALUES ({PH}, {PH}, {PH})",
        (user_id, token, expires_at),
    )
    conn.commit()
    _release(conn)


def get_refresh_token(token: str) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM refresh_tokens WHERE token = {PH}", (token,))
    row = _fetchone(cur)
    _release(conn)
    return row


def delete_refresh_token(token: str) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM refresh_tokens WHERE token = {PH}", (token,))
    conn.commit()
    _release(conn)


def delete_user_refresh_tokens(user_id: int) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM refresh_tokens WHERE user_id = {PH}", (user_id,))
    conn.commit()
    _release(conn)


def cleanup_expired_refresh_tokens() -> None:
    conn = get_db()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(f"DELETE FROM refresh_tokens WHERE expires_at < {PH}", (now,))
    conn.commit()
    _release(conn)


# Initialize DB on import
init_db()
