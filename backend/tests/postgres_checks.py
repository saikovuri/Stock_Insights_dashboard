import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.parse import urlparse
from uuid import uuid4


def main():
    url = os.environ.get("DATABASE_URL", "")
    if os.environ.get("STOCKPILOT_DISPOSABLE_DB") != "1" or not urlparse(url).path.endswith("_test"):
        raise RuntimeError("Refusing writes: use an explicitly disposable database whose name ends in _test")
    import database
    import accounting
    import psycopg2
    if not database.USE_PG:
        raise RuntimeError("PostgreSQL is required")
    database.init_db()
    database.init_db()
    user = database.create_user(uuid4().hex, "test-only", "Postgres checks")["id"]
    other = database.create_user(uuid4().hex, "test-only", "Other tenant")["id"]
    database.add_user_holding(user, "AAPL", 10, 100)
    barrier = Barrier(2)

    def sell():
        barrier.wait()
        try:
            return database.sell_user_holding(user, "AAPL", 8, 110)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        sales = list(executor.map(lambda _: sell(), range(2)))
    assert sum(result is not None for result in sales) == 1
    assert database.get_user_holdings(user)[0]["shares"] == 2
    assert database.get_user_holdings(other) == []
    selected = database.add_user_option(user, "MSFT", "put", 100, "2027-01-15", 2, 1, "short")
    barrier = Barrier(2)

    def assign():
        barrier.wait()
        try:
            return database.assign_user_option(user, selected["id"])
        except LookupError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        assignments = list(executor.map(lambda _: assign(), range(2)))
    assert sum(result is not None for result in assignments) == 1
    assert sum(row["shares"] for row in database.get_user_holdings(user) if row["ticker"] == "MSFT") == 100
    assert accounting.list_events(other) == []
    historical = dict(ticker="WDC", option_type="put", position="short", strike="65", expiry="2025-09-19",
                      contracts=1, open_premium="1.20", close_premium="0.35", opened_at="2025-09-01",
                      closed_at="2025-09-10", fees="1.30", notes="Historical test", idempotency_key=uuid4().hex)
    barrier = Barrier(2)

    def import_history():
        barrier.wait()
        return database.record_closed_option(user, historical)

    with ThreadPoolExecutor(max_workers=2) as executor:
        imported = list(executor.map(lambda _: import_history(), range(2)))
    assert imported[0]["id"] == imported[1]["id"]
    recorded = [row for row in database.get_closed_options(user) if row["ticker"] == "WDC"]
    assert len(recorded) == 1 and recorded[0]["net_pnl"] == 83.7
    assert database.get_closed_options(other) == []
    correction = historical | {"close_premium": "0.25", "fees": "2.50", "idempotency_key": uuid4().hex}
    for _ in range(2):
        updated = database.record_closed_option(user, correction, trade_id=recorded[0]["id"])
        assert updated["id"] == recorded[0]["id"]
    corrected = next(row for row in database.get_closed_options(user) if row["id"] == updated["id"])
    assert corrected["is_manual"] and corrected["net_pnl"] == 92.5
    review = dict(kind="review", event_id=corrected["ledger_event_id"], exit_reason="profit_target", target_capture_pct="50",
                  occurred_at="2025-09-10T00:00:00Z", idempotency_key=uuid4().hex)
    reviewed = accounting.record_entry(user, review)
    assert accounting.record_entry(user, review) == reviewed
    assert next(row for row in database.get_closed_options(user) if row["id"] == updated["id"])["review"]["target_capture_pct"] == 50
    accounting.record_entry(user, dict(kind="link", event_id=corrected["ledger_event_id"], cycle="PG wheel fixture", quantity=1,
                                      occurred_at="2025-09-10T00:00:00Z", idempotency_key=uuid4().hex))
    cycle = next(cycle for cycle in accounting.report(user)["cycles"] if cycle["name"] == "PG wheel fixture")
    assert cycle["put_pnl"] == 95 and cycle["fees"] == 2.5 and cycle["realized_pnl"] == 92.5
    import account_transfer
    destination = database.create_user(uuid4().hex, "test-only", "Transfer destination")["id"]
    package = account_transfer.export_account(user)
    assert account_transfer.preview_import(destination, package)["counts"]["closed_options"] == 2
    barrier = Barrier(2)

    def transfer():
        barrier.wait()
        return account_transfer.import_account(destination, package)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: transfer(), range(2)))
    assert sum(not result["already_imported"] for result in results) == 1
    transferred = next(row for row in database.get_closed_options(destination) if row["ticker"] == "WDC")
    assert transferred["net_pnl"] == 92.5 and transferred["is_manual"]
    assert transferred["review"]["target_capture_pct"] == 50
    assert accounting.report(destination)["cycles"][0]["realized_pnl"] == 92.5
    assert not database.delete_closed_option(other, updated["id"])
    assert database.delete_closed_option(user, updated["id"])
    assert accounting.report(user)["fees"] == 0
    conn = database.get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT relrowsecurity FROM pg_class WHERE oid='public.idea_log'::regclass")
        assert cursor.fetchone()[0], "Startup left idea_log exposed without RLS"
        for statement in ("UPDATE accounting_events SET operation='changed'", "DELETE FROM accounting_events", "TRUNCATE accounting_events"):
            try:
                cursor.execute(statement)
            except psycopg2.Error:
                conn.rollback()
            else:
                conn.rollback()
                raise AssertionError("Audit mutation unexpectedly succeeded")
        for role in ("anon", "authenticated", "service_role"):
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
            if not cursor.fetchone():
                cursor.execute(f"CREATE ROLE {role} NOLOGIN")
        cursor.execute("CREATE TABLE IF NOT EXISTS unrelated_policy_fixture(id INTEGER)")
        cursor.execute("ALTER TABLE unrelated_policy_fixture ENABLE ROW LEVEL SECURITY")
        cursor.execute("CREATE POLICY unrelated_fixture_policy ON unrelated_policy_fixture FOR SELECT USING (true)")
        conn.commit()
        script = (Path(__file__).resolve().parents[2] / "deploy" / "supabase_rls.sql").read_text(encoding="utf-8")
        cursor.execute(script)
        conn.commit()
        cursor.execute(script)
        conn.commit()
        cursor.execute("SELECT 1 FROM pg_policies WHERE tablename='unrelated_policy_fixture' AND policyname='unrelated_fixture_policy'")
        assert cursor.fetchone(), "RLS migration removed an unrelated policy"
        conn.rollback()
        for role in ("anon", "authenticated"):
            for table in ("holdings", "closed_trades", "accounting_events", "universe_snapshots", "idea_log"):
                cursor.execute(f"SET LOCAL ROLE {role}")
                try:
                    cursor.execute(f"SELECT * FROM {table}")
                    assert cursor.fetchall() == [], "Public role read private rows"
                except psycopg2.errors.InsufficientPrivilege:
                    pass
                finally:
                    conn.rollback()
        cursor.execute("SELECT relrowsecurity FROM pg_class WHERE relname='accounting_events'")
        assert cursor.fetchone()[0]
    finally:
        conn.rollback()
        database._release(conn)
    print("PostgreSQL migrations, concurrent sales/assignment, tenant isolation, immutable audit, and public-role RLS checks passed")


if __name__ == "__main__":
    main()