import os
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get("STOCKPILOT_DB_PATH"):
    _database_dir = tempfile.TemporaryDirectory()
    os.environ["DATABASE_URL"] = ""
    os.environ["STOCKPILOT_DB_PATH"] = os.path.join(_database_dir.name, "test.db")

import database
import spreads
from pydantic import ValidationError
from portfolio_models import ClosedSpreadRequest, SpreadRequest

EXPIRY = "2099-01-15"


class SpreadMathTests(unittest.TestCase):
    def test_payoff_limits_for_each_spread_type(self):
        # (kind, long, short, net) -> (max profit, max loss, breakeven) for 2 contracts
        cases = {
            ("bull_call", 100, 105, 2.0): (600, 400, 102),
            ("bear_put", 105, 100, 2.0): (600, 400, 103),
            ("bull_put", 95, 100, 1.5): (300, 700, 98.5),
            ("bear_call", 105, 100, 1.5): (300, 700, 101.5),
        }
        for (kind, long_strike, short_strike, net), (profit, loss, breakeven) in cases.items():
            with self.subTest(kind=kind):
                result = spreads.metrics(kind, long_strike, short_strike, net, 2)
                self.assertEqual((result["max_profit"], result["max_loss"], result["breakeven"]), (profit, loss, breakeven))
                self.assertEqual(result["collateral"], 1000 if spreads.KINDS[kind]["style"] == "credit" else 0)
                self.assertEqual(spreads.kind_of(spreads.KINDS[kind]["type"], long_strike, short_strike), kind)

    def test_net_premium_is_debit_or_credit(self):
        self.assertEqual(spreads.net_premium("bull_call", 3.0, 1.0), 2.0)
        self.assertEqual(spreads.net_premium("bull_put", 1.0, 2.5), 1.5)

    def test_strikes_must_match_direction(self):
        with self.assertRaisesRegex(ValueError, "buys the lower strike"):
            spreads.validate_strikes("bull_put", 100, 95)
        with self.assertRaisesRegex(ValueError, "buys the higher strike"):
            spreads.validate_strikes("bear_call", 95, 100)
        with self.assertRaisesRegex(ValueError, "differ"):
            spreads.validate_strikes("bull_call", 100, 100)
        with self.assertRaises(ValidationError):
            SpreadRequest(ticker="SPY", kind="bull_call", expiry=EXPIRY, long_strike=105, long_premium=1,
                          short_strike=100, short_premium=2)

    def test_pairing_requires_one_long_and_one_short_of_equal_size(self):
        leg = dict(ticker="SPY", option_type="put", expiry=EXPIRY, account=None, spread_id="s1", contracts=1)
        whole = [dict(leg, id=1, position="long", strike=95), dict(leg, id=2, position="short", strike=100)]
        self.assertEqual(set(spreads.pair_open(whole)), {"s1"})
        self.assertEqual(spreads.pair_open(whole[:1]), {})
        self.assertEqual(spreads.pair_open([whole[0], dict(whole[1], contracts=2)]), {})


class SpreadLedgerTests(unittest.TestCase):
    def setUp(self):
        conn = database.get_db()
        for table in ("transactions", "closed_options", "options", "holdings"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, display_name) VALUES (1, 'test', 'unused', 'Test')")
        conn.commit()
        conn.close()

    def _client(self):
        import main
        from fastapi.testclient import TestClient
        return main, TestClient(main.app)

    def test_open_partial_close_and_merge_bull_put_spread(self):
        opened = database.add_user_spread(1, "spy", "bull_put", EXPIRY, 95, 1.0, 100, 2.5, 3, account="IRA")
        self.assertEqual((opened["kind"], opened["net_open"], opened["max_loss"]), ("bull_put", 1.5, 1050))
        legs = database.get_user_options(1)
        self.assertEqual({leg["spread_id"] for leg in legs}, {opened["spread_id"]})
        self.assertEqual({leg["account"] for leg in legs}, {"IRA"})

        first = database.close_user_spread(1, opened["spread_id"], 0.25, 0.75, 1)
        self.assertEqual(first["pnl"], 100.0)  # credit 1.50, paid 0.50 to close, one contract
        self.assertEqual({leg["contracts"] for leg in database.get_user_options(1)}, {2})
        database.close_user_spread(1, opened["spread_id"], 0.0, 0.0, 2)
        self.assertEqual(database.get_user_options(1), [])

        rows = database.get_closed_options(1)
        self.assertEqual(len(rows), 4)
        merged = spreads.merge_closed(rows)
        self.assertEqual(len(merged), 2)
        self.assertEqual(sorted(row["pnl"] for row in merged), [100.0, 300.0])
        whole = next(row for row in merged if row["contracts"] == 2)
        self.assertEqual((whole["position"], whole["open_premium"], whole["close_premium"]), ("short", 1.5, 0.0))
        self.assertEqual(whole["spread"]["label"], "Bull put")

        with self.assertRaises(LookupError):
            database.close_user_spread(1, opened["spread_id"], 0, 0, 1)

    def test_close_rejects_too_many_contracts_and_broken_spreads(self):
        opened = database.add_user_spread(1, "QQQ", "bull_call", EXPIRY, 400, 6.0, 410, 2.0, 1)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            database.close_user_spread(1, opened["spread_id"], 1, 1, 2)
        self.assertEqual(len(database.get_user_options(1)), 2, "failed close rolls back both legs")
        short = next(leg for leg in database.get_user_options(1) if leg["position"] == "short")
        database.close_user_option(1, "QQQ", "call", 410, EXPIRY, 1.0, 1, "short", option_id=short["id"])
        with self.assertRaisesRegex(LookupError, "already closed"):
            database.close_user_spread(1, opened["spread_id"], 1, 1, 1)
        self.assertEqual(database.delete_user_spread(1, opened["spread_id"])["deleted"], 1)

    def test_api_open_close_delete_and_summary(self):
        main, client = self._client()
        bad = dict(ticker="SPY", kind="bear_call", expiry=EXPIRY, long_strike=100, long_premium=1,
                   short_strike=105, short_premium=2, contracts=1)
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": 1}}):
            self.assertEqual(client.post("/api/portfolio/spreads", json=bad).status_code, 422)
            good = dict(bad, long_strike=105, short_strike=100)
            spread_id = client.post("/api/portfolio/spreads", json=good).json()["spread_id"]
            quote = {"bid": 0.9, "ask": 1.1, "last_price": 1, "iv": 0.3, "volume": 1, "open_interest": 10}
            with patch.object(main, "get_key_metrics", return_value={"price": 101}), \
                 patch.object(main.options_analytics, "_expirations", return_value=[EXPIRY]), \
                 patch.object(main.options_analytics, "_chain", return_value=(self._chain({100: 2.0, 105: 0.4}), self._chain({}))):
                summary = client.get("/api/portfolio/options/summary").json()
            [row] = summary["spreads"]
            self.assertEqual((row["label"], row["net_open"], row["net_mark"]), ("Bear call", 1.0, 1.6))
            self.assertEqual(row["pnl"], -60.0)
            self.assertEqual({o["spread_id"] for o in summary["options"]}, {spread_id})
            missing = client.post("/api/portfolio/spreads/nope/close", json={"long_premium": 0, "short_premium": 0, "contracts": 1})
            self.assertEqual(missing.status_code, 404)
            closed = client.post(f"/api/portfolio/spreads/{spread_id}/close", json={"long_premium": 0.1, "short_premium": 0.3, "contracts": 1})
            self.assertEqual(closed.json()["pnl"], 80.0)
            history = client.get("/api/portfolio/options/closed").json()
            self.assertEqual(len(history["trades"]), 1)
            self.assertEqual(history["total_realized_pnl"], 80.0)
            reopened = client.post("/api/portfolio/spreads", json=good).json()["spread_id"]
            self.assertEqual(client.delete(f"/api/portfolio/spreads/{reopened}").json()["deleted"], 2)

    @staticmethod
    def _chain(mids):
        import pandas as pd
        return pd.DataFrame([{"strike": strike, "bid": mid - 0.05, "ask": mid + 0.05, "lastPrice": mid,
                              "impliedVolatility": 0.3, "volume": 5, "openInterest": 50} for strike, mid in mids.items()],
                            columns=["strike", "bid", "ask", "lastPrice", "impliedVolatility", "volume", "openInterest"])

    def test_expire_settles_at_expiry_close(self):
        import pandas as pd
        main, client = self._client()
        past = "2026-01-16"
        with patch("database._option_values"):
            spread_id = database.add_user_spread(1, "SPY", "bull_put", past, 95, 1.0, 100, 2.5, 1)["spread_id"]
        closes = pd.DataFrame({"Close": [98.0, 120.0]}, index=pd.to_datetime([past, "2026-02-02"]))
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": 1}}), \
             patch.object(main, "get_stock_data", return_value=closes):
            result = client.post(f"/api/portfolio/spreads/{spread_id}/expire").json()
        self.assertEqual((result["settle_price"], result["pnl"]), (98.0, -50.0))  # short 100 put worth 2, credit 1.50
        closed = database.get_closed_options(1)
        self.assertEqual({str(row["closed_at"])[:10] for row in closed}, {past})

    def test_journal_spread_entry_is_idempotent_and_deletes_together(self):
        main, client = self._client()
        body = dict(ticker="nvda", kind="bear_call", expiry="2026-03-20", contracts=2, long_strike=150, short_strike=140,
                    long_open=1.0, short_open=3.0, long_close=0.2, short_close=0.7, opened_at="2026-03-01",
                    closed_at="2026-03-10", fees=2.6, notes="Faded the gap", idempotency_key="spread-entry-0001")
        ClosedSpreadRequest.model_validate(body)
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": 1}}):
            first = client.post("/api/portfolio/options/closed/spread", json=body)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["pnl"], 300.0)  # credit 2.00, closed for 0.50, 2 contracts
            retry = client.post("/api/portfolio/options/closed/spread", json=body).json()
            self.assertEqual(retry["spread_id"], first.json()["spread_id"])
            self.assertEqual(len(database.get_closed_options(1)), 2)
            conflict = client.post("/api/portfolio/options/closed/spread", json=dict(body, fees=3))
            self.assertEqual(conflict.status_code, 409)
            [trade] = client.get("/api/portfolio/options/closed").json()["trades"]
            self.assertEqual((trade["position"], trade["net_pnl"], trade["fees"], trade["notes"]), ("short", 297.4, 2.6, "Faded the gap"))
            self.assertTrue(trade["is_manual"])
            self.assertEqual(trade["ledger_event_id"], next(r["ledger_event_id"] for r in database.get_closed_options(1)
                                                          if r["position"] == "short"))
            self.assertEqual(client.delete(f"/api/portfolio/options/closed/spread/{trade['id']}").json(), {"ok": True})
            self.assertEqual(database.get_closed_options(1), [])

    def test_credit_spread_collateral_is_the_width(self):
        import accounts
        database.add_user_option(1, "AAPL", "put", 200, EXPIRY, 3.0, 1, "short")
        database.add_user_spread(1, "MSFT", "bull_put", EXPIRY, 390, 1.0, 400, 3.0, 2)
        database.add_user_spread(1, "TSLA", "bear_call", EXPIRY, 260, 1.0, 250, 3.0, 1)
        database.add_user_spread(1, "NVDA", "bear_put", EXPIRY, 500, 12.0, 490, 7.0, 1)
        account = accounts.list_accounts(1)["accounts"][0]
        self.assertEqual(account["put_collateral"], 20000 + 2000 + 1000, "a bear put's long put covers its short put")

    def test_deleting_one_partial_close_keeps_the_others(self):
        main, client = self._client()
        spread_id = database.add_user_spread(1, "SPY", "bull_put", EXPIRY, 95, 1.0, 100, 2.5, 2)["spread_id"]
        database.close_user_spread(1, spread_id, 0.2, 0.7, 1)
        database.close_user_spread(1, spread_id, 0.1, 0.4, 1)
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": 1}}):
            first, second = client.get("/api/portfolio/options/closed").json()["trades"]
            self.assertEqual(client.delete(f"/api/portfolio/options/closed/spread/{first['id']}").status_code, 200)
            [left] = client.get("/api/portfolio/options/closed").json()["trades"]
            self.assertEqual((left["id"], left["pnl"]), (second["id"], second["pnl"]))
            self.assertEqual(client.delete("/api/portfolio/options/closed/spread/999999").status_code, 404)

    def test_expiry_ladder_debit_spread_needs_no_assignment_cash(self):
        import expiry_ladder
        bear = database.add_user_spread(1, "NVDA", "bear_put", EXPIRY, 500, 12.0, 490, 7.0, 1)
        bull = database.add_user_spread(1, "MSFT", "bull_put", EXPIRY, 390, 1.0, 400, 3.0, 1)
        with patch.object(expiry_ladder, "_spot", side_effect=lambda ticker, cache: {"NVDA": 480.0, "MSFT": 380.0}[ticker]), \
             patch.object(expiry_ladder.accounts, "list_accounts", return_value={"accounts": []}):
            [group] = expiry_ladder.build(1, {"positions": []})["expiries"]
        rows = {row["id"]: row for row in group["positions"]}
        self.assertEqual(rows[bear["short"]["id"]]["cash_if_assigned"], 0)
        self.assertIn("pays its full", rows[bear["short"]["id"]]["spread_note"])
        self.assertEqual(rows[bull["short"]["id"]]["cash_if_assigned"], 1000, "both legs in the money: net is the width")
        self.assertEqual(group["cash_if_all_puts_assigned"], 1000)

    def test_spread_rules_use_net_value(self):
        import options_desk
        legs = [dict(id=1, ticker="TSLA", option_type="call", position="short", strike=250, expiry=EXPIRY, premium=3.0,
                     contracts=1, account=None, spread_id="s1", date_added="2026-01-01"),
                dict(id=2, ticker="TSLA", option_type="call", position="long", strike=260, expiry=EXPIRY, premium=1.0,
                     contracts=1, account=None, spread_id="s1", date_added="2026-01-01")]
        mids = {250: 8.5, 260: 2.5}
        contract = lambda t, kind, strike, expiry, S: {"mid": mids[strike], "bid": mids[strike] - 0.1, "ask": mids[strike] + 0.1,  # noqa: E731
                                                        "delta": 0.6 if strike == 250 else 0.3, "iv": 0.5}
        with patch.object(options_desk, "get_user_options", return_value=legs), \
             patch.object(options_desk, "get_user_holdings", return_value=[]), \
             patch.object(options_desk, "_roll_counts", return_value={}), \
             patch.object(options_desk.oa, "_spot", return_value=255.0), \
             patch.object(options_desk.oa, "earnings_info", return_value={"next": "2099-06-01"}), \
             patch.object(options_desk, "next_dividend", return_value=None), \
             patch.object(options_desk, "_contract", side_effect=contract):
            result = options_desk.position_actions(1)
        by_id = {row["id"]: row for row in result["positions"]}
        short_codes = [a["code"] for a in by_id[1]["actions"]]
        self.assertNotIn("naked", short_codes)
        self.assertIn("stop_loss", short_codes)  # net mark 6.00 vs 2.00 credit = 2x loss
        self.assertIn("tested", short_codes)
        self.assertEqual(by_id[1]["loss_multiple"], 2.0)
        self.assertEqual(by_id[1]["spread"]["role"], "main")
        self.assertFalse(any(a.get("repair") for a in by_id[1]["actions"]))
        self.assertEqual(by_id[2]["spread"]["role"], "hedge")

    def test_covered_call_ideas_ignore_spread_short_calls(self):
        import next_steps
        holdings = [{"ticker": "TSLA", "shares": 100, "buy_price": 200, "account": None}]
        options = [dict(id=1, ticker="TSLA", option_type="call", position="short", strike=250, expiry=EXPIRY, contracts=1,
                        account=None, spread_id="s1"),
                   dict(id=2, ticker="TSLA", option_type="call", position="long", strike=260, expiry=EXPIRY, contracts=1,
                        account=None, spread_id="s1")]
        self.assertEqual(len(next_steps._covered_call_items(holdings, options)), 1)
        self.assertEqual(next_steps._covered_call_items(holdings, [dict(options[0], spread_id=None)]), [])


if __name__ == "__main__":
    unittest.main()
