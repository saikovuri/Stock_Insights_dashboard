import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

_database_dir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("STOCKPILOT_DB_PATH", os.path.join(_database_dir.name, "test.db"))

import database


def new_user():
    return database.create_user(uuid4().hex[:16], "test-only", "Feature tests")["id"]


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        import main
        from fastapi.testclient import TestClient
        cls.main = main
        cls.client = TestClient(main.app)

    def as_user(self, uid):
        return patch.dict(self.main.app.dependency_overrides, {self.main.get_current_user: lambda: {"user_id": uid}})

    def test_accounts_label_lots_filter_views_and_scope_sales_and_assignment(self):
        uid = new_user()
        database.add_user_holding(uid, "AAPL", 10, 100, "2026-01-02 00:00:00")
        database.add_user_holding(uid, "AAPL", 5, 120, "2026-01-03 00:00:00", account="IRA")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            database.sell_user_holding(uid, "AAPL", 6, 130, "IRA")
        database.sell_user_holding(uid, "AAPL", 5, 130, "IRA")
        self.assertEqual(sorted((h["account"], h["shares"]) for h in database.get_user_holdings(uid)), [(None, 10)])
        with self.as_user(uid), patch("yfinance.download", return_value=__import__("pandas").DataFrame()), \
             patch.object(self.main, "finnhub_enabled", return_value=False), \
             patch.object(self.main, "get_key_metrics", return_value={"price": 150, "sector": "Tech"}):
            ira = self.client.get("/api/portfolio/closed", params={"account": "IRA"}).json()
            self.assertEqual([t["pnl"] for t in ira["trades"]], [50])
            self.assertEqual(self.client.get("/api/portfolio/closed", params={"account": "Default"}).json()["trades"], [])
            summary = self.client.get("/api/portfolio/summary", params={"account": "Default"}).json()
            self.assertEqual([(h["account"], h["shares"]) for h in summary["holdings"]], [("Default", 10)])
            self.assertTrue(summary["as_of"])
        call = database.add_user_option(uid, "AAPL", "call", 160, "2026-01-16", 2, 1, "short", account="IRA")
        with self.assertRaisesRegex(ValueError, "option's account"):
            database.assign_user_option(uid, call["id"])
        put = database.add_user_option(uid, "MSFT", "put", 300, "2026-01-16", 3, 1, "short", account="IRA")
        database.assign_user_option(uid, put["id"])
        msft = next(h for h in database.get_user_holdings(uid) if h["ticker"] == "MSFT")
        self.assertEqual((msft["account"], msft["shares"]), ("IRA", 100))

    def test_cash_free_cash_and_flow_adjusted_nav_history(self):
        uid = new_user()
        database.add_user_option(uid, "AAPL", "put", 100, "2099-01-15", 2, 2, "short")
        with self.as_user(uid):
            self.assertEqual(self.client.put("/api/portfolio/cash", json={"cash": 50000}).status_code, 200)
            self.assertEqual(self.client.put("/api/portfolio/cash", json={"account": "IRA", "cash": 1000}).status_code, 200)
            self.assertEqual(self.client.put("/api/portfolio/cash", json={"account": "bad/name", "cash": 1}).status_code, 422)
            accounts = {a["name"]: a for a in self.client.get("/api/portfolio/accounts").json()["accounts"]}
        self.assertEqual((accounts["Default"]["put_collateral"], accounts["Default"]["free_cash"]), (20000, 30000))
        self.assertEqual(accounts["IRA"]["free_cash"], 1000)
        import accounting
        import accounts as accounts_module
        from datetime import datetime, timezone
        marks = iter([
            ({"holdings": [{"account": "Default", "current_value": 10000}]}, {"options": [{"account": "Default", "market_price": 1, "contracts": 2, "position": "short"}]}),
            ({"holdings": [{"account": "Default", "current_value": 20000}]}, {"options": [{"account": "Default", "market_price": 1, "contracts": 2, "position": "short"}]}),
            ({"holdings": [{"account": "Default", "current_value": None}]}, {"options": []}),
        ])
        accounting.record_entry(uid, {"kind": "deposit", "amount": "10000", "occurred_at": datetime(2026, 3, 2, tzinfo=timezone.utc),
                                      "idempotency_key": uuid4().hex})
        for day in ("2026-03-01", "2026-03-02", "2026-03-03"):
            stocks, options = next(marks)
            with patch.object(self.main, "portfolio_summary_endpoint", return_value=stocks), \
                 patch.object(self.main, "options_summary_endpoint", return_value=options):
                accounts_module.snapshot(uid, day)
        history = accounts_module.nav_history(uid)
        navs = [point["nav"] for point in history["series"]]
        self.assertEqual(navs[:2], [10000 + 50000 + 1000 - 200, 20000 + 50000 + 1000 - 200])
        self.assertIsNone(navs[2], "missing marks must not become a value")
        self.assertAlmostEqual(history["return_pct"], 0.0, places=2, msg="the deposit must not count as a return")
        self.assertTrue(history["flow_adjusted"])
        self.assertFalse(accounts_module.nav_history(uid, "IRA")["flow_adjusted"])

    def test_expire_worthless_and_close_link_cycles(self):
        uid = new_user()
        expired = database.add_user_option(uid, "AAPL", "put", 100, "2026-01-16", 1.5, 2, "short")
        live = database.add_user_option(uid, "AAPL", "put", 95, "2099-01-15", 1, 1, "short")
        cycle = f"AAPL wheel {uuid4().hex[:6]}"
        with self.as_user(uid), patch.object(self.main.options_analytics, "_live", side_effect=lambda expiry: expiry > "2027-01-01"):
            self.assertEqual(self.client.post(f"/api/portfolio/options/{live['id']}/expire").status_code, 400)
            response = self.client.post(f"/api/portfolio/options/{expired['id']}/expire", json={"cycle": cycle})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual((response.json()["pnl"], response.json()["cycle"]), (300, cycle))
            closed = self.client.post("/api/portfolio/options/close", json={
                "ticker": "AAPL", "option_type": "put", "strike": 95, "expiry": "2099-01-15", "premium": 0.4,
                "contracts": 1, "position": "short", "option_id": live["id"], "cycle": cycle})
            self.assertEqual(closed.status_code, 200, closed.text)
        record = next(r for r in database.get_closed_options(uid) if r["strike"] == 100)
        self.assertTrue(str(record["closed_at"]).startswith("2026-01-16"))
        import accounting
        linked = next(c for c in accounting.report(uid)["cycles"] if c["name"] == cycle)
        self.assertEqual(round(linked["realized_pnl"], 2), 360)

    def test_broker_option_symbols_positions_and_history_import(self):
        import portfolio_insights as insights
        parse = insights.parse_option_symbol
        expected = {"ticker": "AAPL", "expiry": "2030-01-17", "option_type": "call", "strike": 150.0}
        for text in ("AAPL  300117C00150000", "-AAPL300117C150", "AAPL 01/17/2030 150.00 C", "AAPL Jan 17 '30 $150 Call"):
            self.assertEqual(parse(text), expected, text)
        self.assertIsNone(parse("AAPL"))
        positions = insights.parse_broker_csv("Symbol,Quantity,Cost Basis Total\nAAPL,10,1500\n"
                                              "AAPL 01/17/2030 150.00 P,-2,-500\nAAPL 01/17/2020 150.00 P,-2,-500\n")
        self.assertEqual([r["kind"] for r in positions["rows"]], ["stock", "option"])
        self.assertEqual((positions["rows"][1]["position"], positions["rows"][1]["premium"]), ("short", 2.5))
        self.assertIn("expired", positions["skipped"][0]["reason"])
        uid = new_user()
        insights.import_rows(uid, positions["rows"], "Roth")
        self.assertEqual({o["account"] for o in database.get_user_options(uid)}, {"Roth"})
        history_csv = ("Symbol,Description,Quantity,Date Acquired,Date Sold,Proceeds,Cost Basis\n"
                       "MSFT,Microsoft,10,01/02/2025,03/03/2025,4200,4000\n"
                       ",MSFT 03/21/2025 380.00 P,-1,02/03/2025,03/03/2025,250,40\n"
                       "XYZ123,Bad,1,01/02/2025,03/03/2025,1,1\n")
        history = insights.parse_history_csv(history_csv)
        self.assertEqual([r["kind"] for r in history["rows"]], ["stock", "option"])
        option = history["rows"][1]
        self.assertEqual((option["position"], option["open_premium"], option["close_premium"]), ("short", 2.5, 0.4))
        first = insights.import_history(uid, history["rows"], "Roth")
        again = insights.import_history(uid, history["rows"], "Roth")
        self.assertEqual((first["imported"], again["imported"], again["duplicates"]), (2, 0, 2))
        self.assertEqual(next(r for r in database.get_closed_options(uid) if r["ticker"] == "MSFT")["pnl"], 210)
        self.assertEqual(next(t for t in database.get_closed_trades(uid) if t["ticker"] == "MSFT")["pnl"], 200)

    def test_split_detection_and_application_is_atomic_and_once(self):
        import corporate_actions
        uid = new_user()
        database.add_user_holding(uid, "NVDA", 10, 1000, "2024-01-02 00:00:00")
        database.add_user_holding(uid, "NVDA", 5, 120, "2024-07-01 00:00:00")
        database._run(f"UPDATE holdings SET date_added={database.PH} WHERE user_id={database.PH} AND shares=5",
                      ("2024-07-01 00:00:00", uid))
        option = database.add_user_option(uid, "NVDA", "call", 1100, "2024-09-20", 20, 1, "short")
        database._run(f"UPDATE options SET date_added={database.PH} WHERE id={database.PH}", ("2024-02-01 00:00:00", option["id"]))
        with patch.object(corporate_actions, "_splits", return_value=[("2024-06-10", 10.0)]):
            pending = corporate_actions.pending_splits(uid)
            self.assertEqual([(p["label"], p["lots"], p["options"], p["options_adjustable"]) for p in pending], [("10-for-1", 1, 1, True)])
            with self.as_user(uid):
                applied = self.client.post("/api/portfolio/corporate-actions/apply", json={"ticker": "NVDA", "split_date": "2024-06-10"})
                self.assertEqual(applied.status_code, 200, applied.text)
                self.assertEqual(self.client.post("/api/portfolio/corporate-actions/apply",
                                                  json={"ticker": "NVDA", "split_date": "2024-06-10"}).status_code, 404)
            self.assertEqual(corporate_actions.pending_splits(uid), [])
        lots = sorted((h["shares"], h["buy_price"]) for h in database.get_user_holdings(uid))
        self.assertEqual(lots, [(5, 120), (100, 100)])
        adjusted = database.get_user_options(uid)[0]
        self.assertEqual((adjusted["contracts"], adjusted["strike"], adjusted["premium"]), (10, 110, 2))
        with patch.object(corporate_actions, "_splits", return_value=[("2024-08-01", 1.5)]):
            database._run(f"UPDATE options SET expiry='2024-12-20' WHERE id={database.PH}", (option["id"],))
            self.assertFalse(corporate_actions.pending_splits(uid)[0]["options_adjustable"])
        import account_transfer
        destination = new_user()
        account_transfer.import_account(destination, account_transfer.export_account(uid))
        with patch.object(corporate_actions, "_splits", return_value=[("2024-06-10", 10.0)]):
            self.assertEqual(corporate_actions.pending_splits(destination), [], "transferred lots must not be split twice")
        self.assertEqual(sorted(h["shares"] for h in database.get_user_holdings(destination)), [5, 100])

    def test_watchlist_groups_notes_earnings_search_and_route_conflicts(self):
        uid = new_user()
        database.add_to_watchlist(uid, "AAPL")
        with self.as_user(uid):
            self.assertEqual(self.client.put("/api/watchlist/AAPL", json={"list_name": "Core", "note": "Buy < 180"}).status_code, 200)
            self.assertEqual(self.client.put("/api/watchlist/MSFT", json={"list_name": "Core"}).status_code, 404)
            items = self.client.get("/api/watchlist").json()
            self.assertEqual(items["items"], [{"ticker": "AAPL", "list_name": "Core", "note": "Buy < 180"}])
            self.assertEqual(items["tickers"], ["AAPL"])
            with patch.object(self.main.options_analytics, "earnings_info",
                              return_value={"next": "2026-10-30", "next_timing": "after close", "next_confirmed": True}):
                self.assertEqual(self.client.get("/api/watchlist/earnings").json()["items"][0]["next"], "2026-10-30")
            self.assertEqual(self.client.put("/api/portfolio/income-goal", json={"goal": 500}).status_code, 200)
        import market
        directory = {"AAPL": {"name": "Apple Inc.", "market_cap": 3e12}, "APP": {"name": "AppLovin", "market_cap": 1e11},
                     "MSFT": {"name": "Microsoft", "market_cap": 3e12}}

        class FakeSearch:
            def __init__(self, *args, **kwargs):
                self.quotes = [{"symbol": "APPN", "shortname": "Appian", "quoteType": "EQUITY", "exchDisp": "NASDAQ"},
                               {"symbol": "APPLE-OPT", "quoteType": "OPTION"}]
        with patch("intraday._directory", return_value=directory), patch.object(market.yf, "Search", FakeSearch), \
             patch.object(market, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()):
            results = self.client.get("/api/search", params={"q": "app"}).json()["results"]
            self.assertEqual([r["symbol"] for r in results], ["APP", "AAPL", "APPN"])
            self.assertEqual(self.client.get("/api/search", params={"q": "microsoft"}).json()["results"][0]["symbol"], "MSFT")


if __name__ == "__main__":
    unittest.main()
