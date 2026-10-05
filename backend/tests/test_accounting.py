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
        from datetime import date, timedelta
        expiries = {days: (date.today() + timedelta(days=days)).isoformat() for days in (6, 7, 14, 20, 21, 35, 50, 51)}
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
    def evaluate(self, liquidity="good", earnings_offset=60):
        from contextlib import ExitStack
        from datetime import date, timedelta
        import options_analytics as analytics
        expiry = (date.today() + timedelta(days=30)).isoformat()
        earnings = (date.today() + timedelta(days=earnings_offset)).isoformat() if earnings_offset is not None else None
        idea = {"kind": "long", "liquidity": liquidity, "cost": 100}
        values = {"_spot": 100, "_expirations": [expiry], "_liquid_expiry": (expiry, None),
                  "_chain": (None, None), "_otm_rows": [], "_atm_iv": 0.3,
                  "volatility_overview": {"level": "normal"}, "_earnings_date": earnings,
                  "_earnings_extra": {}, "_long_option": (idea, None), "_debit_spread": (None, None)}
        with ExitStack() as stack:
            for name, value in values.items():
                stack.enter_context(patch.object(analytics, name, return_value=value))
            stack.enter_context(patch.object(analytics, "get_or_fetch", side_effect=lambda key, fetch, **kwargs: fetch()))
            record = stack.enter_context(patch.object(analytics.track_record, "record_directional"))
            result = analytics.directional_ideas("AAPL", "bear", 200, "moderate")
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


if __name__ == "__main__":
    unittest.main()