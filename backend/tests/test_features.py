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
        etrade = insights.parse_broker_csv(
            "Account Summary\nAccount,Net Account Value\nBrokerage -1234,\"$25,000.00\"\n\n"
            "Symbol,Last Price $,Change $,Change %,Quantity,Price Paid $,Day's Gain $,Total Gain $,Total Gain %,Value $\n"
            "MSFT,420.00,1.00,0.24%,10,\"$350.25\",10.00,697.50,19.91%,\"4,200.00\"\n"
            "AAPL Jan 17 '30 $150 Put,2.10,0,0%,-1,2.75,0,65,23.6%,-210\n"
            "CASH,,,,,,,,,\"1,000.00\"\nVUSXX,1.00,0,0%,\"2,500.50\",1.00,0,0,0%,\"2,500.50\"\nTOTAL,,,,,,,,,\"5,000.00\"\n")
        self.assertEqual([(r["kind"], r["ticker"]) for r in etrade["rows"]], [("stock", "MSFT"), ("option", "AAPL")])
        self.assertEqual(etrade["money_market"], [{"line": 9, "ticker": "VUSXX", "amount": 2500.5}])
        self.assertEqual(etrade["money_market_total"], 2500.5)
        mm_user = new_user()
        import accounts as accounts_module
        accounts_module.set_cash(mm_user, "Etrade", 100)
        self.assertEqual(insights.add_money_market_cash(mm_user, "Etrade", 2500.5)["cash"], 2600.5)
        self.assertEqual(insights.add_money_market_cash(mm_user, "New", 50)["cash"], 50)
        self.assertEqual(etrade["rows"][0]["price"], 350.25, "E*TRADE's 'Price Paid $' column is the cost per share")
        self.assertEqual((etrade["rows"][1]["position"], etrade["rows"][1]["premium"]), ("short", 2.75))
        self.assertEqual({s["reason"] for s in etrade["skipped"]}, {"cash / money market"})
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

    def test_fidelity_accounts_and_activity_history_rebuild_positions(self):
        import portfolio_insights as insights
        fidelity = ("Account Number,Account Name,Symbol,Description,Quantity,Last Price,Current Value,Cost Basis Total,Average Cost Basis,Type\n"
                    "Z111,Individual,SPAXX**,HELD IN MONEY MARKET,,,$1200.00,,,Cash\n"
                    "Z111,Individual,AAPL,APPLE INC,10,$200,$2000,$1500.00,$150.00,Cash\n"
                    "Z222,ROTH IRA,FCASH**,HELD IN FCASH,,,$300.00,,,Cash\n"
                    "Z222,ROTH IRA, -AAPL300117C250,AAPL JAN 17 2030 $250 CALL,-1,$5,-$500,$400.00,$4.00,Margin\n"
                    "Z222,ROTH IRA,Pending Activity,,,,$12.00,,,\n"
                    "\"The data and information in this spreadsheet is provided to you solely for your use.\"\n")
        whole = insights.parse_broker_csv(fidelity)
        self.assertEqual(whole["source_accounts"], ["Individual · Z111", "ROTH IRA · Z222"])
        self.assertEqual(whole["money_market_total"], 1500)
        roth = insights.parse_broker_csv(fidelity, "ROTH IRA · Z222")
        self.assertEqual([(r["kind"], r["ticker"]) for r in roth["rows"]], [("option", "AAPL")])
        self.assertEqual((roth["money_market"], roth["rows"][0]["premium"]), ([{"line": 4, "ticker": "FCASH", "amount": 300}], 4))

        robinhood = ('"Activity Date","Process Date","Settle Date","Instrument","Description","Trans Code","Quantity","Price","Amount"\n'
                     '"3/10/2026","3/10/2026","3/11/2026","AAPL","Apple\nCUSIP: 037833100","Sell","5","$210.00","$1,050.00"\n'
                     '"3/02/2026","3/02/2026","3/02/2026","AAPL","Option Expiration for AAPL 2/27/2026 Put $180.00","OEXP","1","",""\n'
                     '"2/20/2026","2/20/2026","2/23/2026","AAPL","AAPL 1/15/2027 Call $250.00","STO","2","$4.00","$800.00"\n'
                     '"2/10/2026","2/10/2026","2/11/2026","AAPL","AAPL 2/27/2026 Put $180.00","STO","1","$2.00","$200.00"\n'
                     '"2/05/2026","2/05/2026","2/06/2026","AAPL","Apple\nCUSIP: 037833100","Buy","10","$190.00","($1,900.00)"\n'
                     '"1/05/2026","1/05/2026","1/06/2026","AAPL","Apple\nCUSIP: 037833100","Buy","100","$180.00","($18,000.00)"\n'
                     '"1/04/2026","1/04/2026","1/04/2026","MSFT","Microsoft","Sell","3","$400.00","$1,200.00"\n'
                     '"1/03/2026","1/03/2026","1/03/2026","AAPL","Cash Div: R/D 2025-12-01","CDIV","","","$5.00"\n'
                     '"1/02/2026","1/02/2026","1/02/2026","","ACH Deposit","ACH","","","$20,000.00"\n'
                     '"","","","","","","","","","The data provided is for informational purposes only."\n')
        rh = insights.parse_activity_csv(robinhood)
        stocks = [(r["shares"], r["price"], r["acquired"]) for r in rh["rows"] if r["kind"] == "stock"]
        self.assertEqual(stocks, [(95, 180, "2026-01-05"), (10, 190, "2026-02-05")], "FIFO sale takes the oldest lot")
        options = [r for r in rh["rows"] if r["kind"] == "option"]
        self.assertEqual([(o["strike"], o["position"], o["contracts"], o["premium"]) for o in options], [(250, "short", 2, 4)])
        self.assertEqual(rh["skipped"][0]["symbol"], "MSFT")
        self.assertEqual(rh["ignored"], {"CDIV": 1})

        webull = ("Name,Symbol,Side,Status,Filled,Total Qty,Price,Avg Price,Time-in-Force,Placed Time,Filled Time\n"
                  "AAPL,AAPL300117C00250000,Sell,Filled,1,1,5.00,5.10,DAY,01/05/2026 09:30:00 EST,01/05/2026 09:30:05 EST\n"
                  "AAPL,AAPL300117C00250000,Buy,Filled,1,1,2.00,1.90,DAY,02/05/2026 09:30:00 EST,02/05/2026 09:30:05 EST\n"
                  "NVDA,NVDA,Buy,Filled,10,10,@MKT,120.50,DAY,01/02/2026 10:00:00 EST,01/02/2026 10:00:01 EST\n"
                  "NVDA,NVDA,Buy,Cancelled,0,10,100.00,,GTC,01/03/2026 10:00:00 EST,\n")
        wb = insights.parse_activity_csv(webull)
        self.assertEqual([(r["kind"], r["ticker"], r.get("price")) for r in wb["rows"]], [("stock", "NVDA", 120.5)],
                         "a buy that closes a short option leaves nothing open; Avg Price is the fill")
        with self.assertRaisesRegex(ValueError, "Trans Code"):
            insights.parse_activity_csv("Symbol,Quantity\nAAPL,1\n")
        uid = new_user()
        with self.as_user(uid):
            preview = self.client.post("/api/portfolio/import", json={"csv": webull, "kind": "activity"}).json()
            self.assertEqual(preview["trades"], 3)
            done = self.client.post("/api/portfolio/import", json={"csv": fidelity, "commit": True,
                                                                   "source_account": "Individual · Z111", "account": "Fido"}).json()
        self.assertEqual((done["imported"], done["cash"]["cash"]), (1, 1200))
        self.assertEqual([(h["ticker"], h["account"]) for h in database.get_user_holdings(uid)], [("AAPL", "Fido")])

    def test_editing_a_lot_can_correct_its_purchase_date(self):
        uid = new_user()
        lot = database.add_user_holding(uid, "AMD", 100, 59.38, account="Etrade")
        with self.as_user(uid):
            future = (date.today() + timedelta(days=2)).isoformat()
            self.assertEqual(self.client.put(f"/api/portfolio/{lot['id']}", json={
                "ticker": "AMD", "shares": 100, "price": 59.38, "acquired": future}).status_code, 422)
            kept = self.client.put(f"/api/portfolio/{lot['id']}", json={"ticker": "AMD", "shares": 100, "price": 59.38})
            self.assertEqual(kept.status_code, 200, kept.text)
            before = str(kept.json()["date_added"])
            edited = self.client.put(f"/api/portfolio/{lot['id']}", json={
                "ticker": "AMD", "shares": 100, "price": 59.38, "acquired": "2019-03-15"})
            self.assertEqual(edited.status_code, 200, edited.text)
        self.assertTrue(str(edited.json()["date_added"]).startswith("2019-03-15"))
        self.assertNotEqual(before[:10], "2019-03-15", "omitting the date leaves it unchanged")
        self.assertEqual(edited.json()["account"], "Etrade")

    def test_system_status_reports_services_without_secrets(self):
        import pandas as pd
        import system_status
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        secret = "sk-test-secret-123"
        bars = pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2026-10-06"]))
        with patch.object(system_status, "_SECRETS", [secret]), \
             patch("providers.finnhub_enabled", return_value=True), \
             patch("providers.finnhub_quote", side_effect=RuntimeError(f"403 for url ...?token={secret}")), \
             patch("stock_data.get_stock_data", return_value=bars), \
             patch.object(system_status, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()), \
             self.as_user(new_user()):
            body = self.client.get("/api/status").json()
        checks = {c["name"]: c for c in body["checks"]}
        self.assertTrue(checks["Database"]["ok"])
        self.assertFalse(checks["Finnhub quotes"]["ok"])
        self.assertNotIn(secret, str(body))
        self.assertIn("2026-10-06", checks["Yahoo price history"]["detail"])
        self.assertIn("jobs", body["scheduler"])

    def test_sync_import_reconciles_an_account_and_keeps_matching_lots(self):
        import accounts as accounts_module
        uid = new_user()
        amd = database.add_user_holding(uid, "AMD", 100, 59.38, "2019-03-15 00:00:00", account="Etrade")
        database.add_user_holding(uid, "MSFT", 50, 300, account="Etrade")
        database.add_user_holding(uid, "MSFT", 5, 300, account="IRA")
        database.add_user_option(uid, "AMD", "call", 580, "2099-06-17", 10, 1, "short", account="Etrade")
        accounts_module.set_cash(uid, "Etrade", 999)
        csv_text = ("Symbol,Quantity,Price Paid,Value\nAMD,100,59.38,64000\nMSFT,60,310,25000\nNVDA,10,180,2000\n"
                    "VUSXX,500,1,500\n")
        with self.as_user(uid):
            preview = self.client.post("/api/portfolio/import", json={"csv": csv_text, "account": "Etrade", "mode": "sync"}).json()
            diff = {s["ticker"]: s["status"] for s in preview["reconcile"]["stocks"]}
            self.assertEqual(diff, {"AMD": "match", "MSFT": "changed", "NVDA": "new"})
            self.assertEqual([o["status"] for o in preview["reconcile"]["options"]], ["missing"])
            self.assertEqual(preview["reconcile"]["changes"], 3)
            self.assertEqual(len(database.get_user_holdings(uid)), 3, "preview changes nothing")
            done = self.client.post("/api/portfolio/import", json={"csv": csv_text, "account": "Etrade", "mode": "sync", "commit": True}).json()
        self.assertEqual((done["sync"]["kept"], done["cash"]["cash"]), (1, 500), "money-market cash is set, not added")
        lots = {(h["ticker"], h["account"]): h for h in database.get_user_holdings(uid)}
        self.assertEqual(lots[("AMD", "Etrade")]["id"], amd["id"], "matching lot untouched")
        self.assertTrue(str(lots[("AMD", "Etrade")]["date_added"]).startswith("2019-03-15"))
        self.assertEqual(lots[("MSFT", "Etrade")]["shares"], 60)
        self.assertEqual(lots[("MSFT", "IRA")]["shares"], 5, "other accounts are not touched")
        self.assertIn(("NVDA", "Etrade"), lots)
        self.assertEqual(database.get_user_options(uid), [])
        with self.as_user(uid):
            again = self.client.post("/api/portfolio/import", json={"csv": csv_text, "account": "Etrade", "mode": "sync"}).json()
        self.assertEqual(again["reconcile"]["changes"], 0, "re-syncing the same file is a no-op")

    def test_expiry_ladder_cash_needs_and_tax_smart_lot_delivery(self):
        import expiry_ladder
        uid = new_user()
        database.add_user_holding(uid, "AMD", 100, 60, "2019-01-02 00:00:00", account="E")
        database.add_user_holding(uid, "AMD", 100, 500, (date.today() - timedelta(days=30)).isoformat() + " 00:00:00", account="E")
        soon = (date.today() + timedelta(days=60)).isoformat()
        first = database.add_user_option(uid, "AMD", "call", 580, soon, 10, 1, "short", account="E")
        database.add_user_option(uid, "AMD", "call", 650, "2099-12-15", 10, 2, "short", account="E")
        database.add_user_option(uid, "KO", "put", 70, soon, 1, 2, "short")
        database.add_user_option(uid, "SPY", "put", 400, "2026-01-16", 1, 1, "short")
        with patch.object(expiry_ladder, "get_quote", side_effect=lambda t: {"price": {"AMD": 640, "KO": 65}[t]}):
            result = expiry_ladder.build(uid, {"positions": [{"id": first["id"], "delta": 0.7}]})
        self.assertEqual([e["expiry"] for e in result["expiries"]], [soon, "2099-12-15"], "expired options are left out")
        june = result["expiries"][0]
        self.assertEqual((june["cash_if_itm_puts_assigned"], june["shares_if_itm_calls_assigned"]), (14000, 100))
        call = next(p for p in june["positions"] if p["type"] == "call")
        self.assertEqual(call["chance_itm_pct"], 70)
        self.assertEqual(call["oldest_first"]["gain"], 52000, "oldest lot has the $60 basis")
        self.assertEqual(call["highest_cost_first"]["gain"], 8000, "highest-cost lot has the $500 basis")
        self.assertEqual(call["gain_difference"], 44000)
        self.assertEqual((call["oldest_first"]["long_term_gain"], call["highest_cost_first"]["short_term_gain"]), (52000, 8000))
        december = next(p for p in result["expiries"][1]["positions"])
        self.assertEqual(december["oldest_first"]["lots"][0]["basis"], 500, "the first call already took the oldest lot")
        self.assertEqual(december["oldest_first"]["uncovered_shares"], 100, "only one 100-share lot is left for two contracts")

    def test_personal_rules_are_saved_validated_and_flagged(self):
        import accounts as accounts_module
        import next_steps
        uid = new_user()
        database.add_user_holding(uid, "AMD", 200, 100, "2026-01-02 00:00:00", account="A")
        database.add_user_holding(uid, "KO", 100, 60, "2026-01-02 00:00:00", account="A")
        database.add_user_option(uid, "AMD", "call", 90, "2099-01-15", 3, 1, "short", account="A")
        database.add_user_option(uid, "KO", "put", 60, "2099-01-15", 1, 1, "short", account="A")
        accounts_module.set_cash(uid, "A", 7000)
        with self.as_user(uid):
            self.assertEqual(self.client.get("/api/rules").json()["max_position_pct"], None)
            self.assertEqual(self.client.put("/api/rules", json={"max_position_pct": 0}).status_code, 422)
            saved = self.client.put("/api/rules", json={"max_position_pct": 50, "min_free_cash_pct": 10, "take_profit_pct": 60,
                                                        "no_calls_below_cost": True, "no_short_through_earnings": True}).json()
        self.assertEqual(saved["take_profit_pct"], 60)
        actions = {"positions": [
            {"id": 1, "ticker": "AMD", "position": "short", "type": "call", "strike": 90, "expiry": "2099-01-15",
             "profit_captured_pct": 70, "actions": [{"level": "warn", "code": "earnings", "text": "Earnings"}]},
            {"id": 2, "ticker": "KO", "position": "short", "type": "put", "strike": 60, "expiry": "2099-01-15",
             "profit_captured_pct": 20, "actions": []}]}
        quote = lambda t: {"price": {"AMD": 150, "KO": 60}[t]}  # noqa: E731
        with patch.object(next_steps, "get_quote", side_effect=quote), patch("portfolio_insights.get_quote", side_effect=quote):
            items = next_steps.build(uid, actions)["items"]
        codes = {i["code"] for i in items}
        self.assertTrue({"rule_max_position", "rule_free_cash", "rule_take_profit", "rule_call_below_cost", "rule_earnings"} <= codes)
        self.assertNotIn("concentration", codes, "a personal limit replaces the default 25% check")
        self.assertIn("your limit 50%", next(i for i in items if i["code"] == "rule_max_position")["title"])
        self.assertIn("is 2% of", next(i for i in items if i["code"] == "rule_free_cash")["title"], "(7000-6000)/(7000+36000)")

    def test_trim_plan_sizes_sales_to_target_weight_with_highest_cost_lots_first(self):
        import trim_plan
        uid = new_user()
        database.add_user_holding(uid, "AMD", 100, 50, "2019-01-02 00:00:00")
        database.add_user_holding(uid, "AMD", 100, 140, (date.today() - timedelta(days=10)).isoformat() + " 00:00:00")
        database.add_user_holding(uid, "KO", 100, 60, "2026-01-02 00:00:00")
        with patch.object(trim_plan, "get_quote", side_effect=lambda t: {"price": {"AMD": 150, "KO": 100}[t]}):
            result = trim_plan.plan(uid, "AMD", 50, steps=2, spacing_pct=10)
            self.assertEqual(result["current_pct"], 75.0)
            first, second = result["tranches"]
            self.assertEqual((first["price"], second["price"]), (150, 165))
            self.assertEqual(first["shares"], 88.89, "62.5% at $150: keep 0.625*10000/(0.375*150)")
            self.assertEqual(result["shares_to_sell"], round(200 - 10000 / 165, 2), "50% exactly at the last step's price")
            self.assertEqual(second["weight_after_pct"], 50.0)
            self.assertEqual(first["short_term_gain"], round(88.89 * 10, 2), "the $140 lot goes first")
            self.assertGreater(second["long_term_gain"], 0, "then the 2019 lot")
            self.assertEqual(trim_plan.plan(uid, "KO", 50)["shares_to_sell"], 0)
            with self.assertRaises(LookupError):
                trim_plan.plan(uid, "TSLA", 50)

    def test_my_stock_summarizes_positions_results_and_chart_levels(self):
        uid = new_user()
        database.add_user_holding(uid, "AMD", 100, 50, "2020-01-02 00:00:00", account="A")
        database.add_user_holding(uid, "AMD", 100, 70, "2021-01-02 00:00:00", account="B")
        database.add_user_option(uid, "AMD", "call", 580, "2099-06-16", 10, 1, "short", account="A")
        database.add_user_holding(uid, "MSFT", 10, 300)
        database.add_user_alert(uid, "AMD", "price_above", 700, None)
        database.add_user_alert(uid, "AMD", "rsi_above", 70, None)
        with self.as_user(uid):
            self.assertEqual(self.client.get("/api/stock/AMD/mine").status_code, 200)
            amd = self.client.get("/api/stock/amd/mine").json()
            self.assertTrue(self.client.get("/api/stock/TSLA/mine").json()["empty"])
        self.assertEqual((amd["shares"], amd["avg_cost"], amd["first_bought"]), (200, 60, "2020-01-02"))
        self.assertEqual([(a["account"], a["avg_cost"]) for a in amd["accounts"]], [("A", 50), ("B", 70)])
        self.assertEqual([(l["kind"], l["price"]) for l in amd["levels"]],
                         [("alert", 700), ("short_call", 580), ("cost", 70), ("cost", 50)], "RSI alerts are not price levels")
        self.assertEqual(self.client.get("/api/stock/AMD/mine").status_code, 401)

    def test_buy_zones_suggest_a_put_to_wait_and_event_week_lists_dates(self):
        import buy_zones
        uid = new_user()
        database.add_to_watchlist(uid, "NVDA", None)
        with self.as_user(uid):
            self.assertEqual(self.client.put("/api/watchlist/buy-zones/NVDA", json={"price": 0}).status_code, 422)
            self.assertEqual(self.client.put("/api/watchlist/buy-zones/NVDA", json={"price": 170}).status_code, 200)
            self.assertEqual(self.client.put("/api/watchlist/buy-zones/KO", json={"price": 80}).status_code, 200)
        self.assertEqual(buy_zones.get_zones(uid), {"NVDA": 170, "KO": 80})
        soon = (date.today() + timedelta(days=5)).isoformat()
        rows = [dict(strike=k, mid=m, bid=m - 0.1, ask=m + 0.1, delta=0.2, p_itm=0.18, oi=oi)
                for k, m, oi in ((175, 6.0, 50), (170, 4.0, 900), (160, 2.0, 900), (180, 8.0, 900))]
        with patch.object(buy_zones, "get_quote", side_effect=lambda t: {"price": {"NVDA": 190, "KO": 70}[t]}), \
             patch.object(buy_zones, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()), \
             patch.object(buy_zones.oa, "_expirations", return_value=["2099-01-01", "2099-02-01"]), \
             patch.object(buy_zones.oa, "_live", return_value=True), \
             patch.object(buy_zones.oa, "_dte", side_effect=lambda e: {"2099-01-01": 30, "2099-02-01": 60}[e]), \
             patch.object(buy_zones.oa, "_years", return_value=30 / 365), \
             patch.object(buy_zones.oa, "_chain", return_value=([], [])), \
             patch.object(buy_zones.oa, "_otm_rows", return_value=rows), \
             patch.object(buy_zones, "_ex_dividend", side_effect=lambda t: soon if t == "NVDA" else None), \
             patch.object(buy_zones.oa, "earnings_info", side_effect=lambda t: {"next": soon if t == "NVDA" else None}):
            zones = buy_zones.overview(uid)["items"]
            with self.as_user(uid):
                events = self.client.get("/api/watchlist/events").json()["events"]
        ko, nvda = zones
        self.assertTrue(ko["in_zone"])
        self.assertIsNone(ko["put"])
        self.assertEqual((nvda["put"]["strike"], nvda["put"]["expiry"]), (170, "2099-01-01"), "highest liquid strike <= target")
        self.assertEqual((nvda["put"]["effective_entry"], nvda["put"]["cash_needed"]), (166, 17000))
        self.assertEqual([(e["ticker"], e["kind"], e["watching"]) for e in events], [("NVDA", "earnings", True), ("NVDA", "ex_dividend", True)])
        with self.as_user(uid):
            self.client.put("/api/watchlist/buy-zones/KO", json={"price": None})
        self.assertEqual(buy_zones.get_zones(uid), {"NVDA": 170})

    def test_portfolio_fit_scores_correlation_sector_size_and_cash(self):
        import numpy as np
        import pandas as pd
        import accounts as accounts_module
        import portfolio_fit
        uid = new_user()
        database.add_user_holding(uid, "AMD", 100, 50)
        database.add_user_holding(uid, "MSFT", 10, 300)
        accounts_module.set_cash(uid, "Default", 10000)
        days = pd.bdate_range("2026-01-01", periods=120)
        base = np.random.default_rng(1).normal(0, 0.02, len(days))
        noise = np.random.default_rng(2).normal(0, 0.02, len(days))
        paths = {"AMD": base, "MSFT": base * 0.5 + noise * 0.5, "NVDA": base + noise * 0.1, "KO": -base}
        frame = lambda t: pd.DataFrame({"Close": 100 * np.cumprod(1 + paths[t])}, index=days)  # noqa: E731
        sectors = {"AMD": "Semiconductors", "MSFT": "Software", "NVDA": "Semiconductors", "KO": "Beverages"}
        with patch.object(portfolio_fit, "get_quote", side_effect=lambda t: {"price": {"AMD": 150, "MSFT": 300}[t]}), \
             patch.object(portfolio_fit, "get_key_metrics", side_effect=lambda t: {"sector": sectors[t]}), \
             patch("providers.finnhub_enabled", return_value=False), \
             patch.object(portfolio_fit, "get_stock_data", side_effect=lambda t, **kw: frame(t)), \
             patch.object(portfolio_fit, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()), \
             self.as_user(uid):
            body = self.client.post("/api/portfolio/fit", json={"items": [
                {"ticker": "NVDA", "cash_needed": 20000}, {"ticker": "KO", "cash_needed": 5000}, {"ticker": "AMD"}]}).json()
            empty_user = new_user()
            self.assertTrue(portfolio_fit.fit(empty_user, [{"ticker": "KO"}])["empty"])
        fits = {f["ticker"]: f for f in body["items"]}
        self.assertEqual(fits["KO"]["label"], "Good fit")
        self.assertLess(fits["KO"]["correlation"], 0)
        self.assertGreater(fits["NVDA"]["correlation"], 0.7)
        self.assertIn("Needs $20,000", " ".join(r["text"] for r in fits["NVDA"]["reasons"]))
        self.assertEqual(fits["NVDA"]["label"], "Poor fit", "correlated, heavy sector, cash doesn't fit")
        self.assertIn("Already 83% of your stock value", " ".join(r["text"] for r in fits["AMD"]["reasons"]), "15000 / 18000")

    def test_next_steps_flag_cash_concentration_and_covered_calls(self):
        import accounts as accounts_module
        import next_steps
        uid = new_user()
        database.add_user_holding(uid, "AMD", 300, 100, "2026-01-02 00:00:00", account="A")
        database.add_user_holding(uid, "KO", 10, 60, "2026-01-02 00:00:00", account="A")
        database.add_user_option(uid, "AMD", "call", 200, "2099-01-15", 3, 1, "short", account="A")
        database.add_user_option(uid, "KO", "put", 50, "2099-01-15", 1, 2, "short", account="B")
        accounts_module.set_cash(uid, "A", 20000)
        accounts_module.set_cash(uid, "B", 4000)
        actions = {"positions": [{"ticker": "KO", "strike": 50, "type": "put", "actions": [
            {"level": "act", "text": "Take profit."}, {"level": "info", "text": "Later."}]}]}
        quote = lambda t: {"price": {"AMD": 150, "KO": 60}[t]}
        with patch.object(next_steps, "get_quote", side_effect=quote), patch("portfolio_insights.get_quote", side_effect=quote):
            result = next_steps.build(uid, actions)
        codes = [(i["level"], i["code"], i.get("account") or i.get("ticker")) for i in result["items"]]
        self.assertEqual(codes[0], ("act", "options_act", None))
        self.assertIn(("warn", "over_committed", "B"), codes)
        self.assertIn(("warn", "concentration", "AMD"), codes)
        self.assertIn(("idea", "idle_cash", "A"), codes)
        call = next(i for i in result["items"] if i["code"] == "covered_call")
        self.assertEqual((call["ticker"], call["link"]["shares"]), ("AMD", 200), "one of three blocks is already covered")
        self.assertNotIn("KO", [i.get("ticker") for i in result["items"] if i["code"] == "covered_call"])
        with self.as_user(uid), patch.object(next_steps, "get_quote", side_effect=quote), \
             patch("portfolio_insights.get_quote", side_effect=quote), \
             patch.object(self.main.options_desk, "position_actions", return_value={"positions": []}):
            self.assertEqual(self.client.get("/api/portfolio/next-steps").status_code, 200)

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
