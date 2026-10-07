"""Named watchlist lists: create, rename, reorder and delete lists, and set which lists each symbol belongs to."""

import database

MAIN = "Main"
MAX_LISTS = 50
MAX_LISTS_PER_SYMBOL = 10


class ListConflict(ValueError):
    pass


def clean_name(name) -> str:
    name = " ".join(str(name or "").split())
    if not name or len(name) > 40:
        raise ValueError("List names are 1-40 characters")
    if "/" in name or any(ord(ch) < 32 for ch in name):
        raise ValueError("List names cannot contain '/' or control characters")
    if name.lower() == "all":
        raise ValueError('"All" is reserved for the view of every symbol')
    return name


def _tx(user_id: int, work):
    conn = database.get_db()
    try:
        cur = conn.cursor()
        if database.USE_PG:
            cur.execute(f"SELECT id FROM users WHERE id={database.PH} FOR UPDATE", (user_id,))
        else:
            cur.execute("BEGIN IMMEDIATE")
        result = work(cur)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        database._release(conn)


def _ensure(cur, user_id: int) -> list[str]:
    """Make lists and memberships authoritative and return list names in display order.
    Symbols saved before multi-list support keep their single legacy list, and every name in use becomes a list."""
    PH = database.PH
    cur.execute(f"""INSERT INTO watchlist_lists (user_id, ticker, list_name)
        SELECT w.user_id, w.ticker, COALESCE(NULLIF(TRIM(w.list_name), ''), '{MAIN}') FROM watchlist w
        WHERE w.user_id={PH} AND NOT EXISTS (
            SELECT 1 FROM watchlist_lists m WHERE m.user_id = w.user_id AND m.ticker = w.ticker)
        ON CONFLICT DO NOTHING""", (user_id,))
    cur.execute(f"SELECT name, position FROM watchlist_groups WHERE user_id={PH} ORDER BY position, name", (user_id,))
    groups = database._fetchall(cur)
    canonical = {g["name"].lower(): g["name"] for g in groups}
    cur.execute(f"SELECT DISTINCT list_name FROM watchlist_lists WHERE user_id={PH}", (user_id,))
    used = sorted({r["list_name"] for r in database._fetchall(cur)}, key=lambda n: (n.lower() != MAIN.lower(), n.lower()))
    low = min((g["position"] for g in groups), default=0)
    high = max((g["position"] for g in groups), default=0)
    for name in [MAIN, *used]:
        if name.lower() in canonical:
            continue
        if name == MAIN:
            position = low - 1 if groups else 0
        else:
            high += 1
            position = high
        cur.execute(f"INSERT INTO watchlist_groups (user_id, name, position) VALUES ({PH}, {PH}, {PH}) ON CONFLICT DO NOTHING",
                    (user_id, name, position))
        canonical[name.lower()] = name
    for name in used:
        if canonical[name.lower()] != name:
            cur.execute(f"UPDATE watchlist_lists SET list_name={PH} WHERE user_id={PH} AND list_name={PH}",
                        (canonical[name.lower()], user_id, name))
    cur.execute(f"SELECT name FROM watchlist_groups WHERE user_id={PH} ORDER BY position, name", (user_id,))
    return [r["name"] for r in database._fetchall(cur)]


def _overview(cur, user_id: int) -> dict:
    PH = database.PH
    names = _ensure(cur, user_id)
    order = {name: i for i, name in enumerate(names)}
    cur.execute(f"SELECT ticker, note FROM watchlist WHERE user_id={PH} ORDER BY added_at, id", (user_id,))
    rows = database._fetchall(cur)
    cur.execute(f"SELECT ticker, list_name FROM watchlist_lists WHERE user_id={PH}", (user_id,))
    memberships: dict[str, list[str]] = {}
    for row in database._fetchall(cur):
        memberships.setdefault(row["ticker"], []).append(row["list_name"])
    items = []
    for row in rows:
        lists = sorted(memberships.get(row["ticker"], [MAIN]), key=lambda n: order.get(n, len(order)))
        items.append({"ticker": row["ticker"], "lists": lists, "list_name": lists[0], "note": row["note"] or ""})
    return {"lists": names, "items": items}


def overview(user_id: int) -> dict:
    return _tx(user_id, lambda cur: _overview(cur, user_id))


def _find(names: list[str], name: str) -> str | None:
    return next((n for n in names if n.lower() == name.lower()), None)


def create(user_id: int, name: str) -> dict:
    name = clean_name(name)

    def work(cur):
        names = _ensure(cur, user_id)
        if _find(names, name):
            raise ListConflict(f'A list named "{name}" already exists')
        if len(names) >= MAX_LISTS:
            raise ValueError(f"Up to {MAX_LISTS} lists are supported")
        cur.execute(f"SELECT COALESCE(MAX(position), 0) AS p FROM watchlist_groups WHERE user_id={database.PH}", (user_id,))
        position = database._fetchone(cur)["p"] + 1
        cur.execute(f"INSERT INTO watchlist_groups (user_id, name, position) VALUES ({database.PH}, {database.PH}, {database.PH})",
                    (user_id, name, position))
        return _overview(cur, user_id)
    return _tx(user_id, work)


def rename(user_id: int, old: str, new: str) -> dict:
    new = clean_name(new)
    PH = database.PH

    def work(cur):
        names = _ensure(cur, user_id)
        current = _find(names, old)
        if not current:
            raise LookupError("List not found")
        if current == MAIN:
            raise ValueError(f"{MAIN} is the default list and cannot be renamed")
        clash = _find(names, new)
        if clash and clash != current:
            raise ListConflict(f'A list named "{clash}" already exists')
        cur.execute(f"UPDATE watchlist_groups SET name={PH} WHERE user_id={PH} AND name={PH}", (new, user_id, current))
        cur.execute(f"UPDATE watchlist_lists SET list_name={PH} WHERE user_id={PH} AND list_name={PH}", (new, user_id, current))
        cur.execute(f"UPDATE watchlist SET list_name={PH} WHERE user_id={PH} AND list_name={PH}", (new, user_id, current))
        return _overview(cur, user_id)
    return _tx(user_id, work)


def delete(user_id: int, name: str) -> dict:
    """Remove a list. Symbols that were only in it move to Main; nothing leaves the watchlist."""
    PH = database.PH

    def work(cur):
        names = _ensure(cur, user_id)
        current = _find(names, name)
        if not current:
            raise LookupError("List not found")
        if current == MAIN:
            raise ValueError(f"{MAIN} is the default list and cannot be deleted")
        cur.execute(f"DELETE FROM watchlist_lists WHERE user_id={PH} AND list_name={PH}", (user_id, current))
        cur.execute(f"DELETE FROM watchlist_groups WHERE user_id={PH} AND name={PH}", (user_id, current))
        cur.execute(f"UPDATE watchlist SET list_name=NULL WHERE user_id={PH} AND list_name={PH}", (user_id, current))
        cur.execute(f"""INSERT INTO watchlist_lists (user_id, ticker, list_name)
            SELECT w.user_id, w.ticker, '{MAIN}' FROM watchlist w WHERE w.user_id={PH} AND NOT EXISTS (
                SELECT 1 FROM watchlist_lists m WHERE m.user_id = w.user_id AND m.ticker = w.ticker)
            ON CONFLICT DO NOTHING""", (user_id,))
        return _overview(cur, user_id)
    return _tx(user_id, work)


def reorder(user_id: int, order: list[str]) -> dict:
    def work(cur):
        names = _ensure(cur, user_id)
        resolved = [_find(names, n) for n in order]
        if None in resolved or len(set(resolved)) != len(names):
            raise ValueError("Send every list exactly once")
        for position, name in enumerate(resolved):
            cur.execute(f"UPDATE watchlist_groups SET position={database.PH} WHERE user_id={database.PH} AND name={database.PH}",
                        (position, user_id, name))
        return _overview(cur, user_id)
    return _tx(user_id, work)


def set_memberships(user_id: int, ticker: str, lists: list[str], note: str | None) -> dict | None:
    """Replace a symbol's lists (new names become lists) and its note. Returns None when the symbol isn't watched."""
    requested: dict[str, str] = {}
    for name in lists:
        name = clean_name(name)
        requested.setdefault(name.lower(), name)
    if not requested:
        requested = {MAIN.lower(): MAIN}
    if len(requested) > MAX_LISTS_PER_SYMBOL:
        raise ValueError(f"A symbol can be in up to {MAX_LISTS_PER_SYMBOL} lists")
    ticker = ticker.upper()
    PH = database.PH

    def work(cur):
        cur.execute(f"UPDATE watchlist SET note={PH} WHERE user_id={PH} AND ticker={PH}",
                    ((note or "").strip() or None, user_id, ticker))
        if cur.rowcount == 0:
            return None
        names = _ensure(cur, user_id)
        chosen = []
        for name in requested.values():
            existing = _find(names, name)
            if not existing:
                if len(names) >= MAX_LISTS:
                    raise ValueError(f"Up to {MAX_LISTS} lists are supported")
                cur.execute(f"SELECT COALESCE(MAX(position), 0) AS p FROM watchlist_groups WHERE user_id={PH}", (user_id,))
                cur.execute(f"INSERT INTO watchlist_groups (user_id, name, position) VALUES ({PH}, {PH}, {PH})",
                            (user_id, name, database._fetchone(cur)["p"] + 1))
                names.append(name)
                existing = name
            chosen.append(existing)
        cur.execute(f"DELETE FROM watchlist_lists WHERE user_id={PH} AND ticker={PH}", (user_id, ticker))
        for name in chosen:
            cur.execute(f"INSERT INTO watchlist_lists (user_id, ticker, list_name) VALUES ({PH}, {PH}, {PH})", (user_id, ticker, name))
        cur.execute(f"UPDATE watchlist SET list_name={PH} WHERE user_id={PH} AND ticker={PH}", (chosen[0], user_id, ticker))
        return _overview(cur, user_id)
    return _tx(user_id, work)
