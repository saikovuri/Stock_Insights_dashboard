import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

if not os.environ.get("STOCKPILOT_DB_PATH"):
    _database_dir = tempfile.TemporaryDirectory()
    os.environ["DATABASE_URL"] = ""
    os.environ["STOCKPILOT_DB_PATH"] = os.path.join(_database_dir.name, "test.db")

import pandas as pd

import accounts
import database
import investing
import risk_guard
import trading_rules

U = 31
EXPIRY = "2099-01-15"
PRICES = {"AAPL": 200.0, "VOO": 500.0, "QQQ": 400.0, "TSLA": 250.0, "SPY": 600.0}


def quote(ticker):
    return {"price": PRICES.get(ticker)}


class Base(unittest.TestCase):
    def setUp(self):
        conn = database.get_db()
        for table in ("transactions", "closed_options", "closed_trades", "options", "holdings", "account_cash", "account_roles",
                      "position_stops", "invest_plans", "user_rules"):
            conn.execute(f"DELETE FROM {table} WHERE user_id=?", (U,))
        conn.execute("DELETE FROM kv_cache WHERE key LIKE 'sweep:31:%'")
        conn.execute(f"INSERT OR IGNORE INTO users (id, username, password_hash, display_name) VALUES ({U}, 'risk', 'unused', 'Risk')")
        conn.commit()
        conn.close()
        self.quotes = patch.object(risk_guard, "get_quote", side_effect=quote)
        self.quotes.start()

    def tearDown(self):
        self.quotes.stop()

    def closed_stock(self, ticker, pnl, opened, closed, account=None, shares=10, buy=100.0):
        database._run("""INSERT INTO closed_trades (user_id, ticker, shares, buy_price, sell_price, pnl, pnl_pct, closed_at, acquired_at, account)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (U, ticker, shares, buy, buy + pnl / shares, pnl, pnl / (buy * shares) * 100, f"{closed} 20:00:00", f"{opened} 14:00:00", account))


class RiskTests(Base):
    def test_position_risk_rules(self):
        database.add_user_holding(U, "AAPL", 50, 180)
        database.add_user_holding(U, "TSLA", 100, 240)
        risk_guard.set_stop(U, None, "AAPL", 190)
        database.add_user_option(U, "TSLA", "call", 300, EXPIRY, 2.0, 1, "short")      # covered by 100 TSLA
        database.add_user_option(U, "AAPL", "call", 250, EXPIRY, 1.5, 1, "short")      # 50 shares: uncovered
        database.add_user_option(U, "VOO", "put", 450, EXPIRY, 4.0, 2, "short")
        database.add_user_option(U, "QQQ", "call", 420, EXPIRY, 6.0, 1, "long")
        database.add_user_spread(U, "SPY", [dict(position="short", option_type="put", strike=590, expiry=EXPIRY, premium=3.0, ratio=1),
                                            dict(position="long", option_type="put", strike=580, expiry=EXPIRY, premium=1.0, ratio=1)], 1)
        rows = {r["label"] if r["kind"] != "stock" else r["ticker"]: r for r in risk_guard.positions(U, {})}
        self.assertEqual((rows["AAPL"]["risk"], rows["AAPL"]["basis"]), (500.0, "down to your $190 stop"))
        self.assertEqual((rows["TSLA"]["risk"], rows["TSLA"]["flags"]), (25000.0, ["no_stop"]))
        self.assertEqual(rows[f"short $300 call {EXPIRY} × 1"]["risk"], 0.0)
        self.assertIsNone(rows[f"short $250 call {EXPIRY} × 1"]["risk"])
        self.assertEqual(rows[f"short $450 put {EXPIRY} × 2"]["risk"], 89200.0)
        self.assertEqual(rows[f"long $420 call {EXPIRY} × 1"]["risk"], 600.0)
        self.assertEqual(rows["Bull put $580/$590 × 1"]["risk"], 800.0)
        with_stop = {r["label"]: r for r in risk_guard.positions(U, {"stop_loss_multiple": 2}) if r["kind"] == "option"}
        self.assertEqual(with_stop[f"short $450 put {EXPIRY} × 2"]["risk"], 1600.0)
        self.assertEqual(with_stop[f"short $250 call {EXPIRY} × 1"]["risk"], 300.0)

    def test_heat_counts_trading_accounts_only(self):
        database.add_user_holding(U, "AAPL", 10, 180, account="Trade")
        database.add_user_holding(U, "VOO", 100, 400, account="Roth")
        risk_guard.set_stop(U, "Trade", "AAPL", 180)
        accounts.set_cash(U, "Trade", 8000)
        accounts.set_role(U, "Roth", "long_term")
        h = risk_guard.heat(U, {"max_open_risk_pct": 1})
        self.assertEqual([p["ticker"] for p in h["positions"]], ["AAPL"])
        self.assertEqual((h["total_risk"], h["trading_value"], h["pct"], h["over_limit"]), (200.0, 10000.0, 2.0, True))

    def test_circuit_breaker_month_loss_and_streak(self):
        accounts.set_cash(U, None, 10000)
        today = date(2026, 10, 20)
        self.closed_stock("AAPL", 150, "2026-09-01", "2026-09-30")
        self.closed_stock("AAPL", -300, "2026-10-01", "2026-10-15")
        self.closed_stock("TSLA", -250, "2026-10-02", "2026-10-19")
        c = risk_guard.circuit(U, {"max_monthly_loss_pct": 5}, 10000, {}, today)
        self.assertEqual((c["month_net"], c["month_loss_pct"], c["active"], c["until"]), (-550.0, 5.5, True, "2026-11-01"))
        c = risk_guard.circuit(U, {"loss_streak": 2, "cooldown_days": 3}, 10000, {}, today)
        self.assertEqual((c["streak"], c["active"], c["until"]), (2, True, "2026-10-22"))
        self.assertFalse(risk_guard.circuit(U, {"loss_streak": 2, "cooldown_days": 3}, 10000, {}, date(2026, 10, 23))["active"])
        self.assertFalse(risk_guard.circuit(U, {"loss_streak": 3}, 10000, {}, today)["active"])

    def test_entry_check_warns_and_sizes(self):
        accounts.set_cash(U, None, 20000)
        trading_rules.save_rules(U, {"max_trade_risk_pct": 1, "max_open_risk_pct": 3, "max_position_pct": 30})
        r = risk_guard.check(U, {"kind": "stock", "ticker": "AAPL", "shares": 50, "price": 200, "stop": 190})
        self.assertEqual((r["risk"], r["risk_pct"], r["max_size"]), (500.0, 2.5, 20))
        self.assertEqual({w["code"] for w in r["warnings"]}, {"trade_risk", "position"})
        no_stop = risk_guard.check(U, {"kind": "stock", "ticker": "AAPL", "shares": 1, "price": 200})
        self.assertIn("No stop", no_stop["notes"][0])
        option = risk_guard.check(U, {"kind": "option", "ticker": "QQQ", "position": "long", "option_type": "call",
                                      "strike": 420, "premium": 2.0, "contracts": 1})
        self.assertEqual((option["risk"], option["warnings"]), (200.0, []))
        structure = risk_guard.check(U, {"kind": "structure", "ticker": "SPY", "contracts": 2, "legs": [
            dict(position="short", option_type="put", strike=590, expiry=EXPIRY, premium=3.0, ratio=1),
            dict(position="long", option_type="put", strike=580, expiry=EXPIRY, premium=1.0, ratio=1)]})
        self.assertEqual((structure["risk"], structure["heat_pct_after"]), (1600.0, 8.0))
        self.assertEqual({w["code"] for w in structure["warnings"]}, {"trade_risk", "open_risk"})
        accounts.set_role(U, "Roth", "long_term")
        long_term = risk_guard.check(U, {"kind": "stock", "ticker": "VOO", "shares": 10, "price": 500, "account": "Roth"})
        self.assertEqual((long_term["role"], long_term["warnings"], long_term["risk_pct"]), ("long_term", [], None))

    def test_entry_check_counts_shares_already_covering_calls(self):
        database.add_user_holding(U, "TSLA", 100, 240)
        call = {"kind": "option", "ticker": "TSLA", "position": "short", "option_type": "call", "strike": 300, "premium": 2.0, "contracts": 1}
        self.assertEqual(risk_guard.check(U, call)["risk"], 0.0)
        database.add_user_option(U, "TSLA", "call", 300, EXPIRY, 2.0, 1, "short")
        second = risk_guard.check(U, call)
        self.assertIsNone(second["risk"])
        self.assertIn("unlimited", {w["code"] for w in second["warnings"]})

    def test_breached_and_stale_stops(self):
        import main
        from fastapi.testclient import TestClient
        database.add_user_holding(U, "AAPL", 10, 180)
        risk_guard.set_stop(U, None, "AAPL", 210)   # above the $200 price
        row = next(r for r in risk_guard.positions(U, {}) if r["ticker"] == "AAPL")
        self.assertEqual((row["risk"], row["flags"]), (2000.0, ["stop_breached"]))
        trading_rules.save_rules(U, {"max_open_risk_pct": 50})
        self.assertIn("rule_stop_breached", {i["code"] for i in risk_guard.next_step_items(U, trading_rules.get_rules(U))})
        risk_guard.set_stop(U, None, "AAPL", 190)
        client = TestClient(main.app)
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": U}}):
            self.assertEqual(client.post("/api/portfolio/sell", json={"ticker": "AAPL", "shares": 4, "price": 200}).status_code, 200)
            self.assertEqual(risk_guard.get_stops(U), {(database.DEFAULT_ACCOUNT, "AAPL"): 190.0})
            self.assertEqual(client.post("/api/portfolio/sell", json={"ticker": "AAPL", "shares": 6, "price": 200}).status_code, 200)
        self.assertEqual(risk_guard.get_stops(U), {})
        database.add_user_holding(U, "AAPL", 5, 200)
        self.assertNotIn("down to", risk_guard.check(U, {"kind": "stock", "ticker": "AAPL", "shares": 5, "price": 200})["basis"])

    def test_next_steps_show_circuit_breaker_and_missing_stops(self):
        import next_steps
        accounts.set_cash(U, None, 10000)
        database.add_user_holding(U, "AAPL", 10, 180)
        self.closed_stock("TSLA", -900, date.today().replace(day=1).isoformat(), date.today().isoformat())
        trading_rules.save_rules(U, {"max_monthly_loss_pct": 5, "max_trade_risk_pct": 2})
        with patch("next_steps.get_quote", side_effect=quote):
            codes = {i["code"] for i in next_steps.build(U, {"positions": []})["items"]}
        self.assertTrue({"rule_circuit_breaker", "rule_no_stop"} <= codes, codes)


class InvestingTests(Base):
    def test_split_drift_and_rebalance(self):
        database.add_user_holding(U, "VOO", 10, 450, account="Roth")
        database.add_user_holding(U, "AAPL", 20, 150, account="Trade")
        accounts.set_cash(U, "Trade", 1000)
        accounts.set_role(U, "Roth", "long_term")
        accounts.set_role(U, "Trade", "trading")
        s = investing.split(U, {"target_trading_pct": 20})
        self.assertEqual((s["by_role"], s["trading_pct"], s["drift_pct"]), ({"long_term": 5000.0, "trading": 5000.0}, 50.0, 30.0))
        self.assertEqual(s["rebalance"], {"from": "trading", "to": "long_term", "amount": 3000.0})

    def test_plan_suggestions_projection_and_due(self):
        with self.assertRaisesRegex(ValueError, "add up to 100"):
            investing.save_plan(U, {"monthly": 500, "targets": [{"ticker": "VOO", "pct": 60}]})
        buys = investing.suggest_buys([{"ticker": "VOO", "pct": 60}, {"ticker": "QQQ", "pct": 40}],
                                      {"VOO": 900, "QQQ": 100}, {"VOO": 500, "QQQ": 400}, 1000)
        # $2,000 after buying: VOO needs $1,200 (has $900), QQQ needs $800 (has $100)
        self.assertEqual([(b["ticker"], b["buy"]) for b in buys], [("VOO", 300.0), ("QQQ", 700.0)])
        self.assertEqual(buys[1]["shares"], 1.75)
        self.assertEqual(round(investing.project(0, 100, 1, 0)), 1200)
        self.assertAlmostEqual(investing.project(1000, 0, 10, 0.07), 1000 * (1 + 0.07 / 12) ** 120, places=4)
        self.assertEqual(investing.years_to_goal(0, 1000, 12000, 0), 1.0)
        database.add_user_holding(U, "VOO", 1, 480, account="Roth")
        investing.save_plan(U, {"account": "Roth", "monthly": 500, "day": 1, "targets": [{"ticker": "VOO", "pct": 60}, {"ticker": "QQQ", "pct": 40}],
                                "goal": 100000, "assumed_return_pct": 7})
        status = investing.plan_status(U, date.today())
        self.assertEqual((status["invested_this_month"], status["remaining"], status["due"]), (480.0, 20.0, True))
        self.assertEqual(round(sum(b["buy"] for b in status["buys"]), 2), 20.0)
        self.assertEqual([p["rate_pct"] for p in status["projection"]], [4.0, 7.0, 10.0])

    def test_profit_sweep(self):
        accounts.set_cash(U, "Trade", 5000)
        accounts.set_cash(U, "Roth", 1000)
        accounts.set_role(U, "Roth", "long_term")
        today = date(2026, 10, 20)
        self.closed_stock("AAPL", 800, "2026-09-02", "2026-09-20", account="Trade")
        self.closed_stock("VOO", 5000, "2026-01-02", "2026-09-21", account="Roth")
        status = investing.sweep_status(U, {"profit_sweep_pct": 25}, today)
        self.assertEqual((status["month"], status["trading_net"], status["amount"], status["done"]), ("2026-09", 800.0, 200.0, False))
        investing.record_sweep(U, "Trade", "Roth", 200, today)
        cash = {a["name"]: a["cash"] for a in accounts.list_accounts(U)["accounts"]}
        self.assertEqual((cash["Trade"], cash["Roth"]), (4800.0, 1200.0))
        self.assertTrue(investing.sweep_status(U, {"profit_sweep_pct": 25}, today)["done"])
        with self.assertRaisesRegex(ValueError, "already recorded"):
            investing.record_sweep(U, "Trade", "Roth", 200, today)
        cash = {a["name"]: a["cash"] for a in accounts.list_accounts(U)["accounts"]}
        self.assertEqual((cash["Trade"], cash["Roth"]), (4800.0, 1200.0))

    def test_profit_sweep_without_cash_on_both_sides_only_records(self):
        accounts.set_cash(U, "Trade", 5000)
        accounts.set_role(U, "Roth", "long_term")
        database.add_user_holding(U, "VOO", 1, 480, account="Roth")
        today = date(2026, 10, 20)
        result = investing.record_sweep(U, "Trade", "Roth", 200, today)
        self.assertEqual(result["cash_updated"], [])
        cash = {a["name"]: a["cash"] for a in accounts.list_accounts(U)["accounts"]}
        self.assertEqual(cash["Trade"], 5000.0)
        self.assertTrue(investing.sweep_status(U, {"profit_sweep_pct": 25}, today)["done"])

    def test_scorecard_against_spy(self):
        self.closed_stock("AAPL", 100, "2026-01-02", "2026-03-02", shares=10, buy=100)   # $1,000 in SPY: +10% -> +100
        self.closed_stock("TSLA", -50, "2026-03-02", "2026-04-01", shares=5, buy=200)    # $1,000 in SPY: -5% -> -50
        closes = pd.Series([500.0, 550.0, 522.5], index=pd.to_datetime(["2026-01-02", "2026-03-02", "2026-04-01"]))
        with patch.object(investing, "_spy_closes", return_value=closes):
            card = investing.scorecard(U, "trading")
        self.assertEqual((card["trades"], card["totals"]["net"], card["totals"]["spy"], card["totals"]["edge"]), (2, 50.0, 50.0, 0.0))
        self.assertEqual([m["month"] for m in card["months"]], ["2026-03", "2026-04"])
        self.assertEqual(card["groups"][0]["strategy"], "Stocks")

    def test_api(self):
        import main
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": U}}):
            self.assertEqual(client.put("/api/invest/role", json={"account": "Roth", "role": "long_term"}).json()["role"], "long_term")
            self.assertEqual(client.put("/api/invest/role", json={"account": "Roth", "role": "gamble"}).status_code, 422)
            bad = client.put("/api/invest/plan", json={"account": "Roth", "monthly": 500, "targets": [{"ticker": "VOO", "pct": 50}]})
            self.assertEqual(bad.status_code, 400)
            saved = client.put("/api/invest/plan", json={"account": "Roth", "monthly": 500, "targets": [{"ticker": "voo", "pct": 100}]})
            self.assertEqual(saved.json()["plan"]["targets"], [{"ticker": "VOO", "pct": 100.0}])
            overview = client.get("/api/invest/overview").json()
            self.assertEqual((overview["plan"]["account"], overview["sweep"]), ("Roth", None))
            self.assertEqual(client.put("/api/risk/stop", json={"ticker": "AAPL", "stop": 150}).json()["stop"], 150)
            self.assertEqual(client.post("/api/risk/check", json={"kind": "stock", "ticker": "AAPL"}).status_code, 422)
            checked = client.post("/api/risk/check", json={"kind": "stock", "ticker": "AAPL", "shares": 10, "price": 200})
            self.assertEqual(checked.json()["risk"], 500.0)
            self.assertIn("positions", client.get("/api/risk/heat").json())
            self.assertEqual(client.post("/api/invest/sweep", json={"from_account": "Roth", "to_account": "Roth", "amount": 5}).status_code, 400)
            self.assertEqual(client.delete("/api/invest/plan").json(), {"ok": True})


if __name__ == "__main__":
    unittest.main()
