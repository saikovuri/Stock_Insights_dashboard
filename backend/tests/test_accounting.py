import os
import tempfile
import unittest
from unittest.mock import patch

_database_dir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = ""
os.environ["STOCKPILOT_DB_PATH"] = os.path.join(_database_dir.name, "test.db")

import database
from pydantic import ValidationError
from portfolio_models import HoldingRequest, OptionRequest, ClosedOptionRequest


class AccountingTests(unittest.TestCase):
    def setUp(self):
        conn = database.get_db()
        for table in ("transactions", "closed_options", "closed_trades", "options", "holdings"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, display_name) VALUES (1, 'test', 'unused', 'Test')")
        conn.commit()
        conn.close()

    def test_assigned_calls_weekly_expiry_and_adjusted_cost(self):
        import options_analytics as analytics
        from contextlib import ExitStack
        expiries = {"2026-10-09": 4, "2026-10-12": 7, "2026-11-06": 32}
        quote = dict(strike=250, mid=4.05, bid=4, ask=4.1, delta=0.25, oi=500, p_itm=0.22)
        for shares in (100, 250):
            with self.subTest(shares=shares), ExitStack() as stack:
                cache = stack.enter_context(patch.object(analytics, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()))
                stack.enter_context(patch.object(analytics, "_spot", return_value=238.9))
                stack.enter_context(patch.object(analytics, "_expirations", return_value=list(expiries)))
                stack.enter_context(patch.object(analytics, "_earnings_date", return_value="2026-12-01"))
                stack.enter_context(patch.object(analytics, "_live", return_value=True))
                stack.enter_context(patch.object(analytics, "_dte", side_effect=expiries.get))
                stack.enter_context(patch.object(analytics, "_years", return_value=7 / 365))
                stack.enter_context(patch.object(analytics, "_is_monthly", return_value=False))
                stack.enter_context(patch.object(analytics, "_chain", return_value=([], [])))
                stack.enter_context(patch.object(analytics, "_otm_rows", return_value=[quote]))
                stack.enter_context(patch.object(analytics, "_pick", side_effect=lambda rows, target, used: quote if rows and 250 not in used else None))
                default = stack.enter_context(patch.object(analytics, "_default_income_expiry", return_value="2026-11-06"))
                weekly = analytics.assigned_calls("NVDA", 226.34, shares, "weekly")
                self.assertEqual([item["date"] for item in weekly["expirations"]], ["2026-10-09", "2026-10-12"])
                self.assertEqual(weekly["ideas"][0]["premium_adjusted_cost"], round(226.34 - 405 * (shares // 100) / shares, 2))
                self.assertEqual(weekly["cost_basis"], 226.34)
                self.assertTrue(cache.call_args.args[0].endswith(":weekly"))
                default.assert_not_called()
                standard = analytics.assigned_calls("NVDA", 226.34, shares)
                self.assertEqual(len(standard["expirations"]), 3)
                self.assertTrue(cache.call_args.args[0].endswith(":standard"))
                with patch.object(analytics, "_earnings_date", return_value="2026-10-10"):
                    result = analytics.assigned_calls("NVDA", 226.34, shares, "weekly")
                    self.assertFalse(result["expirations"][0]["earnings_before_expiry"])
                    self.assertTrue(result["expirations"][1]["earnings_before_expiry"])
                valid = [dict(quote, strike=250 + index) for index in range(6)]
                rejected = [dict(quote, oi=499), dict(quote, ask=5), dict(quote, ask=3.9),
                            dict(quote, delta=0.05), dict(quote, delta=0.5), dict(quote, strike=220),
                            dict(quote, mid=0.1, bid=0.1, ask=0.1)]
                def load_chain(ticker, expiry):
                    if expiry == "2026-11-06":
                        raise RuntimeError("Fixture quote failure")
                    return expiry, []
                with patch.object(analytics, "_chain", side_effect=load_chain), \
                     patch.object(analytics, "_otm_rows", side_effect=lambda calls, *args: rejected if calls == "2026-10-09" else valid + rejected):
                    result = analytics.assigned_calls("NVDA", 226.34, shares, "all")
                    self.assertEqual([item["date"] for item in result["expirations"]], ["2026-10-12"])
                    self.assertEqual([item["strike"] for item in result["ideas"]], list(range(250, 256)))
                    self.assertEqual(result["skipped_expirations"], 1)
                    self.assertEqual(result["unavailable_expirations"], ["2026-11-06"])
                with patch.object(analytics, "_otm_rows", return_value=[]), patch.object(analytics, "_chain", return_value=([], [])) as chain:
                    self.assertEqual(analytics.assigned_calls("NVDA", 300, shares, "weekly")["ideas"], [])
                    self.assertEqual(chain.call_count, 2)
                with patch.object(analytics, "_expirations", return_value=["2026-11-06"]):
                    with self.assertRaisesRegex(LookupError, "1-7 days"):
                        analytics.assigned_calls("NVDA", 226.34, shares, "weekly")

    def test_option_expirations_match_roll_live_dates(self):
        import main
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        dates = {"2026-10-05": 0, "2026-10-09": 4, "2026-10-02": -3}
        with patch.object(main.options_analytics, "_expirations", return_value=list(dates)), \
             patch.object(main.options_analytics, "_live", side_effect=lambda expiry: dates[expiry] >= 0), \
             patch.object(main.options_analytics, "_dte", side_effect=dates.get):
            response = client.get("/api/stock/NVDA/option-expirations")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["expirations"], [
                {"date": "2026-10-05", "dte": 0}, {"date": "2026-10-09", "dte": 4}])
            with patch.object(main.options_analytics, "_live", side_effect=lambda expiry: dates[expiry] > 0):
                self.assertEqual(client.get("/api/stock/NVDA/option-expirations").json()["expirations"], [
                    {"date": "2026-10-09", "dte": 4}])

    def test_covered_calls_value_yield_leaps_and_upside_cap(self):
        import options_analytics as analytics
        expiries = {"2026-10-09": 2, "2027-06-17": 253, "2029-01-19": 834}
        short = dict(strike=700, mid=40, bid=38, ask=43, delta=0.25, oi=150, p_itm=0.22)
        cap = dict(strike=770, mid=25, bid=24, ask=26, delta=0.18, oi=120, p_itm=0.15)
        with patch.object(analytics, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()) as cache, \
             patch.object(analytics, "_spot", return_value=640.0), \
             patch.object(analytics, "_expirations", return_value=list(expiries)), \
             patch.object(analytics, "_earnings_date", return_value=None), \
             patch.object(analytics, "_live", return_value=True), \
             patch.object(analytics, "_dte", side_effect=expiries.get), \
             patch.object(analytics, "_years", return_value=0.7), \
             patch.object(analytics, "_is_monthly", return_value=True), \
             patch.object(analytics, "_chain", return_value=([], [])), \
             patch.object(analytics, "_otm_rows", return_value=[short, cap]):
            result = analytics.assigned_calls("AMD", 60, 100, "leaps")
            self.assertTrue(cache.call_args.args[0].endswith(":leaps"))
            self.assertEqual([e["date"] for e in result["expirations"]], ["2027-06-17"], "180-800 days only")
            self.assertIn("open interest >= 100", result["note"])
            idea = result["ideas"][0]
            self.assertEqual((idea["yield_pct"], idea["if_called_from_today_pct"], idea["gain_realized_if_called"]),
                             (6.25, round(100 / 640 * 100, 2), 64000), "yield and gain use today's price; realized gain uses cost")
            self.assertEqual(idea["upside_cap"], {"strike": 770, "mid": 25, "net_credit": 15, "total_net": 1500})
            self.assertIsNone(result["ideas"][1]["upside_cap"], "nothing 10% above the top strike")
            with self.assertRaises(LookupError):
                with patch.object(analytics, "_expirations", return_value=["2026-10-09"]):
                    analytics.assigned_calls("AMD", 60, 100, "leaps")

    def test_assigned_calls_api_cadence_validation(self):
        import main
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        with patch.object(main.options_analytics, "assigned_calls", return_value={}) as calculate:
            self.assertEqual(client.get("/api/stock/NVDA/assigned-calls?cost_basis=226.34&cadence=weekly").status_code, 200)
            calculate.assert_called_once_with("NVDA", 226.34, 100, "weekly")
            self.assertEqual(client.get("/api/stock/NVDA/assigned-calls?cost_basis=226.34").status_code, 200)
            calculate.assert_called_with("NVDA", 226.34, 100, "all")
            calculate.reset_mock()
            self.assertEqual(client.get("/api/stock/NVDA/assigned-calls?cost_basis=226.34&cadence=invalid").status_code, 422)
            calculate.assert_not_called()
            calculate.side_effect = LookupError("No listed expirations within 1-7 days")
            missing = client.get("/api/stock/NVDA/assigned-calls?cost_basis=226.34&cadence=weekly")
            self.assertEqual(missing.status_code, 404)
            self.assertIn("1-7 days", missing.json()["detail"])

    def test_wheel_starts_missing_expanded_scan(self):
        import wheel
        with patch.object(wheel, "kv_get", return_value=None), \
             patch.object(wheel, "get_scan") as start, \
             patch.object(wheel, "_spots") as spots:
            self.assertEqual(wheel.run_wheel_scan(), {"status": "building", "rows": []})
            start.assert_called_once_with()
            spots.assert_not_called()

    def test_scan_universe_combines_indexes_without_duplicates(self):
        import scanner
        apple = dict(symbol="AAPL", name="Apple", sector="Information Technology")
        nasdaq_only = dict(symbol="TEST", name="Nasdaq-only fixture", sector="Information Technology")
        with patch.object(scanner, "_index_universe", side_effect=[[apple], [apple, nasdaq_only]]) as load:
            self.assertEqual(scanner.universe(), [apple, nasdaq_only])
        self.assertEqual(load.call_args_list[0].args[0], scanner.UNIVERSE_KEY)
        self.assertEqual(load.call_args_list[1].args[0], scanner.NASDAQ_UNIVERSE_KEY)

    def test_scan_universe_parses_nasdaq_constituents_and_caches(self):
        import scanner
        html = '<table><tr><th>Other</th></tr><tr><td>Ignored</td></tr></table>' + \
            '<table><tr><th>Company</th><th>Ticker</th><th>ICB Industry[1]</th></tr>' + \
            '<tr><td>Example</td><td>TEST.A</td><td>Technology</td></tr></table>'
        with patch.object(scanner, "kv_get", return_value=None), \
             patch.object(scanner.requests, "get") as fetch, \
             patch.object(scanner, "kv_set") as cache, \
             patch("research_universe.save_snapshot") as snapshot:
            fetch.return_value.text = html
            rows = scanner._index_universe(scanner.NASDAQ_UNIVERSE_KEY, "https://example.test", "Ticker", "Company", "nasdaq-fixture", [])
            self.assertEqual(rows, [dict(symbol="TEST-A", name="Example", sector="Information Technology")])
            cache.assert_called_once_with(scanner.NASDAQ_UNIVERSE_KEY, rows)
            self.assertEqual(snapshot.call_args.args[0]["source"], "nasdaq-fixture")

    def test_scan_universe_keeps_cached_index_when_fetch_fails(self):
        import scanner
        cached = [dict(symbol="TEST", name="Example", sector="Information Technology")]
        with patch.object(scanner, "kv_get", return_value={"updated_at": "2020-01-01", "data": cached}), \
             patch.object(scanner.requests, "get", side_effect=RuntimeError("offline")):
            self.assertEqual(scanner._index_universe("test", "https://example.test", "Ticker", "Company", "test", []), cached)

    def test_short_put_through_earnings_offers_roll_ins_before_the_report(self):
        import pandas as pd
        import options_analytics as oa
        from datetime import datetime, timedelta
        today = datetime.now(oa._ET).date()
        day = lambda n: (today + timedelta(days=n)).isoformat()
        quotes = {day(8): {375: (9.8, 10.2), 370: (7.3, 7.7), 365: (5.3, 5.7), 360: (3.5, 3.9)},
                  day(15): {375: (14.4, 14.7), 370: (11.6, 11.9)}}
        chain = lambda ticker, e: (pd.DataFrame(), pd.DataFrame(
            [{"strike": k, "bid": b, "ask": a, "openInterest": 500, "impliedVolatility": 0.5} for k, (b, a) in quotes[e].items()]))
        with patch.object(oa, "get_or_fetch", side_effect=lambda key, fetch, ttl=0: fetch()), \
             patch.object(oa, "_spot", return_value=375.0), patch.object(oa, "_expirations", return_value=list(quotes)), \
             patch.object(oa, "_chain", side_effect=chain), patch.object(oa, "_earnings_date", return_value=day(13)):
            result = oa.roll_ideas("TSLA", "csp", day(15), 375, credit=13.65)
        roll_ins = {r["short_strike"]: r for r in result["rolls"] if r["type"].startswith("in")}
        self.assertEqual(set(roll_ins), {375, 360})
        self.assertEqual(roll_ins[375]["type"], "in")
        self.assertEqual(roll_ins[375]["net_credit"], -455.0)  # $10.00 new - $14.55 to close
        self.assertEqual(roll_ins[360]["type"], "in_improve")
        self.assertTrue(all(r["expiry"] == day(8) and not r["spans_earnings"] and not r["best"] for r in roll_ins.values()))
        self.assertIn("If assigned: buy at $375 − $9.10 total premium", roll_ins[375]["outcome"])
        self.assertIn("Roll in before earnings", [a["title"] for a in result["alternatives"]])

    def test_oversold_reversal_candle_then_reclaim_of_21ema_and_50sma(self):
        import pandas as pd
        import scanner
        n = 30
        df = pd.DataFrame({"Open": [91.0] * n, "High": [91.5] * n, "Low": [89.5] * n, "Close": [90.0] * n,
                           "Volume": [1e6] * n, "rsi": [50.0] * n, "ema_21": [95.0] * n, "sma_50": [96.0] * n,
                           "sma_200": [100.0] * n, "bb_upper": [100.0] * n, "bb_lower": [80.0] * n, "bb_mid": [90.0] * n})
        df.loc[18:19, "rsi"] = 30.0
        df.loc[20, ["Open", "High", "Low", "Close", "rsi"]] = [90.0, 90.5, 85.0, 90.2, 33.0]  # hammer
        df.loc[24, ["Open", "High", "Close"]] = [91.0, 97.5, 97.0]  # first close above both averages
        df.loc[25:, ["Open", "High", "Close"]] = [96.5, 98.0, 97.5]
        signals = scanner._signals(df)
        self.assertEqual(list(signals.index[signals["reversal"]]), [20])
        self.assertEqual(list(signals.index[signals["reclaim"]]), [24, 25, 26])  # stays listed for 3 days
        self.assertFalse(signals["oversold"].any())  # below the 200-day, so the existing setup stays quiet
        engulf = pd.DataFrame({"Open": [10.0, 9.0], "High": [10.2, 10.6], "Low": [8.8, 8.9], "Close": [9.2, 10.4]})
        self.assertEqual(list(scanner._reversal_candles(engulf)), [False, True])

    def test_accounting_queries_use_database_placeholders(self):
        import accounting
        for placeholder in ("?", "%s"):
            with self.subTest(placeholder=placeholder), \
                 patch.object(database, "PH", placeholder), \
                 patch.object(database, "_run", return_value=[]) as run:
                self.assertEqual(accounting.list_events(7, after_id=123, limit=50), [])
                run.assert_called_once_with(
                    f"SELECT * FROM accounting_events WHERE user_id={placeholder} AND id>{placeholder} ORDER BY id LIMIT {placeholder}",
                    (7, 123, 50), fetch="all",
                )
                run.reset_mock()
                accounting.report(7)
                run.assert_called_once_with(
                    f"SELECT * FROM accounting_events WHERE user_id={placeholder} ORDER BY id",
                    (7,), fetch="all",
                )

    def option(self, contracts=1, option_type="put", position="short"):
        return database.add_user_option(1, "AAPL", option_type, 100, "2027-01-15", 2, contracts, position)

    def test_assignment_targets_selected_lot(self):
        first = self.option()
        selected = self.option(2)
        result = database.assign_user_option(1, selected["id"])
        self.assertEqual(result["shares"], 200)
        self.assertEqual([row["id"] for row in database.get_user_options(1)], [first["id"]])
        self.assertEqual(database.get_user_holdings(1)[0]["shares"], 200)

    def test_assignment_rolls_back_share_failure(self):
        selected = self.option()
        with patch.object(database, "add_user_holding", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                database.assign_user_option(1, selected["id"])
        self.assertEqual(len(database.get_user_options(1)), 1)
        self.assertEqual(database.get_closed_options(1), [])

    def test_negative_lot_sale_rejected(self):
        holding = database.add_user_holding(1, "AAPL", 10, 100)
        with self.assertRaises(ValueError):
            database.sell_user_holding_by_lot(1, holding["id"], -5, 110)
        self.assertEqual(database.get_user_holdings(1)[0]["shares"], 10)

    def test_call_assignment_uses_multiple_lots(self):
        database.add_user_holding(1, "AAPL", 40, 90)
        database.add_user_holding(1, "AAPL", 60, 95)
        selected = self.option(option_type="call")
        self.assertEqual(database.assign_user_option(1, selected["id"])["pnl"], 700)
        self.assertEqual(database.get_user_holdings(1), [])

    def test_assignment_checks_owner_and_is_not_repeatable(self):
        selected = self.option()
        with self.assertRaises(LookupError):
            database.assign_user_option(2, selected["id"])
        database.assign_user_option(1, selected["id"])
        with self.assertRaises(LookupError):
            database.assign_user_option(1, selected["id"])

    def test_partial_close_selected_lot(self):
        selected = self.option(2)
        result = database.close_user_option(1, "AAPL", "put", 100, "2027-01-15", 1, 1, "short", option_id=selected["id"])
        self.assertEqual(result["pnl"], 100)
        self.assertEqual(database.get_user_options(1)[0]["contracts"], 1)

    def test_close_rolls_back_transaction_log_failure(self):
        selected = self.option()
        with patch.object(database.json, "dumps", side_effect=RuntimeError("log failed")):
            with self.assertRaises(RuntimeError):
                database.close_user_option(1, "AAPL", "put", 100, "2027-01-15", 1, 1, "short", option_id=selected["id"])
        self.assertEqual(len(database.get_user_options(1)), 1)
        self.assertEqual(database.get_closed_options(1), [])

    def test_unavailable_stock_quotes_do_not_report_total_loss(self):
        import main
        import pandas as pd
        holding = database.add_user_holding(1, "AAPL", 10, 100)
        with patch.object(main, "get_user_holdings", return_value=[holding]), \
             patch.object(main, "finnhub_enabled", return_value=False), \
             patch("yfinance.download", return_value=pd.DataFrame()), \
             patch.object(main, "get_key_metrics", side_effect=RuntimeError("quote unavailable")):
            result = main.portfolio_summary_endpoint({"user_id": 1})
        self.assertIsNone(result["total_pnl"])
        self.assertIsNone(result["holdings"][0]["current_price"])
        self.assertTrue(result["incomplete"])

    def test_sale_spans_lots_without_silent_capping(self):
        database.add_user_holding(1, "AAPL", 4, 90)
        database.add_user_holding(1, "AAPL", 6, 95)
        result = database.sell_user_holding(1, "AAPL", 8, 100)
        self.assertEqual(result["shares"], 8)
        self.assertEqual(result["pnl"], 60)
        with self.assertRaises(ValueError):
            database.sell_user_holding(1, "AAPL", 3, 100)
        with self.assertRaises(ValueError):
            database.sell_user_holding(1, "AAPL", -5, 100)

    def test_request_validation(self):
        for shares in (-1, 0, float("nan"), float("inf")):
            with self.subTest(shares=shares), self.assertRaises(ValidationError):
                HoldingRequest(ticker="AAPL", shares=shares, price=100)
        values = dict(ticker="AAPL", option_type="put", strike=100, expiry="2027-01-15", premium=0)
        for invalid in ({"contracts": -3}, {"contracts": 1.5}, {"option_type": "banana"},
                        {"expiry": "not-a-date"}, {"position": "wrong"}, {"premium": float("nan")}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                OptionRequest(**(values | invalid))
        self.assertEqual(OptionRequest(**values).premium, 0)

    def test_historical_option_validation(self):
        values = dict(ticker="wdc", option_type="put", position="short", strike="65", expiry="2025-09-19",
                      contracts=1, open_premium="1.20", close_premium="0.35", opened_at="2025-09-01",
                      closed_at="2025-09-10", fees="1.30", notes="Closed early", idempotency_key="history-validation")
        self.assertEqual(ClosedOptionRequest(**values).ticker, "WDC")
        self.assertEqual(ClosedOptionRequest(**(values | {"close_premium": "0"})).close_premium, 0)
        for invalid in ({"contracts": 1.5}, {"contracts": 0}, {"open_premium": "0"},
                        {"close_premium": "-1"}, {"fees": "-1"}, {"fees": "1.001"},
                        {"strike": "NaN"}, {"open_premium": "Infinity"}, {"opened_at": "2025-09-11"},
                        {"closed_at": "2025-09-20"}, {"opened_at": "2999-01-01", "closed_at": "2999-01-02", "expiry": "2999-02-01"},
                        {"option_type": "shares"}, {"pnl": 85}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                ClosedOptionRequest(**(values | invalid))

    def historical_option(self, **changes):
        from uuid import uuid4
        return dict(ticker="WDC", option_type="put", position="short", strike="65", expiry="2025-09-19",
                    contracts=1, open_premium="1.20", close_premium="0.35", opened_at="2025-09-01",
                    closed_at="2025-09-10", fees="1.30", notes="Closed early", idempotency_key=uuid4().hex) | changes

    def test_historical_option_records_once_with_fees_and_dates(self):
        import accounting
        values = self.historical_option()
        first = database.record_closed_option(1, values)
        repeated = database.record_closed_option(1, values)
        self.assertEqual(first["id"], repeated["id"])
        self.assertEqual(database.get_user_options(1), [])
        self.assertEqual(database.get_user_holdings(1), [])
        rows = database.get_closed_options(1)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["pnl"], rows[0]["fees"], rows[0]["net_pnl"]), (85, 1.3, 83.7))
        self.assertEqual((rows[0]["opened_at"], rows[0]["closed_at"], rows[0]["notes"]),
                         ("2025-09-01", "2025-09-10", "Closed early"))
        lot = next(lot for lot in accounting.report(1)["tax_lots"] if lot["source_id"] == first["id"] and lot["source"] == "closed_options")
        self.assertEqual(lot["gain"], 83.7)
        self.assertEqual(database.get_closed_options(2), [])
        with self.assertRaises(ValueError):
            database.record_closed_option(1, values | {"contracts": 2})

    def test_historical_option_long_and_zero_close(self):
        for position, close, expected in (("long", "2.05", 170), ("short", "0", 240), ("long", "0", -240)):
            with self.subTest(position=position, close=close):
                result = database.record_closed_option(1, self.historical_option(position=position, close_premium=close, contracts=2, fees="0"))
                self.assertEqual(result["pnl"], expected)

    def test_historical_option_fee_failure_rolls_back_everything(self):
        import accounting
        original = database.json.dumps
        before = accounting.list_events(1, limit=1000)
        def fail_fee(value, *args, **kwargs):
            if isinstance(value, dict) and value.get("kind") == "fee":
                raise RuntimeError("fee write failed")
            return original(value, *args, **kwargs)
        with patch.object(database.json, "dumps", side_effect=fail_fee), self.assertRaises(RuntimeError):
            database.record_closed_option(1, self.historical_option())
        self.assertEqual(database.get_closed_options(1), [])
        self.assertEqual(accounting.list_events(1, limit=1000), before)

    def test_historical_option_review_uses_fees_and_tracks_reversals(self):
        import accounting
        import options_desk
        from datetime import datetime, timezone
        from uuid import uuid4
        database.record_closed_option(1, self.historical_option(fees="100"))
        self.assertEqual(options_desk.options_review(1)["stats"]["total_pnl"], -15)
        self.assertEqual(options_desk.options_review(1)["stats"]["win_rate"], 0)
        event_ids = {lot["event_id"] for lot in accounting.report(1)["tax_lots"]}
        fee = next(entry for entry in accounting.report(1)["manual_entries"] if entry["kind"] == "fee" and entry["event_id"] in event_ids)
        accounting.record_entry(1, {"kind": "reverse", "event_id": fee["id"], "occurred_at": datetime.now(timezone.utc),
                                    "idempotency_key": uuid4().hex})
        self.assertEqual(database.get_closed_options(1)[0]["net_pnl"], 85)
        self.assertEqual(options_desk.options_review(1)["stats"]["win_rate"], 100)

    def test_historical_option_edit_and_delete_reconcile_fees(self):
        import accounting
        first = database.record_closed_option(1, self.historical_option())
        changes = self.historical_option(close_premium="0.25", fees="2.50", notes="Corrected fill", closed_at="2025-09-11")
        edited = database.record_closed_option(1, changes, trade_id=first["id"])
        events = accounting.list_events(1, limit=1000)
        again = database.record_closed_option(1, changes, trade_id=first["id"])
        self.assertEqual((edited["id"], again["id"]), (first["id"], first["id"]))
        self.assertEqual(accounting.list_events(1, limit=1000), events)
        rows = database.get_closed_options(1)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_manual"])
        self.assertEqual((rows[0]["pnl"], rows[0]["fees"], rows[0]["net_pnl"]), (95, 2.5, 92.5))
        self.assertEqual(rows[0]["notes"], "Corrected fill")
        before_fees = accounting.report(1)["fees"]
        self.assertTrue(database.delete_closed_option(1, first["id"]))
        self.assertFalse(database.delete_closed_option(1, first["id"]))
        self.assertEqual(database.get_closed_options(1), [])
        self.assertAlmostEqual(accounting.report(1)["fees"], before_fees - 2.5)
        operations = [event["operation"] for event in accounting.list_events(1, limit=1000)
                      if event["source"] == "closed_options" and event["source_id"] == first["id"]]
        self.assertEqual(operations, ["INSERT", "UPDATE", "DELETE"])

    def test_historical_option_corrections_check_owner_and_origin(self):
        first = database.record_closed_option(1, self.historical_option())
        with self.assertRaises(LookupError):
            database.record_closed_option(2, self.historical_option(), trade_id=first["id"])
        self.assertFalse(database.delete_closed_option(2, first["id"]))
        live = self.option()
        database.close_user_option(1, "AAPL", "put", 100, "2027-01-15", 1, 1, "short", option_id=live["id"])
        actual_close = next(row for row in database.get_closed_options(1) if row["ticker"] == "AAPL")
        self.assertFalse(actual_close["is_manual"])
        with self.assertRaises(LookupError):
            database.record_closed_option(1, self.historical_option(), trade_id=actual_close["id"])

    def test_historical_option_correction_failure_rolls_back_fees_and_trade(self):
        import accounting
        first = database.record_closed_option(1, self.historical_option())
        before = accounting.list_events(1, limit=1000)
        original = database.json.dumps
        def fail_fee(value, *args, **kwargs):
            if isinstance(value, dict) and value.get("kind") == "fee":
                raise RuntimeError("replacement fee failed")
            return original(value, *args, **kwargs)
        with patch.object(database.json, "dumps", side_effect=fail_fee), self.assertRaises(RuntimeError):
            database.record_closed_option(1, self.historical_option(fees="3"), trade_id=first["id"])
        self.assertEqual(accounting.list_events(1, limit=1000), before)
        self.assertEqual(database.get_closed_options(1)[0]["fees"], 1.3)

    def test_historical_option_correction_api_and_zero_fees(self):
        import main
        from fastapi.testclient import TestClient
        first = database.record_closed_option(1, self.historical_option())
        client = TestClient(main.app)
        path = f"/api/portfolio/options/closed/{first['id']}"
        changes = self.historical_option(close_premium="0.25", fees="0", notes="Corrected")
        self.assertEqual(client.put(path, json=changes).status_code, 401)
        self.assertEqual(client.delete(path).status_code, 401)
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": 2}}):
            self.assertEqual(client.put(path, json=changes).status_code, 404)
            self.assertEqual(client.delete(path).status_code, 404)
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": 1}}):
            self.assertEqual(client.put(path, json=changes | {"closed_at": "2024-01-01"}).status_code, 422)
            result = client.put(path, json=changes)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["id"], first["id"])
            self.assertEqual(client.put(path, json=changes).status_code, 200)
            self.assertEqual(client.put(path, json=changes | {"fees": "3"}).status_code, 409)
            row = client.get("/api/portfolio/options/closed").json()["trades"][0]
            self.assertEqual((row["fees"], row["net_pnl"]), (0, 95))
            self.assertEqual(client.delete(path).status_code, 200)
            self.assertEqual(client.get("/api/portfolio/options/closed").json()["trades"], [])

    def test_historical_option_corrections_preserve_cycle_allocations(self):
        import accounting
        from datetime import datetime, timezone
        from uuid import uuid4
        first = database.record_closed_option(1, self.historical_option(contracts=2))
        event_id = next(row["event_id"] for row in accounting.report(1)["tax_lots"] if row["source"] == "closed_options" and row["source_id"] == first["id"])
        cycle = uuid4().hex
        accounting.record_entry(1, {"kind": "link", "event_id": event_id, "quantity": "2", "cycle": cycle,
                                    "occurred_at": datetime.now(timezone.utc), "idempotency_key": uuid4().hex})
        with self.assertRaisesRegex(ValueError, "cycle allocations"):
            database.record_closed_option(1, self.historical_option(contracts=1), trade_id=first["id"])
        self.assertEqual(database.get_closed_options(1)[0]["contracts"], 2)
        database.delete_closed_option(1, first["id"])
        self.assertNotIn(cycle, [entry["name"] for entry in accounting.report(1)["cycles"]])

    def test_historical_option_coach_cache_tracks_fee_changes(self):
        import main
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        records = [{"id": 1, "pnl": 85, "fees": 0, "net_pnl": 85}]
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": 1}}), \
             patch.object(main, "get_closed_options", return_value=records), \
             patch.object(main, "get_or_fetch", side_effect=lambda key, factory, ttl: {"cache_key": key}):
            first = client.get("/api/portfolio/options/coach")
            records[0].update(fees=1.3, net_pnl=83.7)
            second = client.get("/api/portfolio/options/coach")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertNotEqual(first.json()["cache_key"], second.json()["cache_key"])

    def test_historical_option_api_requires_owner_and_rejects_reused_payload(self):
        import main
        from fastapi.testclient import TestClient
        from uuid import uuid4
        client = TestClient(main.app)
        values = self.historical_option()
        self.assertEqual(client.post("/api/portfolio/options/closed", json=values).status_code, 401)
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": 1}}):
            first = client.post("/api/portfolio/options/closed", json=values)
            self.assertEqual(first.status_code, 200, first.text)
            again = client.post("/api/portfolio/options/closed", json=values)
            self.assertEqual(again.json()["id"], first.json()["id"])
            self.assertEqual(client.post("/api/portfolio/options/closed", json=values | {"fees": "2"}).status_code, 409)
            self.assertEqual(client.post("/api/portfolio/options/closed", json=values | {"user_id": 2}).status_code, 422)
        other = database.create_user(uuid4().hex, "unused", "Other")
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": other["id"]}}):
            self.assertEqual(client.get("/api/portfolio/options/closed").json()["trades"], [])
            result = client.post("/api/portfolio/options/closed", json=values)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertNotEqual(result.json()["id"], first.json()["id"])

    def test_audit_survives_edit_and_delete_without_cross_user_access(self):
        import accounting
        holding = database.add_user_holding(1, "AAPL", 10, 100)
        database.update_user_holding(1, holding["id"], "AAPL", 12, 101)
        database.delete_user_holding(1, holding["id"])
        events = [event for event in accounting.list_events(1, limit=1000)
                  if event["source"] == "holdings" and event["source_id"] == holding["id"]]
        self.assertEqual([event["operation"] for event in events], ["INSERT", "UPDATE", "DELETE"])
        self.assertEqual(events[1]["before"]["shares"], 10)
        self.assertEqual(events[1]["after"]["shares"], 12)
        self.assertEqual(accounting.list_events(2), [])
        conn = database.get_db()
        try:
            for statement in ("DELETE FROM accounting_events", "UPDATE accounting_events SET operation='EDIT'"):
                with self.assertRaises(Exception):
                    conn.execute(statement)
                conn.rollback()
        finally:
            conn.close()

    def test_audit_rolls_back_with_assignment_and_migration_is_idempotent(self):
        import accounting
        selected = self.option()
        before = accounting.list_events(1, limit=1000)
        with patch.object(database, "add_user_holding", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                database.assign_user_option(1, selected["id"])
        self.assertEqual(accounting.list_events(1, limit=1000), before)
        database.init_db()
        self.assertEqual(accounting.list_events(1, limit=1000), before)


class ManualAccountingTests(unittest.TestCase):
    def setUp(self):
        import uuid
        import accounting
        self.accounting = accounting
        self.user = database.create_user(uuid.uuid4().hex, "unused", "Accounting")["id"]

    def entry(self, kind, **values):
        import uuid
        return self.accounting.record_entry(self.user, {"kind": kind, "occurred_at": "2026-01-01T00:00:00Z",
                                                        "idempotency_key": uuid.uuid4().hex, **values})

    def test_partial_sale_allocates_opening_fees_and_keeps_acquisition_date(self):
        lot = database.add_user_holding(self.user, "AAPL", 10, 100, acquired="2023-01-01")
        opening = next(event for event in self.accounting.list_events(self.user) if event["source"] == "holdings")
        self.entry("fee", amount=10, event_id=opening["id"])
        database.sell_user_holding_by_lot(self.user, lot["id"], 4, 110)
        closing = next(event for event in self.accounting.list_events(self.user) if event["source"] == "closed_trades")
        self.entry("fee", amount=2, event_id=closing["id"])
        report = self.accounting.report(self.user)
        trade = report["tax_lots"][0]
        self.assertEqual((trade["basis"], trade["proceeds"], trade["gain"], trade["fees"]), (404, 438, 34, 6))
        self.assertEqual(trade["acquired_at"], "2023-01-01")
        self.assertEqual(trade["term"], "long")

    def test_reversal_is_append_only_and_cannot_be_repeated(self):
        entry = self.entry("fee", amount=3)
        self.entry("reverse", event_id=entry["id"])
        self.assertEqual(self.accounting.report(self.user)["fees"], 0)
        self.assertEqual(len(self.accounting.list_events(self.user)), 2)
        with self.assertRaises(ValueError):
            self.entry("reverse", event_id=entry["id"])

    def test_idempotency_and_reference_ownership(self):
        request = {"kind": "deposit", "amount": 100, "occurred_at": "2026-01-01T00:00:00Z", "idempotency_key": "request-one"}
        first = self.accounting.record_entry(self.user, request)
        self.assertEqual(self.accounting.record_entry(self.user, request), first)
        with self.assertRaises(ValueError):
            self.accounting.record_entry(self.user, {**request, "amount": 200})
        with self.assertRaises(ValueError):
            self.accounting.record_entry(1, {**request, "kind": "reverse", "amount": 0, "event_id": first["id"]})

    def test_cycle_allocations_cannot_reuse_contracts(self):
        database.add_user_option(self.user, "AAPL", "put", 100, "2027-01-15", 2, 2, "short")
        opening = next(event for event in self.accounting.list_events(self.user) if event["source"] == "options")
        link = self.entry("link", event_id=opening["id"], cycle="Wheel 1", quantity=2)
        with self.assertRaises(ValueError):
            self.entry("link", event_id=opening["id"], cycle="Wheel 2", quantity=1)
        self.entry("reverse", event_id=link["id"])
        self.entry("link", event_id=opening["id"], cycle="Wheel 2", quantity=2)
        self.assertEqual(self.accounting.report(self.user)["cycles"][0]["name"], "Wheel 2")

    def closed_option(self, option_type="put", position="short"):
        option = database.add_user_option(self.user, "AAPL", option_type, 100, "2027-01-15", 2, 2, position)
        database.close_user_option(self.user, "AAPL", option_type, 100, "2027-01-15", 0.5, 2, position,
                                   option_id=option["id"])
        return next(row for row in database.get_closed_options(self.user) if row["source_lot_id"] == option["id"])

    def test_journal_review_is_owned_audited_and_reversible(self):
        trade = self.closed_option()
        event_id = trade["ledger_event_id"]
        first = self.entry("review", event_id=event_id, exit_reason="profit_target", target_capture_pct="50", note="Original target")
        row = database.get_closed_options(self.user)[0]
        self.assertEqual(row["review"]["target_capture_pct"], 50)
        self.assertEqual(row["review"]["exit_reason"], "profit_target")
        self.assertEqual(row["net_pnl"], 300)
        second = self.entry("review", event_id=event_id, exit_reason="discretionary", target_capture_pct="75")
        self.assertEqual(database.get_closed_options(self.user)[0]["review"]["review_id"], second["id"])
        self.entry("reverse", event_id=second["id"])
        self.assertEqual(database.get_closed_options(self.user)[0]["review"]["review_id"], first["id"])
        from uuid import uuid4
        with self.assertRaises(ValueError):
            self.accounting.record_entry(1, dict(kind="review", event_id=event_id, exit_reason="stop",
                occurred_at="2026-01-01T00:00:00Z", idempotency_key=uuid4().hex))
        for changes in ({"target_capture_pct": 101}, {"target_capture_pct": -1}, {"exit_reason": "guessed"}, {"amount": 10}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.entry("review", event_id=event_id, **changes)
        database.delete_closed_option(self.user, trade["id"])
        with self.assertRaises(ValueError):
            self.entry("review", event_id=event_id, exit_reason="other")

    def test_journal_review_rejects_capture_target_on_long_option(self):
        trade = self.closed_option(position="long")
        with self.assertRaisesRegex(ValueError, "short options"):
            self.entry("review", event_id=trade["ledger_event_id"], target_capture_pct=50)
        self.entry("review", event_id=trade["ledger_event_id"], exit_reason="stop")
        self.assertEqual(database.get_closed_options(self.user)[0]["review"]["exit_reason"], "stop")

    def test_journal_cycle_components_reconcile_allocations_and_fees(self):
        put = self.closed_option()
        call = self.closed_option(option_type="call")
        stock = database.add_user_holding(self.user, "AAPL", 100, 100)
        database.sell_user_holding_by_lot(self.user, stock["id"], 100, 90)
        sold = database.get_closed_trades(self.user)[0]
        for trade, quantity, fee in ((put, 1, 4), (call, 2, 6), (sold, 100, 5)):
            self.entry("fee", event_id=trade["ledger_event_id"], amount=fee)
            self.entry("link", event_id=trade["ledger_event_id"], cycle="AAPL cycle", quantity=quantity)
        cycle = self.accounting.report(self.user)["cycles"][0]
        self.assertEqual((cycle["put_pnl"], cycle["call_pnl"], cycle["stock_pnl"], cycle["fees"], cycle["realized_pnl"]),
                         (150, 300, -1000, 13, -563))
        self.assertEqual(cycle["unresolved_links"], 0)
        self.assertTrue(all(link["status"] == "realized" for link in cycle["links"]))
        with self.assertRaises(ValueError):
            self.entry("link", event_id=call["ledger_event_id"], cycle="Duplicate", quantity=1)
        database.delete_closed_trade(self.user, sold["id"])
        cycle = self.accounting.report(self.user)["cycles"][0]
        self.assertEqual(cycle["unresolved_links"], 1)
        self.assertEqual(cycle["realized_pnl"], 442)

    def test_journal_review_api_validation_and_idempotency(self):
        import main
        from fastapi.testclient import TestClient
        from uuid import uuid4
        client = TestClient(main.app)
        trade = self.closed_option()
        payload = dict(kind="review", event_id=trade["ledger_event_id"], target_capture_pct=50,
                       exit_reason="roll", occurred_at="2026-01-01T00:00:00Z", idempotency_key=uuid4().hex)
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": self.user}}):
            first = client.post("/api/accounting/entries", json=payload)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(client.post("/api/accounting/entries", json=payload).json(), first.json())
            self.assertEqual(client.post("/api/accounting/entries", json=payload | {"target_capture_pct": 101}).status_code, 422)
            self.assertEqual(client.get("/api/portfolio/options/closed").json()["trades"][0]["review"]["exit_reason"], "roll")

    def test_journal_fields_preserve_older_ledger_retry_keys(self):
        import json
        from uuid import uuid4
        from portfolio_models import AccountingEntryRequest
        payload = AccountingEntryRequest(kind="fee", amount="2.50", occurred_at="2026-01-01T00:00:00Z",
                                         idempotency_key=uuid4().hex).model_dump(mode="json")
        previous = {key: value for key, value in payload.items() if key not in {"exit_reason", "target_capture_pct"}}
        database._run(f"""INSERT INTO accounting_events(user_id, source, source_id, operation, after_json, idempotency_key)
            VALUES ({database.PH}, 'manual', 0, 'FEE', {database.PH}, {database.PH})""",
                      (self.user, json.dumps(previous), payload["idempotency_key"]))
        first = self.accounting.record_entry(self.user, payload)
        self.assertEqual(self.accounting.record_entry(self.user, payload), first)
        self.assertEqual(self.accounting.report(self.user)["fees"], 2.5)
        with self.assertRaises(ValueError):
            self.accounting.record_entry(self.user, payload | {"amount": "3.00"})

    def test_transfer_export_is_owned_signed_and_excludes_credentials(self):
        import account_transfer
        import json
        trade = self.closed_option()
        self.entry("review", event_id=trade["ledger_event_id"], exit_reason="roll")
        package = account_transfer.export_account(self.user)
        payload = json.loads(package["payload"])
        self.assertEqual(payload["counts"]["closed_options"], 1)
        self.assertEqual(payload["counts"]["options"], 0)
        self.assertNotIn("password", str(package))
        self.assertNotIn("idempotency_key", str(package))
        self.assertTrue(account_transfer.verify_package(package, self.user + 1)["events"])
        with self.assertRaisesRegex(ValueError, "different account"):
            account_transfer.verify_package(package, self.user)
        payload["source_user_id"] = 999999
        package["payload"] = json.dumps(payload)
        with self.assertRaisesRegex(ValueError, "signature"):
            account_transfer.verify_package(package, 1)

    def test_transfer_preserves_lots_fees_reviews_journal_and_retries(self):
        import account_transfer
        from uuid import uuid4
        destination = database.create_user(uuid4().hex, "unused", "Destination")["id"]
        untouched = database.add_user_holding(destination, "MSFT", 3, 20)
        option = database.add_user_option(self.user, "AAPL", "put", 100, "2027-01-15", 2, 2, "short")
        opening = next(row for row in self.accounting.list_events(self.user) if row["source"] == "options")
        self.entry("fee", event_id=opening["id"], amount=4)
        database.close_user_option(self.user, "AAPL", "put", 100, "2027-01-15", .5, 1, "short", option_id=option["id"])
        closed = database.get_closed_options(self.user)[0]
        self.entry("review", event_id=closed["ledger_event_id"], target_capture_pct=50, exit_reason="profit_target")
        self.entry("link", event_id=closed["ledger_event_id"], cycle="My wheel", quantity=1)
        fee = self.entry("fee", amount=30)
        self.entry("reverse", event_id=fee["id"])
        self.entry("valuation", amount=1000)
        self.entry("valuation", amount=1100)
        self.assertEqual(self.accounting.report(self.user)["twr"]["pct"], 10)
        database.add_journal(self.user, {"ticker": "AAPL", "side": "long", "shares": 1, "entry_date": "2025-09-01",
            "entry_price": 100, "exit_date": "2025-09-10", "exit_price": 110, "notes": "Original journal"})
        package = account_transfer.export_account(self.user)
        before = len(self.accounting.list_events(destination))
        preview = account_transfer.preview_import(destination, package)
        self.assertEqual(preview["counts"]["journal"], 1)
        self.assertEqual(len(self.accounting.list_events(destination)), before)
        result = account_transfer.import_account(destination, package)
        self.assertFalse(result["already_imported"])
        imported = database.get_closed_options(destination)[0]
        self.assertNotEqual(imported["ledger_event_id"], closed["ledger_event_id"])
        self.assertEqual(imported["net_pnl"], 148)
        self.assertEqual(imported["review"]["target_capture_pct"], 50)
        self.assertEqual(database.list_journal(destination)[0]["notes"], "Original journal")
        report = self.accounting.report(destination)
        self.assertEqual(report["fees"], 4)
        self.assertEqual(report["cycles"][0]["realized_pnl"], 148)
        self.assertIsNone(report["twr"]["pct"])
        self.assertIn("not consolidated", report["twr"]["reason"])
        self.assertEqual(database._run(f"SELECT shares FROM holdings WHERE id={database.PH}", (untouched["id"],), fetch="one")["shares"], 3)
        event_count = len(self.accounting.list_events(destination))
        self.assertTrue(account_transfer.import_account(destination, package)["already_imported"])
        self.assertEqual(len(self.accounting.list_events(destination)), event_count)
        self.assertEqual(account_transfer.export_account(self.user)["payload"], package["payload"])
        self.entry("fee", amount=1)
        with self.assertRaisesRegex(ValueError, "already imported"):
            account_transfer.import_account(destination, account_transfer.export_account(self.user))

    def test_transfer_rolls_back_and_api_requires_confirmation_and_auth(self):
        import account_transfer
        import main
        from uuid import uuid4
        from fastapi.testclient import TestClient
        destination = database.create_user(uuid4().hex, "unused", "Destination")["id"]
        self.closed_option()
        package = account_transfer.export_account(self.user)
        insert = account_transfer._insert
        def fail_marker(cursor, table, values):
            if values.get("source") == "account_transfer":
                raise ValueError("Injected failure")
            return insert(cursor, table, values)
        with patch.object(account_transfer, "_insert", side_effect=fail_marker), self.assertRaisesRegex(ValueError, "Injected"):
            account_transfer.import_account(destination, package)
        self.assertEqual(database.get_closed_options(destination), [])
        self.assertEqual(self.accounting.list_events(destination), [])
        client = TestClient(main.app)
        self.assertEqual(client.get("/api/account-transfer/export").status_code, 401)
        with patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": destination}}):
            self.assertEqual(client.post("/api/account-transfer/import", json={"package": package}).status_code, 400)
            self.assertEqual(client.post("/api/account-transfer/preview", json=package).status_code, 200)
            response = client.post("/api/account-transfer/import", json={"package": package, "confirm": True})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_transfer_historical_edits_stocks_watchlist_and_cycle_name_conflicts(self):
        import account_transfer
        from uuid import uuid4
        destination = database.create_user(uuid4().hex, "unused", "Destination")["id"]
        holding = database.add_user_holding(self.user, "AAPL", 5, 100)
        database.sell_user_holding_by_lot(self.user, holding["id"], 2, 110)
        historic = dict(ticker="WDC", option_type="put", position="short", strike="65", expiry="2025-09-19",
            contracts=1, open_premium="1.20", close_premium="0.35", opened_at="2025-09-01", closed_at="2025-09-10",
            fees="1.30", notes="Original", idempotency_key=uuid4().hex)
        old = database.record_closed_option(self.user, historic)
        database.record_closed_option(self.user, historic | {"close_premium": "0.25", "fees": "2.50", "idempotency_key": uuid4().hex}, trade_id=old["id"])
        closed = database.get_closed_options(self.user)[0]
        self.entry("link", event_id=closed["ledger_event_id"], cycle="Shared name", quantity=1)
        target = database.add_user_holding(destination, "MSFT", 1, 10)
        event = next(row for row in self.accounting.list_events(destination) if row["source"] == "holdings")
        self.accounting.record_entry(destination, dict(kind="link", event_id=event["id"], cycle="Shared name", quantity=1,
            occurred_at="2026-01-01T00:00:00Z", idempotency_key=uuid4().hex))
        for owner in (self.user, destination):
            database._run(f"INSERT INTO watchlist (user_id, ticker) VALUES ({database.PH}, 'AAPL')", (owner,))
        account_transfer.import_account(destination, account_transfer.export_account(self.user))
        imported = database.get_closed_options(destination)[0]
        self.assertTrue(imported["is_manual"])
        self.assertEqual(imported["net_pnl"], 92.5)
        self.assertEqual(database.get_closed_trades(destination)[0]["pnl"], 20)
        self.assertEqual(len(database._run(f"SELECT * FROM watchlist WHERE user_id={database.PH}", (destination,), fetch="all")), 1)
        self.assertEqual(len({cycle["name"] for cycle in self.accounting.report(destination)["cycles"]}), 2)
        self.assertEqual(len(database.get_user_holdings(destination)), 2)
        self.assertNotEqual(imported["id"], old["id"])
        self.assertTrue(database.delete_closed_option(destination, imported["id"]))
        self.assertEqual(self.accounting.report(destination)["fees"], 0)
        self.assertEqual(database.get_closed_options(self.user)[0]["net_pnl"], 92.5)

    def test_journal_cycle_open_lot_becomes_unresolved_after_close(self):
        lot = database.add_user_option(self.user, "AAPL", "put", 100, "2027-01-15", 2, 2, "short")
        event = next(row for row in self.accounting.list_events(self.user)
                     if row["source"] == "options" and row["source_id"] == lot["id"] and row["operation"] == "INSERT")
        allocation = self.entry("link", event_id=event["id"], cycle="Open wheel", quantity=2)
        cycle = self.accounting.report(self.user)["cycles"][0]
        self.assertEqual((cycle["open_links"], cycle["unresolved_links"], cycle["realized_pnl"]), (1, 0, 0))
        database.close_user_option(self.user, "AAPL", "put", 100, "2027-01-15", 0.5, 2, "short", option_id=lot["id"])
        cycle = self.accounting.report(self.user)["cycles"][0]
        self.assertEqual((cycle["open_links"], cycle["unresolved_links"], cycle["realized_pnl"]), (0, 1, 0))
        with self.assertRaises(ValueError):
            self.entry("link", event_id=event["id"], cycle="Open wheel", quantity=1)
        self.entry("reverse", event_id=allocation["id"])
        closed = database.get_closed_options(self.user)[0]
        self.entry("link", event_id=closed["ledger_event_id"], cycle="Open wheel", quantity=2)
        cycle = self.accounting.report(self.user)["cycles"][0]
        self.assertEqual((cycle["open_links"], cycle["unresolved_links"], cycle["realized_pnl"]), (0, 0, 300))

    def test_time_weighted_return_uses_pre_flow_nav(self):
        entries = [{"id": 1, "kind": "valuation", "amount": 100, "occurred_at": "2026-01-01T00:00:00Z"},
                   {"id": 2, "kind": "deposit", "amount": 50, "nav_before": 110, "occurred_at": "2026-01-02T00:00:00Z"},
                   {"id": 3, "kind": "valuation", "amount": 176, "occurred_at": "2026-01-03T00:00:00Z"}]
        self.assertEqual(self.accounting.time_weighted_return(entries)["pct"], 21)
        entries[1]["nav_before"] = None
        self.assertIsNone(self.accounting.time_weighted_return(entries)["pct"])
        self.assertIsNone(self.accounting.time_weighted_return(entries[:1])["pct"])

    def test_full_withdrawal_is_recordable_without_inventing_a_return(self):
        self.entry("valuation", amount=100)
        self.entry("withdrawal", amount=100, nav_before=100, occurred_at="2026-01-02T00:00:00Z")
        report = self.accounting.report(self.user)
        self.assertEqual(report["external_cash_flow"], -100)
        self.assertIsNone(report["twr"]["pct"])

    def test_zero_ending_nav_records_total_loss(self):
        self.entry("valuation", amount=100)
        self.entry("valuation", amount=0, occurred_at="2026-01-02T00:00:00Z")
        self.assertEqual(self.accounting.report(self.user)["twr"]["pct"], -100)

    def test_partial_fee_rounding_reconciles_to_the_recorded_fee(self):
        lot = database.add_user_holding(self.user, "AAPL", 3, 100)
        opening = next(event for event in self.accounting.list_events(self.user) if event["source"] == "holdings")
        self.entry("fee", amount="0.01", event_id=opening["id"])
        for _ in range(3):
            database.sell_user_holding_by_lot(self.user, lot["id"], 1, 100)
        report = self.accounting.report(self.user)
        self.assertEqual(sum(trade["fees"] for trade in report["tax_lots"]), .01)
        self.assertEqual(sum(trade["gain"] for trade in report["tax_lots"]), -.01)


class RiskTests(unittest.TestCase):
    def setUp(self):
        import options_desk
        self.desk = options_desk
        self.short = dict(id=1, ticker="AAPL", option_type="put", position="short", strike=100,
                          expiry="2027-01-15", contracts=10, premium=2)
        self.long = dict(self.short, id=2, position="long", strike=95, contracts=1, premium=1)

    def test_one_wing_cannot_cover_ten_shorts(self):
        self.assertEqual(self.desk._put_capital(self.short, [self.long]), 90500)

    def test_wings_not_reused_across_short_lots(self):
        positions = [dict(self.short, contracts=1), dict(self.short, id=3, contracts=1), self.long]
        self.assertEqual(self.desk.capital_requirements(positions, [])["reserved_cash"], 10500)

    def test_call_coverage_not_reused(self):
        call = dict(self.short, option_type="call", contracts=1)
        result = self.desk.capital_requirements([call, dict(call, id=2)], [{"ticker": "AAPL", "shares": 100}])
        self.assertEqual(result["uncovered_calls"], 1)

    def test_failed_quote_preserves_position(self):
        with patch.object(self.desk, "get_user_options", return_value=[self.short]), \
             patch.object(self.desk, "get_user_holdings", return_value=[]), \
             patch.object(self.desk.oa, "_spot", side_effect=RuntimeError("unavailable")):
            result = self.desk.position_actions(1)
        self.assertEqual(len(result["positions"]), 1)
        self.assertIsNone(result["positions"][0]["pnl"])
        self.assertGreater(result["counts"]["warn"], 0)

    def test_entry_premium_is_not_unrealized_profit(self):
        with patch.object(self.desk, "get_user_options", return_value=[self.short]), \
             patch.object(self.desk, "get_closed_options", return_value=[]), \
             patch.object(self.desk, "get_closed_trades", return_value=[]), \
             patch.object(self.desk, "get_user_holdings", return_value=[]), \
             patch.object(self.desk.oa, "_spot", return_value=100), \
             patch.object(self.desk, "_contract", return_value={"mid": 2}), \
             patch.object(self.desk, "get_stock_data", side_effect=RuntimeError("offline")):
            self.assertEqual(self.desk.wheel_ledger(1)["total_pnl"], 0)

    def test_planner_reserves_existing_collateral_and_blocks_stale_data(self):
        import wheel
        with patch.object(database, "get_user_holdings", return_value=[]), \
             patch.object(database, "get_user_options", return_value=[self.short]), \
             patch.object(wheel, "get_wheel", return_value={"rows": [], "updated_at": "2020-01-01T00:00:00+00:00"}), \
             patch.object(wheel, "_profile", return_value={"sector": "Technology"}):
            result = wheel.plan(150000, user_id=1)
        self.assertEqual(result["reserved_cash"], 100000)
        self.assertEqual(result["cash_left"], 50000)
        self.assertEqual(result["picks"], [])
        self.assertTrue(result["blocked"])

    def test_combined_ledger_includes_all_tickers_and_closed_stock_only(self):
        holdings = [{"ticker": "AAPL", "shares": 1, "buy_price": 90}, {"ticker": "MSFT", "shares": 2, "buy_price": 100}]
        with patch.object(self.desk, "get_user_options", return_value=[]), \
             patch.object(self.desk, "get_closed_options", return_value=[]), \
             patch.object(self.desk, "get_user_holdings", return_value=holdings), \
             patch.object(self.desk, "get_closed_trades", return_value=[{"ticker": "NVDA", "pnl": 30}]), \
             patch.object(self.desk.oa, "_spot", return_value=100):
            result = self.desk.wheel_ledger(1)
        self.assertEqual({row["ticker"] for row in result["rows"]}, {"AAPL", "MSFT", "NVDA"})
        self.assertEqual(result["total_pnl"], 40)

    def test_empty_combined_ledger_returns_zero(self):
        with patch.object(self.desk, "get_user_options", return_value=[]), \
             patch.object(self.desk, "get_closed_options", return_value=[]), \
             patch.object(self.desk, "get_user_holdings", return_value=[]), \
             patch.object(self.desk, "get_closed_trades", return_value=[]):
            result = self.desk.wheel_ledger(1)
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["total_pnl"], 0)

    def test_planner_uses_refreshed_bid_delta_and_earnings(self):
        import wheel
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        candidate = {"ticker": "AAPL", "name": "Apple", "sector": "Technology", "price": 105,
                     "strike": 100, "expiry": (now + timedelta(days=30)).date().isoformat(), "dte": 30,
                     "delta": 0.2, "premium": 200, "annualized_pct": 24, "cushion_pct": 5,
                     "liquidity": "good", "score": 80, "earnings_date": (now + timedelta(days=60)).date().isoformat()}
        with patch.object(database, "get_user_holdings", return_value=[]), \
             patch.object(database, "get_user_options", return_value=[]), \
             patch.object(wheel, "get_wheel", return_value={"rows": [candidate], "updated_at": now.isoformat()}) as snapshot, \
             patch.object(wheel.oa, "earnings_info", return_value={"next": candidate["earnings_date"]}) as earnings, \
             patch.object(wheel.oa, "_spot", return_value=110), \
             patch.object(self.desk, "_contract", return_value={"bid": 1.5, "ask": 1.6, "mid": 1.55, "delta": -0.15}):
            result = wheel.plan(50000, user_id=1)
            self.assertEqual(result["picks"][0]["contracts"], 1)
            self.assertEqual(result["picks"][0]["premium"], 149)
            self.assertEqual(result["picks"][0]["delta"], 0.15)
            self.assertEqual(result["cash_left"], 40000)
            self.assertEqual(wheel.plan(50000, user_id=1, short_dated=True)["picks"], [])
            snapshot.assert_called_with(start_if_stale=False, short_dated=True)
            with patch.object(wheel.oa, "_dte", return_value=14):
                self.assertEqual(len(wheel.plan(50000, user_id=1, short_dated=True)["picks"]), 1)
                self.assertEqual(wheel.plan(50000, user_id=1)["picks"], [])
                earnings.return_value = {"next": candidate["expiry"]}
                self.assertEqual(wheel.plan(50000, user_id=1, short_dated=True)["picks"], [])
            earnings.return_value = {"next": None}
            self.assertEqual(wheel.plan(50000, user_id=1)["picks"], [])


class WheelExpiryTests(unittest.TestCase):
    def test_quality_pool_keeps_stocks_exactly_at_their_52_week_high(self):
        import wheel
        base = {"trend": "uptrend", "atr_pct": 1.5, "rs_rating": 80, "price": 120}
        rows = [{**base, "symbol": "HIGH", "pct_from_high": 0.0}, {**base, "symbol": "NEG0", "pct_from_high": -0.0},
                {**base, "symbol": "FAR", "pct_from_high": -25.0}, {**base, "symbol": "NONE", "pct_from_high": None}]
        self.assertEqual(sorted(r["symbol"] for r in wheel._quality_pool(rows)), ["HIGH", "NEG0"])
        self.assertTrue(wheel._quality_checks({**base, "pct_from_high": 0.0})[2]["ok"])

    def test_scan_routes_window_and_writes_matching_cache(self):
        import wheel
        row = {"symbol": "PYPL", "price": 52.8}
        with patch.object(wheel, "_running", set()), \
             patch.object(wheel, "kv_get", return_value={"data": {"rows": [row]}}), \
             patch.object(wheel, "_quality_pool", return_value=[row]), \
             patch.object(wheel, "_spots", return_value={}), \
             patch.object(wheel.oa, "_earnings_date", return_value="2026-10-27"), \
             patch.object(wheel, "_candidate", return_value={"score": 80}) as candidate, \
             patch.object(wheel, "kv_set") as save, \
             patch.object(wheel.track_record, "record_wheel"):
            for short_dated in (True, False):
                result = wheel.run_wheel_scan(short_dated)
                candidate.assert_called_with(row, 52.8, "2026-10-27", short_dated)
                save.assert_called_with(wheel.WHEEL_KEY + (":short" if short_dated else ""), result)
                self.assertEqual(result["short_dated"], short_dated)
                self.assertEqual(wheel._running, set())

    def test_expiry_windows_boundaries_and_earnings(self):
        import wheel
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/New_York")).date()  # DTE is counted on the New York calendar
        expiries = {days: (today + timedelta(days=days)).isoformat() for days in (6, 7, 14, 20, 21, 35, 50, 51)}
        with patch.object(wheel.oa, "_live", return_value=True), patch.object(wheel.oa, "_is_monthly", return_value=False):
            self.assertEqual(wheel._pick_expiry(list(expiries.values()), None), expiries[35])
            self.assertEqual(wheel._pick_expiry(list(expiries.values()), None, True), expiries[14])
            self.assertEqual(wheel._pick_expiry(list(expiries.values()), expiries[14], True), expiries[7])
            for days, expiry in expiries.items():
                self.assertEqual(wheel._pick_expiry([expiry], None, True), expiry if 7 <= days <= 20 else None)
                self.assertEqual(wheel._pick_expiry([expiry], None), expiry if 21 <= days <= 50 else None)

    def test_short_scan_cache_and_running_state_are_separate(self):
        import wheel
        from datetime import datetime, timezone
        snapshot = {"data": {"rows": [], "updated_at": datetime.now(timezone.utc).isoformat()}}
        with patch.object(wheel, "kv_get", return_value=snapshot) as get, patch.object(wheel, "_running", {True}):
            self.assertEqual(wheel.get_wheel(False, True)["status"], "running")
            get.assert_called_with(wheel.WHEEL_KEY + ":short")
            self.assertEqual(wheel.get_wheel(False)["status"], "ready")
            get.assert_called_with(wheel.WHEEL_KEY)

    def test_wheel_refreshes_every_15_minutes_in_session_and_once_after_close(self):
        import wheel
        from datetime import datetime
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        thursday = lambda h, m: datetime(2026, 10, 8, h, m, tzinfo=et)
        self.assertTrue(wheel.refresh_due(None, thursday(12, 0)))
        self.assertFalse(wheel.refresh_due(thursday(12, 0).isoformat(), thursday(12, 14)))
        self.assertTrue(wheel.refresh_due(thursday(12, 0).isoformat(), thursday(12, 16)))
        # After the close: a scan from 3:50 PM already saw closing premiums; one from noon did not
        self.assertFalse(wheel.refresh_due(thursday(15, 50).isoformat(), thursday(22, 0)))
        self.assertTrue(wheel.refresh_due(thursday(12, 0).isoformat(), thursday(22, 0)))
        # Weekend and pre-market look back to Friday's / the prior close
        friday_close = datetime(2026, 10, 9, 15, 55, tzinfo=et).isoformat()
        self.assertFalse(wheel.refresh_due(friday_close, datetime(2026, 10, 11, 10, 0, tzinfo=et)))
        self.assertFalse(wheel.refresh_due(friday_close, datetime(2026, 10, 12, 8, 0, tzinfo=et)))

    def test_holidays_close_the_market_and_planning_follows_sessions(self):
        import scheduler
        import wheel
        from datetime import datetime
        from market_calendar import trading_day
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        thanksgiving_noon = datetime(2026, 11, 26, 12, 0, tzinfo=et)
        self.assertFalse(trading_day(thanksgiving_noon))
        self.assertFalse(scheduler._market_open(thanksgiving_noon))
        self.assertTrue(scheduler._market_open(datetime(2026, 11, 25, 12, 0, tzinfo=et)))
        wednesday_close = datetime(2026, 11, 25, 15, 55, tzinfo=et).isoformat()
        self.assertFalse(wheel.refresh_due(wednesday_close, thanksgiving_noon))
        # Weekend planning accepts Friday's closing scan; in session it needs one from the last 3 hours
        friday_close = datetime(2026, 10, 9, 15, 55, tzinfo=et).isoformat()
        self.assertFalse(wheel.plan_stale(friday_close, datetime(2026, 10, 11, 10, 0, tzinfo=et)))
        self.assertTrue(wheel.plan_stale(friday_close, datetime(2026, 10, 12, 11, 0, tzinfo=et)))
        self.assertFalse(wheel.plan_stale(datetime(2026, 10, 12, 10, 0, tzinfo=et).isoformat(),
                                          datetime(2026, 10, 12, 12, 0, tzinfo=et)))
        self.assertTrue(wheel.plan_stale(None))


class EvaluationTests(unittest.TestCase):
    def test_holdout_is_chronological_and_cost_sensitive(self):
        import backtester
        import numpy as np
        import pandas as pd
        prices = 100 + np.sin(np.arange(300) / 5) * 5
        frame = pd.DataFrame({"Open": prices, "High": prices + 1, "Low": prices - 1,
                              "Close": prices, "Volume": 100, "day": np.arange(300)},
                             index=pd.date_range("2024-01-01", periods=300))
        result = backtester._validation(frame, "ema_cross", {"fast": 3, "slow": 9}, False, 390, "both", 0.001, 0, 0)
        self.assertLess(result["train"]["to"], result["holdout"]["from"])
        self.assertEqual(len(result["windows"]), 3)
        holdout = result["holdout"]
        self.assertGreater(holdout["stats"]["trades"], 0)
        self.assertLess(holdout["double_cost_stats"]["avg_net_pct"], holdout["stats"]["avg_net_pct"])

    def test_invalid_indicator_windows_rejected(self):
        import backtester
        for params in ({"fast": 0}, {"fast": 1.5}, {"fast": 40, "slow": 20}):
            with self.assertRaises(ValueError):
                backtester._params("ema_cross", params)

    def test_crossed_or_last_only_quotes_are_not_marks(self):
        import options_analytics
        self.assertIsNone(options_analytics._mid({"bid": 3, "ask": 2, "lastPrice": 2.5}))
        self.assertIsNone(options_analytics._mid({"lastPrice": 2.5}))
        self.assertEqual(options_analytics._mid({"bid": 2, "ask": 3}), 2.5)


class WalkForwardTests(unittest.TestCase):
    def test_future_prices_cannot_change_earlier_parameter_selection(self):
        import numpy as np
        import pandas as pd
        import backtester
        frame = pd.DataFrame({"Close": np.full(600, 100.0), "day": np.arange(600)}, index=pd.date_range("2020-01-01", periods=600))
        params = backtester._params("ema_cross", {})

        def signals(sample, strategy, selected, intraday):
            return (pd.Series(selected["fast"], index=sample.index),)

        def simulate(sample, signal, *args):
            fast = signal[0].iloc[0]
            score = fast if sample["Close"].mean() > 150 else 20 - fast
            return [{"ret": score / 1000, "bars": 1, "side": 1} for _ in range(6)]

        with patch.object(backtester, "_signals", side_effect=signals), patch.object(backtester, "_simulate", side_effect=simulate):
            original = backtester._walk_forward(frame, "ema_cross", params, False, 390, "both", .001, 0, 0)
            altered = frame.copy()
            altered.iloc[360:, altered.columns.get_loc("Close")] = 1000
            changed = backtester._walk_forward(altered, "ema_cross", params, False, 390, "both", .001, 0, 0)
        self.assertEqual(len(original["windows"]), 5)
        self.assertIsNotNone(original["windows"][0]["params"])
        self.assertEqual(original["windows"][0], changed["windows"][0])
        for original_fold, changed_fold in zip(original["windows"][:2], changed["windows"][:2]):
            self.assertEqual(original_fold["params"], changed_fold["params"])
            self.assertEqual(original_fold["training_stats"], changed_fold["training_stats"])
        for fold in original["windows"]:
            self.assertLess(fold["train_to"], fold["from"])
            self.assertLess(fold["double_cost_stats"]["avg_net_pct"], fold["stats"]["avg_net_pct"])


class ResearchDataTests(unittest.TestCase):
    def test_failed_database_health_check_returns_503(self):
        import asyncio
        import main
        from fastapi import HTTPException
        with patch.object(database, "get_db", side_effect=RuntimeError("unavailable")):
            with self.assertRaises(HTTPException) as failure:
                asyncio.run(main.api_health_check())
        self.assertEqual(failure.exception.status_code, 503)

    def test_universe_never_uses_later_publications(self):
        import uuid
        import research_universe
        source = "fixture-" + uuid.uuid4().hex
        research_universe.save_snapshot({"as_of": "2024-01-01", "known_at": "2024-01-01T12:00:00Z", "source": source, "members": ["OLD"]})
        research_universe.save_snapshot({"as_of": "2024-02-01", "known_at": "2024-02-02T23:00:00Z", "source": source, "members": ["NEW"]})
        self.assertFalse(research_universe.members_at("2023-12-31", source)["available"])
        self.assertEqual(research_universe.members_at("2024-02-02", source)["members"], ["OLD"])
        self.assertEqual(research_universe.members_at("2024-02-03", source)["members"], ["NEW"])
        with self.assertRaises(ValueError):
            research_universe.save_snapshot({"as_of": "2024-01-01", "known_at": "2024-01-01T12:00:00Z", "source": source, "members": ["REPLACED"]})

    def test_paper_costs_are_frozen_and_legacy_outcomes_excluded(self):
        import track_record
        row = track_record._row("long", "test", "AAPL", "2024-01-01", [{"side": "buy", "type": "call", "strike": 100}], -1, 1, 100, .5)
        self.assertEqual(row["cost_per_share"], .04)
        with patch.object(track_record, "idea_log_rows", return_value=[dict(row, pnl=.02), dict(row, pnl=10, cost_per_share=None)]):
            summary = track_record.summary()
        self.assertEqual(summary["legacy_uncosted"], 1)
        self.assertEqual(summary["open"], 0)
        self.assertEqual(summary["groups"][0]["win_rate"], 0)
        self.assertEqual(summary["groups"][0]["avg_net_pnl_per_contract"], -2)

    def test_scanner_filters_nonmembers_and_refuses_missing_prices(self):
        import scanner
        import pandas as pd
        events = [("breakout", pd.Timestamp("2024-01-02"), {horizon: .1 for horizon in scanner.HORIZONS}, symbol) for symbol in ("OLD", "NEW")]
        with patch("research_universe.members_at", return_value={"available": True, "members": ["OLD"]}):
            result = scanner._point_in_time_record(events, None, "fixture", [])
            incomplete = scanner._point_in_time_record(events, None, "fixture", ["DELISTED"])
        self.assertEqual(result["track_record"]["breakout"]["signals"], 1)
        self.assertEqual(result["excluded_nonmember_signals"], 1)
        self.assertFalse(incomplete["available"])
        self.assertEqual(incomplete["track_record"], {})


class DirectionalSafeguardsTests(unittest.TestCase):
    def evaluate(self, liquidity="good", earnings_offset=60, risk="moderate", direction="bear", fund=False,
                 expiry_offsets=(30,), shares=False):
        from contextlib import ExitStack
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        import options_analytics as analytics
        today = datetime.now(ZoneInfo("America/New_York")).date()
        expiries = [(today + timedelta(days=days)).isoformat() for days in expiry_offsets]
        earnings = (today + timedelta(days=earnings_offset)).isoformat() if earnings_offset is not None else None
        idea = {"kind": "long", "liquidity": liquidity, "cost": 100, "stretched": False, "legs": [{"delta": 0.75}]}
        values = {"_spot": 100, "_expirations": expiries,
                  "_chain": (None, None), "_otm_rows": [], "_atm_iv": 0.3,
                  "volatility_overview": {"level": "normal"}, "_earnings_date": earnings, "_is_fund": fund,
                  "_earnings_extra": {}, "_long_option": (idea, None), "_debit_spread": (None, None)}
        with ExitStack() as stack:
            for name, value in values.items():
                stack.enter_context(patch.object(analytics, name, return_value=value))
            # Latest offered expiry within the candidates, or none: mirrors the real picker's contract.
            stack.enter_context(patch.object(analytics, "_liquid_expiry",
                                             side_effect=lambda ticker, exps, *args: (max(exps), None) if exps else (None, None)))
            stack.enter_context(patch.object(analytics, "get_or_fetch", side_effect=lambda key, fetch, **kwargs: fetch()))
            record = stack.enter_context(patch.object(analytics.track_record, "record_directional"))
            result = analytics.directional_ideas("AAPL", direction, 20000 if shares else 200, risk)
        return result, record

    def test_ineligible_directional_ideas_are_not_recommended_or_recorded(self):
        for liquidity, earnings in (("thin", 60), (None, 60), ("good", None), ("good", 10), ("good", 30)):
            with self.subTest(liquidity=liquidity, earnings=earnings):
                result, record = self.evaluate(liquidity, earnings)
                self.assertEqual(result["ideas"], [])
                self.assertTrue(result["no_trade_reason"])
                self.assertIsNone(result["best_why"])
                record.assert_not_called()

    def test_liquid_directional_idea_before_known_earnings_remains_available(self):
        result, record = self.evaluate()
        self.assertEqual(len(result["ideas"]), 1)
        self.assertTrue(result["ideas"][0]["best"])
        record.assert_called_once()

    def test_moves_to_the_last_liquid_expiry_before_earnings(self):
        result, _ = self.evaluate(earnings_offset=25, expiry_offsets=(18, 30))
        self.assertEqual(result["dte"], 18)
        self.assertIn("before earnings", result["expiry_note"])
        self.assertIsNone(result["no_trade_reason"])
        self.assertFalse(result["earnings_before_expiry"])

    def test_funds_without_earnings_and_leaps_through_earnings_are_not_blocked(self):
        fund, _ = self.evaluate(earnings_offset=None, fund=True)
        self.assertEqual([i["kind"] for i in fund["ideas"]], ["long"])
        unknown, _ = self.evaluate(earnings_offset=None, fund=False)
        self.assertEqual(unknown["ideas"], [])
        leaps, _ = self.evaluate(earnings_offset=40, risk="low", expiry_offsets=(365,))
        self.assertEqual([i["kind"] for i in leaps["ideas"]], ["long"])
        self.assertTrue(leaps["earnings_before_expiry"])

    def test_shares_survive_the_option_earnings_block(self):
        result, _ = self.evaluate(earnings_offset=10, direction="bull", shares=True)
        self.assertEqual([i["kind"] for i in result["ideas"]], ["shares"])
        self.assertIn("Shares are still shown", result["no_trade_reason"])


if __name__ == "__main__":
    unittest.main()