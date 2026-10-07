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
        self.assertAlmostEqual(accounts_module.nav_history(uid, "Default")["return_pct"], 0.0, places=2,
                               msg="unassigned ledger flows count toward Default")
        self.assertTrue(accounts_module.nav_history(uid, "IRA")["flow_adjusted"])
        self.assertEqual(accounts_module._external_flows(uid, "IRA"), {})
        from decimal import Decimal
        withdrawal = {"kind": "withdrawal", "amount": "500", "account": "IRA", "idempotency_key": uuid4().hex,
                      "occurred_at": datetime(2026, 3, 2, tzinfo=timezone.utc)}
        first = accounting.record_entry(uid, withdrawal)
        self.assertEqual(accounting.record_entry(uid, withdrawal), first, "retries stay idempotent")
        self.assertEqual(accounts_module._external_flows(uid, "IRA"), {"2026-03-02": Decimal("-500")})
        self.assertEqual(accounts_module._external_flows(uid, "Default"), {"2026-03-02": Decimal("10000")})
        self.assertEqual(accounts_module._external_flows(uid), {"2026-03-02": Decimal("9500")})
        with self.assertRaisesRegex(ValueError, "Only deposits and withdrawals"):
            accounting.record_entry(uid, {"kind": "fee", "amount": "1", "account": "IRA", "idempotency_key": uuid4().hex,
                                          "occurred_at": datetime(2026, 3, 2, tzinfo=timezone.utc)})

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
        database.add_to_watchlist(uid, "NVDA", "Semis")
        with self.as_user(uid):
            self.assertEqual(self.client.put("/api/watchlist/AAPL", json={"lists": ["Core", " Income ", "core"], "note": "Buy < 180"}).status_code, 200)
            self.assertEqual(self.client.put("/api/watchlist/MSFT", json={"lists": ["Core"]}).status_code, 404)
            self.assertEqual(self.client.put("/api/watchlist/AAPL", json={"lists": []}).status_code, 422)
            self.assertEqual(self.client.put("/api/watchlist/AAPL", json={"lists": ["x" * 41]}).status_code, 400)
            items = self.client.get("/api/watchlist").json()
            self.assertEqual(items["lists"], ["Main", "Semis", "Core", "Income"])
            self.assertEqual(items["items"], [
                {"ticker": "AAPL", "lists": ["Core", "Income"], "list_name": "Core", "note": "Buy < 180"},
                {"ticker": "NVDA", "lists": ["Semis"], "list_name": "Semis", "note": ""}])
            self.assertEqual(items["tickers"], ["AAPL", "NVDA"])
            self.assertEqual(self.client.delete("/api/watchlist/AAPL").status_code, 200)
            self.assertEqual(database._run(f"SELECT COUNT(*) AS n FROM watchlist_lists WHERE user_id={database.PH} AND ticker='AAPL'",
                                           (uid,), "one")["n"], 0)
            database.add_to_watchlist(uid, "AAPL")
            self.assertEqual(self.client.get("/api/watchlist").json()["items"][1]["lists"], ["Main"], "removed memberships must not resurface")
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

    def test_named_watchlist_lists_create_rename_reorder_delete(self):
        uid = new_user()
        database.add_to_watchlist(uid, "NVDA", "Semis")
        database.add_to_watchlist(uid, "AAPL")
        with self.as_user(uid):
            post = lambda name: self.client.post("/api/watchlist/lists", json={"name": name})
            created = post("  Earnings   plays ")
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(created.json()["lists"], ["Main", "Semis", "Earnings plays"], "empty lists exist")
            self.assertEqual(post("earnings PLAYS").status_code, 409)
            self.assertEqual(post("All").status_code, 400)
            self.assertEqual(post("a/b").status_code, 400)
            rename = lambda old, new: self.client.put(f"/api/watchlist/lists/{old}", json={"name": new})
            self.assertEqual(rename("Earnings plays", "Earnings").json()["lists"], ["Main", "Semis", "Earnings"])
            self.assertEqual(rename("Main", "Core").status_code, 400)
            self.assertEqual(rename("Nope", "Other").status_code, 404)
            self.assertEqual(rename("Semis", "earnings").status_code, 409)
            self.assertEqual(rename("semis", "Chips").json()["items"][0]["lists"], ["Chips"], "memberships follow a rename")
            self.client.put("/api/watchlist/NVDA", json={"lists": ["Chips", "Earnings"]})
            order = self.client.post("/api/watchlist/lists/order", json={"names": ["Earnings", "main", "Chips"]})
            self.assertEqual(order.json()["lists"], ["Earnings", "Main", "Chips"])
            self.assertEqual(order.json()["items"][0]["lists"], ["Earnings", "Chips"], "symbol lists follow list order")
            self.assertEqual(self.client.post("/api/watchlist/lists/order", json={"names": ["Main"]}).status_code, 400)
            self.assertEqual(self.client.delete("/api/watchlist/lists/Main").status_code, 400)
            gone = self.client.delete("/api/watchlist/lists/Chips").json()
            self.assertEqual((gone["lists"], gone["items"][0]["lists"]), (["Earnings", "Main"], ["Earnings"]))
            self.client.put("/api/watchlist/AAPL", json={"lists": ["Solo"]})
            solo = self.client.delete("/api/watchlist/lists/Solo").json()
            self.assertEqual(solo["items"][1]["lists"], ["Main"], "symbols only in a deleted list move to Main")
            self.assertEqual(self.client.post("/api/watchlist", json={"ticker": "AMD", "list_name": "All"}).status_code, 400)
            database.add_to_watchlist(uid, "AMD", "earnings")
            self.assertEqual(self.client.get("/api/watchlist").json()["items"][2]["lists"], ["Earnings"], "case variants join the existing list")
        import account_transfer
        destination = new_user()
        database.add_to_watchlist(destination, "NVDA", "Mine")
        account_transfer.import_account(destination, account_transfer.export_account(uid))
        import watchlists
        copied = watchlists.overview(destination)
        self.assertEqual(copied["lists"], ["Main", "Mine", "Earnings"])
        self.assertEqual({i["ticker"]: i["lists"] for i in copied["items"]},
                         {"NVDA": ["Mine"], "AAPL": ["Main"], "AMD": ["Earnings"]})

    def test_spinoff_moves_basis_and_keeps_lot_date_and_account(self):
        uid = new_user()
        old = database.add_user_holding(uid, "GE", 10, 100, "2023-01-05 00:00:00", account="IRA")
        database.add_user_holding(uid, "GE", 4, 150, "2024-05-01 00:00:00")
        with self.as_user(uid):
            body = {"ticker": "GE", "new_ticker": "GEV", "action_date": "2024-04-02", "ratio": 0.25, "basis_pct": 20}
            self.assertEqual(self.client.post("/api/portfolio/corporate-actions/spinoff", json={**body, "new_ticker": "GE"}).status_code, 422)
            self.assertEqual(self.client.post("/api/portfolio/corporate-actions/spinoff", json={**body, "action_date": "2999-01-01"}).status_code, 422)
            response = self.client.post("/api/portfolio/corporate-actions/spinoff", json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual((response.json()["lots"], response.json()["basis_moved"]), (1, 200))
            self.assertEqual(self.client.post("/api/portfolio/corporate-actions/spinoff", json=body).status_code, 409)
            self.assertEqual(self.client.post("/api/portfolio/corporate-actions/spinoff",
                                              json={**body, "ticker": "MSFT", "new_ticker": "XYZ"}).status_code, 404)
        lots = {(h["ticker"], h["account"]): h for h in database.get_user_holdings(uid)}
        self.assertEqual(lots[("GE", "IRA")]["buy_price"], 80, "parent keeps 80% of its basis")
        child = lots[("GEV", "IRA")]
        self.assertEqual((child["shares"], child["buy_price"]), (2.5, 80))
        self.assertEqual(str(child["date_added"])[:10], str(old["date_added"])[:10], "holding period carries over")
        self.assertEqual(lots[("GE", None)]["buy_price"], 150, "lots bought after the ex-date are untouched")
        total = sum(h["shares"] * h["buy_price"] for h in database.get_user_holdings(uid))
        self.assertAlmostEqual(total, 10 * 100 + 4 * 150, places=6, msg="total basis is conserved")

    def test_merger_cash_stock_and_mixed_deals(self):
        uid = new_user()
        database.add_user_holding(uid, "CASHCO", 10, 40, "2023-01-05 00:00:00")
        database.add_user_holding(uid, "STOCKCO", 10, 60, "2023-01-05 00:00:00", account="IRA")
        database.add_user_holding(uid, "MIXCO", 10, 30, "2023-01-05 00:00:00")
        database.add_user_option(uid, "STOCKCO", "call", 70, "2099-01-15", 1, 1, "short", account="IRA")
        with self.as_user(uid):
            post = lambda body: self.client.post("/api/portfolio/corporate-actions/merger", json=body)
            self.assertEqual(post({"ticker": "CASHCO", "action_date": "2025-06-02"}).status_code, 422)
            self.assertEqual(post({"ticker": "CASHCO", "action_date": "2025-06-02", "ratio": 1}).status_code, 422)
            cash = post({"ticker": "CASHCO", "action_date": "2025-06-02", "cash_per_share": 55})
            self.assertEqual((cash.status_code, cash.json()["realized_pnl"]), (200, 150), cash.text)
            stock = post({"ticker": "STOCKCO", "action_date": "2025-06-02", "new_ticker": "BIGCO", "ratio": 0.5})
            self.assertEqual((stock.status_code, stock.json()["options_unadjusted"]), (200, 1), stock.text)
            mixed = post({"ticker": "MIXCO", "action_date": "2025-06-02", "new_ticker": "BIGCO", "ratio": 2, "cash_per_share": 35})
            self.assertEqual((mixed.status_code, mixed.json()["lots_cash_above_basis"]), (200, 1), mixed.text)
            self.assertEqual(post({"ticker": "MIXCO", "action_date": "2025-06-02", "cash_per_share": 1}).status_code, 409)
            import corporate_actions
            with patch.object(corporate_actions, "_splits", return_value=[]), patch.object(corporate_actions, "_last_bar", return_value=None):
                applied = self.client.get("/api/portfolio/corporate-actions").json()
        self.assertEqual({a["ticker"] for a in applied["applied"]}, {"CASHCO", "STOCKCO", "MIXCO"})
        closed = database.get_closed_trades(uid)
        self.assertEqual([(t["ticker"], t["pnl"], str(t["closed_at"])[:10]) for t in closed], [("CASHCO", 150, "2025-06-02")])
        lots = sorted((h["ticker"], h["account"] or "", h["shares"], h["buy_price"]) for h in database.get_user_holdings(uid))
        self.assertEqual(lots, [("BIGCO", "", 20, 0), ("BIGCO", "IRA", 5, 120)])
        import account_transfer
        destination = new_user()
        account_transfer.import_account(destination, account_transfer.export_account(uid))
        with self.as_user(destination):
            again = self.client.post("/api/portfolio/corporate-actions/merger",
                                     json={"ticker": "STOCKCO", "action_date": "2025-06-02", "new_ticker": "BIGCO", "ratio": 0.5})
            self.assertEqual(again.status_code, 409, "transferred actions must not be applied twice")

    def test_stale_holdings_need_a_fresh_benchmark(self):
        import corporate_actions
        uid = new_user()
        database.add_user_holding(uid, "LIVE", 1, 10)
        database.add_user_holding(uid, "GONE", 1, 10)
        database.add_user_holding(uid, "OLDBAR", 1, 10)
        database.add_user_holding(uid, "ERR", 1, 10)
        today = date.today().isoformat()
        bars = {"SPY": today, "LIVE": today, "GONE": "", "OLDBAR": "2020-01-02", "ERR": None}
        with patch.object(corporate_actions, "_last_bar", side_effect=bars.get):
            self.assertEqual(corporate_actions.stale_holdings(uid), [
                {"ticker": "GONE", "last_quote": None}, {"ticker": "OLDBAR", "last_quote": "2020-01-02"}])
        with patch.object(corporate_actions, "_last_bar", side_effect={**bars, "SPY": ""}.get):
            self.assertEqual(corporate_actions.stale_holdings(uid), [], "an outage must not flag every holding")

    def test_refresh_tokens_are_hashed_and_legacy_tokens_still_work_once(self):
        uid = new_user()
        database.store_refresh_token(uid, "new-token-value", "2999-01-01T00:00:00")
        stored = database._run(f"SELECT token FROM refresh_tokens WHERE user_id={database.PH}", (uid,), "all")
        self.assertEqual([r["token"] for r in stored], [database._token_digest("new-token-value")])
        self.assertEqual(database.consume_refresh_token("new-token-value")["user_id"], uid)
        self.assertIsNone(database.consume_refresh_token("new-token-value"))
        self.assertIsNone(database.consume_refresh_token(database._token_digest("new-token-value")),
                          "a leaked digest is not itself a usable token")
        database._run(f"INSERT INTO refresh_tokens (user_id, token, expires_at) VALUES ({database.PH}, {database.PH}, {database.PH})",
                      (uid, "legacy-plain", "2999-01-01T00:00:00"))
        self.assertEqual(database.consume_refresh_token("legacy-plain")["user_id"], uid)
        self.assertIsNone(database.consume_refresh_token("legacy-plain"))


if __name__ == "__main__":
    unittest.main()
