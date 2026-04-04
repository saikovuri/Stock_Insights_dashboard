import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "stockinsights.db")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()


# ── User operations ──────────────────────────────────────────────────────

def create_user(username: str, password_hash: str, display_name: str) -> dict | None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
            (username, password_hash, display_name),
        )
        conn.commit()
        user = conn.execute("SELECT id, username, display_name FROM users WHERE username = ?", (username,)).fetchone()
        return dict(user)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Holdings operations ──────────────────────────────────────────────────

def get_user_holdings(user_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM holdings WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_user_holding(user_id: int, ticker: str, shares: float, buy_price: float) -> dict:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO holdings (user_id, ticker, shares, buy_price) VALUES (?, ?, ?, ?)",
        (user_id, ticker.upper(), shares, buy_price),
    )
    conn.execute(
        "INSERT INTO transactions (user_id, action, ticker, details) VALUES (?, 'BUY', ?, ?)",
        (user_id, ticker.upper(), json.dumps({"shares": shares, "price": buy_price})),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM holdings WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def update_user_holding(user_id: int, holding_id: int, ticker: str, shares: float, buy_price: float) -> dict | None:
    conn = get_db()
    cur = conn.execute(
        "UPDATE holdings SET ticker=?, shares=?, buy_price=? WHERE id=? AND user_id=?",
        (ticker.upper(), shares, buy_price, holding_id, user_id),
    )
    if cur.rowcount == 0:
        conn.close()
        return None
    conn.execute(
        "INSERT INTO transactions (user_id, action, ticker, details) VALUES (?, 'EDIT', ?, ?)",
        (user_id, ticker.upper(), json.dumps({"shares": shares, "price": buy_price})),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,)).fetchone()
    conn.close()
    return dict(row)


def delete_user_holding(user_id: int, holding_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM holdings WHERE id=? AND user_id=?", (holding_id, user_id)).fetchone()
    if not row:
        conn.close()
        return None
    removed = dict(row)
    conn.execute("DELETE FROM holdings WHERE id=? AND user_id=?", (holding_id, user_id))
    conn.execute(
        "INSERT INTO transactions (user_id, action, ticker, details) VALUES (?, 'DELETE', ?, ?)",
        (user_id, removed["ticker"], json.dumps({"shares": removed["shares"]})),
    )
    conn.commit()
    conn.close()
    return removed


def sell_user_holding(user_id: int, ticker: str, shares: float, sell_price: float) -> dict | None:
    conn = get_db()
    ticker = ticker.upper()
    row = conn.execute(
        "SELECT * FROM holdings WHERE user_id=? AND ticker=? LIMIT 1", (user_id, ticker)
    ).fetchone()
    if not row:
        conn.close()
        return None
    h = dict(row)
    if shares >= h["shares"]:
        conn.execute("DELETE FROM holdings WHERE id=?", (h["id"],))
        sold_shares = h["shares"]
    else:
        conn.execute("UPDATE holdings SET shares = shares - ? WHERE id=?", (shares, h["id"]))
        sold_shares = shares
    conn.execute(
        "INSERT INTO transactions (user_id, action, ticker, details) VALUES (?, 'SELL', ?, ?)",
        (user_id, ticker, json.dumps({"shares": sold_shares, "price": sell_price})),
    )
    conn.commit()
    conn.close()
    return {"action": "SELL", "ticker": ticker, "shares": sold_shares, "sell_price": sell_price}


# ── Options operations ──────────────────────────────────────────────────

def get_user_options(user_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM options WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_user_option(user_id: int, ticker: str, option_type: str, strike: float,
                    expiry: str, premium: float, contracts: int, position: str = "long") -> dict:
    conn = get_db()
    action = "BTO" if position == "long" else "STO"
    cur = conn.execute(
        "INSERT INTO options (user_id, ticker, option_type, position, strike, expiry, premium, contracts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, ticker.upper(), option_type.lower(), position.lower(), strike, expiry, premium, contracts),
    )
    conn.execute(
        "INSERT INTO transactions (user_id, action, ticker, details) VALUES (?, ?, ?, ?)",
        (user_id, f"{action}_{option_type.upper()}", ticker.upper(),
         json.dumps({"strike": strike, "expiry": expiry, "premium": premium, "contracts": contracts})),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM options WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def close_user_option(user_id: int, ticker: str, option_type: str, strike: float,
                      expiry: str, close_premium: float, contracts: int, position: str = "long") -> dict | None:
    conn = get_db()
    ticker = ticker.upper()
    row = conn.execute(
        "SELECT * FROM options WHERE user_id=? AND ticker=? AND option_type=? AND position=? AND strike=? AND expiry=?",
        (user_id, ticker, option_type.lower(), position.lower(), strike, expiry),
    ).fetchone()
    if not row:
        conn.close()
        return None
    opt = dict(row)
    if contracts >= opt["contracts"]:
        conn.execute("DELETE FROM options WHERE id=?", (opt["id"],))
        closed = opt["contracts"]
    else:
        conn.execute("UPDATE options SET contracts = contracts - ? WHERE id=?", (contracts, opt["id"]))
        closed = contracts
    close_action = "STC" if position == "long" else "BTC"
    conn.execute(
        "INSERT INTO transactions (user_id, action, ticker, details) VALUES (?, ?, ?, ?)",
        (user_id, f"{close_action}_{option_type.upper()}", ticker,
         json.dumps({"strike": strike, "expiry": expiry, "premium": close_premium, "contracts": closed})),
    )
    conn.commit()
    conn.close()
    return {"action": close_action, "ticker": ticker, "type": option_type, "strike": strike,
            "expiry": expiry, "close_premium": close_premium, "contracts": closed}


def update_user_option(user_id: int, option_id: int, ticker: str, option_type: str,
                       strike: float, expiry: str, premium: float, contracts: int,
                       position: str = "long") -> dict | None:
    conn = get_db()
    cur = conn.execute(
        "UPDATE options SET ticker=?, option_type=?, position=?, strike=?, expiry=?, premium=?, contracts=? WHERE id=? AND user_id=?",
        (ticker.upper(), option_type.lower(), position.lower(), strike, expiry, premium, contracts, option_id, user_id),
    )
    if cur.rowcount == 0:
        conn.close()
        return None
    conn.execute(
        "INSERT INTO transactions (user_id, action, ticker, details) VALUES (?, 'EDIT_OPTION', ?, ?)",
        (user_id, ticker.upper(), json.dumps({"strike": strike, "expiry": expiry})),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM options WHERE id = ?", (option_id,)).fetchone()
    conn.close()
    return dict(row)


def delete_user_option(user_id: int, option_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM options WHERE id=? AND user_id=?", (option_id, user_id)).fetchone()
    if not row:
        conn.close()
        return None
    removed = dict(row)
    conn.execute("DELETE FROM options WHERE id=? AND user_id=?", (option_id, user_id))
    conn.execute(
        "INSERT INTO transactions (user_id, action, ticker, details) VALUES (?, 'DELETE_OPTION', ?, ?)",
        (user_id, removed["ticker"], json.dumps({"strike": removed["strike"]})),
    )
    conn.commit()
    conn.close()
    return removed


def get_user_transactions(user_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Watchlist operations ─────────────────────────────────────────────────

def get_user_watchlist(user_id: int) -> list[str]:
    conn = get_db()
    rows = conn.execute("SELECT ticker FROM watchlist WHERE user_id=? ORDER BY added_at", (user_id,)).fetchall()
    conn.close()
    return [r["ticker"] for r in rows]


def add_to_watchlist(user_id: int, ticker: str) -> bool:
    conn = get_db()
    try:
        conn.execute("INSERT INTO watchlist (user_id, ticker) VALUES (?, ?)", (user_id, ticker.upper()))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def remove_from_watchlist(user_id: int, ticker: str) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM watchlist WHERE user_id=? AND ticker=?", (user_id, ticker.upper()))
    conn.commit()
    removed = cur.rowcount > 0
    conn.close()
    return removed


# Initialize DB on import
init_db()
