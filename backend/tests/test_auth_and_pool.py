import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

_database_dir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("STOCKPILOT_DB_PATH", os.path.join(_database_dir.name, "test.db"))

import database


class ConnectionReleaseTests(unittest.TestCase):
    def test_helpers_release_connections_when_queries_fail(self):
        class FailingCursor:
            rowcount, lastrowid, description = 0, None, None

            def execute(self, *args):
                raise RuntimeError("database unavailable")

        class FailingConnection:
            def cursor(self):
                return FailingCursor()

            def commit(self):
                pass

            def rollback(self):
                pass

        calls = [
            lambda: database.get_user_by_username("x"),
            lambda: database.get_user_holdings(1),
            lambda: database.add_user_holding(1, "AAPL", 1, 1),
            lambda: database.update_user_holding(1, 1, "AAPL", 1, 1),
            lambda: database.delete_user_holding(1, 1),
            lambda: database.add_user_option(1, "AAPL", "put", 100, "2027-01-15", 1, 1, "short"),
            lambda: database.update_user_option(1, 1, "AAPL", "put", 100, "2027-01-15", 1, 1, "short"),
            lambda: database.delete_user_option(1, 1),
            lambda: database.get_closed_options(1),
            lambda: database.consume_refresh_token("x"),
            lambda: database.list_notifications(1),
            lambda: database.get_iv_history("AAPL", "2026-01-01"),
        ]
        released = []
        with patch.object(database, "get_db", side_effect=lambda: FailingConnection()), \
             patch.object(database, "_release", side_effect=released.append):
            for call in calls:
                with self.assertRaises(RuntimeError):
                    call()
            self.assertFalse(database.add_to_watchlist(1, "AAPL"))
        self.assertEqual(len(released), len(calls) + 1)


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        import main
        from fastapi.testclient import TestClient
        main.limiter.reset()
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def test_passwords_over_bcrypt_limit_are_rejected_without_server_error(self):
        username = uuid4().hex[:12]
        response = self.client.post("/api/auth/register", json={"username": username, "password": "p" * 73, "display_name": "x"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register", json={
            "username": username, "password": "é" * 36, "display_name": "x"}).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": username, "password": "é" * 37}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": username, "password": "é" * 36}).status_code, 200)

    def test_registration_requires_the_invite_code_when_configured(self):
        import main
        from unittest.mock import patch
        main.limiter.reset()
        body = {"username": uuid4().hex[:12], "password": "secret123", "display_name": "x"}
        with patch.dict("os.environ", {"REGISTRATION_CODE": "letmein"}):
            self.assertEqual(self.client.post("/api/auth/register", json=body).status_code, 403)
            self.assertEqual(self.client.post("/api/auth/register", json={**body, "invite_code": "wrong"}).status_code, 403)
            self.assertEqual(self.client.post("/api/auth/register", json={**body, "invite_code": " letmein "}).status_code, 200)
        main.limiter.reset()

    def test_refresh_token_is_single_use_under_concurrency(self):
        from fastapi.testclient import TestClient
        import main
        registered = self.client.post("/api/auth/register", json={
            "username": uuid4().hex[:12], "password": "secret123", "display_name": "x"}).json()
        barrier, results = threading.Barrier(2), []

        def refresh():
            client = TestClient(main.app, raise_server_exceptions=False)
            barrier.wait()
            results.append(client.post("/api/auth/refresh", json={"refresh_token": registered["refresh_token"]}))

        threads = [threading.Thread(target=refresh) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(response.status_code for response in results), [200, 401])
        rotated = next(response.json() for response in results if response.status_code == 200)
        self.assertEqual(self.client.post("/api/auth/refresh", json={"refresh_token": rotated["refresh_token"]}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
