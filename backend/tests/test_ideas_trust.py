import os
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get("STOCKPILOT_DB_PATH"):
    _database_dir = tempfile.TemporaryDirectory()
    os.environ["DATABASE_URL"] = ""
    os.environ["STOCKPILOT_DB_PATH"] = os.path.join(_database_dir.name, "test.db")

import pandas as pd

import database
import paper

EXPIRY = "2099-01-15"


def chain(rows):
    """rows: {strike: (bid, ask)} -> option chain frame."""
    return pd.DataFrame([{"strike": k, "bid": b, "ask": a, "lastPrice": (a + b) / 2, "impliedVolatility": 0.3,
                          "volume": 1, "openInterest": 500} for k, (b, a) in rows.items()],
                        columns=["strike", "bid", "ask", "lastPrice", "impliedVolatility", "volume", "openInterest"])


class PaperTradeTests(unittest.TestCase):
    def setUp(self):
        conn = database.get_db()
        conn.execute("DELETE FROM paper_trades")
        conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, display_name) VALUES (1, 'test', 'unused', 'Test')")
        conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, display_name) VALUES (2, 'other', 'unused', 'Other')")
        conn.commit()
        conn.close()

    def quotes(self, puts):
        return patch("options_analytics._chain", return_value=(chain({}), chain(puts)))

    def test_bull_put_opens_at_realistic_fill_marks_and_closes(self):
        legs = [{"position": "short", "option_type": "put", "strike": 100, "expiry": EXPIRY},
                {"position": "long", "option_type": "put", "strike": 95, "expiry": EXPIRY}]
        with self.quotes({100: (2.4, 2.6), 95: (0.9, 1.1)}):
            trade = paper.open_trade(1, "spy", legs, 2, "income", "Balanced")
        # sell 100 put at (2.5+2.4)/2 = 2.45, buy 95 put at (1.0+1.1)/2 = 1.05 -> credit 1.40
        self.assertEqual((trade["entry"], trade["style"], trade["structure"], trade["strikes"]), (-1.4, "credit", "Bull put", "$95/$100"))
        self.assertEqual(trade["max_loss"], 720.0)
        with self.quotes({100: (1.4, 1.6), 95: (0.4, 0.6)}):
            listed = paper.list_trades(1)
            self.assertEqual(listed["trades"][0]["unrealized"], 80.0)  # mark -1.00 vs -1.40 entry, 2 spreads
            closed = paper.close_trade(1, trade["id"])
        # exit: buy back 100 at (1.5+1.6)/2 = 1.55, sell 95 at (0.5+0.4)/2 = 0.45 -> -1.10
        self.assertEqual((closed["exit_value"], closed["pnl"]), (-1.1, 60.0))
        with self.assertRaisesRegex(ValueError, "already closed"):
            paper.close_trade(1, trade["id"])
        stats = paper.list_trades(1)["stats"]
        self.assertEqual((stats["closed"], stats["wins"], stats["win_rate"], stats["realized"]), (1, 1, 100, 60.0))
        self.assertEqual(paper.list_trades(2)["trades"], [], "trades are private to their user")
        self.assertFalse(paper.delete_trade(2, trade["id"]))
        self.assertTrue(paper.delete_trade(1, trade["id"]))

    def test_rejects_unquoted_mixed_expiry_and_unsupported_legs(self):
        leg = {"position": "short", "option_type": "put", "strike": 100, "expiry": EXPIRY}
        with self.quotes({100: (0, 0.2)}), self.assertRaisesRegex(ValueError, "No usable quote"):
            paper.open_trade(1, "SPY", [leg], 1, None, None)
        with self.assertRaisesRegex(ValueError, "one expiry"):
            paper.open_trade(1, "SPY", [leg, {**leg, "position": "long", "strike": 95, "expiry": "2099-03-19"}], 1, None, None)
        with self.assertRaisesRegex(ValueError, "already passed"):
            paper.open_trade(1, "SPY", [{**leg, "expiry": "2020-01-17"}], 1, None, None)
        with self.assertRaises(ValueError):
            paper.open_trade(1, "SPY", [leg, {**leg, "strike": 95}], 1, None, None)

    def test_expired_trade_settles_at_expiry_close(self):
        leg = {"position": "short", "option_type": "put", "strike": 100, "expiry": EXPIRY}
        with self.quotes({100: (1.9, 2.1)}):
            trade = paper.open_trade(1, "SPY", [leg], 1, "wheel", None)
        self.assertEqual(trade["entry"], -1.95)
        with patch("options_analytics._live", return_value=False), patch.object(paper, "expiry_close", return_value=98.5), \
             patch.object(paper, "settle_ready", return_value=False), self.quotes({100: (0.0, 0.05)}):
            [still_open] = paper.list_trades(1)["trades"]
        self.assertEqual(still_open["status"], "open", "no settlement before the close is final")
        with patch("options_analytics._live", return_value=False), patch.object(paper, "expiry_close", return_value=98.5), \
             patch.object(paper, "settle_ready", return_value=True):
            [settled] = paper.list_trades(1)["trades"]
        self.assertEqual((settled["status"], settled["settle_price"], settled["pnl"]), ("expired", 98.5, 45.0))

    def test_api(self):
        import main
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        body = {"ticker": "SPY", "contracts": 1, "source": "directional", "label": "Bull call",
                "legs": [{"position": "long", "option_type": "call", "strike": 100, "expiry": EXPIRY},
                         {"position": "short", "option_type": "call", "strike": 110, "expiry": EXPIRY}]}
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": 1}}), \
             patch("options_analytics._chain", return_value=(chain({100: (5.8, 6.2), 110: (1.9, 2.1)}), chain({}))):
            created = client.post("/api/paper", json=body).json()
            self.assertEqual((created["entry"], created["style"], created["structure"]), (4.15, "debit", "Bull call"))
            self.assertEqual(client.post("/api/paper", json={**body, "legs": [{**body["legs"][0], "position": "sideways"}]}).status_code, 422)
            self.assertEqual(client.get("/api/paper").json()["trades"][0]["id"], created["id"])
            self.assertEqual(client.post(f"/api/paper/{created['id']}/close").status_code, 200)
            self.assertEqual(client.delete(f"/api/paper/{created['id']}").json(), {"ok": True})
            self.assertEqual(client.delete(f"/api/paper/{created['id']}").status_code, 404)


class SettleReadyTests(unittest.TestCase):
    def test_cutoff_is_4_15_pm_eastern_on_expiry_day(self):
        from datetime import datetime as real
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        cases = [(real(2026, 10, 16, 16, 5, tzinfo=et), False), (real(2026, 10, 16, 16, 15, tzinfo=et), True),
                 (real(2026, 10, 17, 9, 0, tzinfo=et), True), (real(2026, 10, 15, 20, 0, tzinfo=et), False)]
        for now, ready in cases:
            with self.subTest(now=now), patch.object(paper, "datetime") as clock:
                clock.now.return_value = now
                self.assertEqual(paper.settle_ready("2026-10-16"), ready)


class RealisticFillTests(unittest.TestCase):
    def test_vertical_scored_between_mid_and_natural(self):
        import options_analytics as oa
        short = {"strike": 100, "mid": 2.5, "bid": 2.4, "ask": 2.6, "oi": 500}
        quotes = {95.0: {"mid": 1.0, "bid": 0.9, "ask": 1.1, "oi": 500}}
        v = oa._vertical(short, quotes, "put", 200)
        self.assertEqual((v["mid_credit"], round(v["credit"], 2), round(v["natural"], 2)), (1.5, 1.4, 1.3))

    def test_low_credit_spreads_are_skipped_and_counted(self):
        import options_analytics as oa
        rows = [{"strike": 100, "mid": 0.45, "bid": 0.4, "ask": 0.5, "oi": 500, "delta": 0.16, "iv": 0.3, "p_itm": 0.15}]
        quotes = {95.0: {"mid": 0.05, "bid": 0.0, "ask": 0.1, "oi": 500}}
        skipped = {}
        # mid credit 0.40 (8% of the $5 width) -> at the realistic fill it is under the 10% minimum
        self.assertEqual(oa._put_credit_spreads(rows, quotes, 200, 0.1, None, skipped), [])
        self.assertEqual(skipped, {"put_credit_spreads": 1})

    def test_single_options_use_sell_fill(self):
        import options_analytics as oa
        rows = [{"strike": 95, "mid": 2.0, "bid": 1.8, "ask": 2.2, "oi": 900, "delta": 0.16, "iv": 0.3, "p_itm": 0.15}]
        [idea] = oa._ideas(rows, "put", 100, 30)
        self.assertEqual((idea["mid"], idea["fill"], idea["premium"], idea["effective_buy_price"]), (2.0, 1.9, 190.0, 93.1))


class AuditTests(unittest.TestCase):
    def test_calls_below_cost_rule_ignores_spread_legs(self):
        import trading_rules
        holdings = [{"ticker": "TSLA", "shares": 100, "buy_price": 300, "account": None}]
        legs = [dict(id=1, ticker="TSLA", option_type="call", position="short", strike=250, expiry=EXPIRY, premium=3,
                     contracts=1, account=None, spread_id="s", spread_ratio=1, spread_legs=2),
                dict(id=2, ticker="TSLA", option_type="call", position="long", strike=260, expiry=EXPIRY, premium=1,
                     contracts=1, account=None, spread_id="s", spread_ratio=1, spread_legs=2)]
        rules = {"no_calls_below_cost": True}
        self.assertEqual(trading_rules.violations(rules, holdings, legs, {}, {}, []), [])
        alone = [dict(legs[0], spread_id=None)]
        self.assertEqual([i["code"] for i in trading_rules.violations(rules, holdings, alone, {}, {}, [])], ["rule_call_below_cost"])

    def test_premium_income_counts_a_condor_once(self):
        import options_desk
        legs = [dict(id=i, ticker="SPY", option_type=t, position=p, strike=k, expiry=EXPIRY, premium=1.0, contracts=1,
                     spread_id="c", date_added="2026-10-02") for i, (t, p, k) in
                enumerate((("put", "long", 90), ("put", "short", 95), ("call", "short", 105), ("call", "long", 110)), 1)]
        with patch.object(options_desk, "get_user_options", return_value=legs), \
             patch.object(options_desk, "get_closed_options", return_value=[]), \
             patch("database.kv_get", return_value=None):
            months = options_desk.premium_income(1)["months"]
        october = next(m for m in months if m["month"] == "2026-10")
        self.assertEqual((october["trades"], october["collected"], october["paid"]), (1, 200.0, 200.0))


if __name__ == "__main__":
    unittest.main()
