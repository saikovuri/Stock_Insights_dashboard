import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import requests
import market_context as context
from cache import invalidate


class MarketContextTests(unittest.TestCase):
    def setUp(self):
        invalidate("market-context:v1:attention")
        invalidate("market-context:v1:predictions")
        self.now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        self.market = {"id": "1", "question": "Fed cut in October?", "active": True, "closed": False,
                       "outcomes": '["Yes", "No"]', "outcomePrices": '["0.4", "0.6"]',
                       "endDate": "2026-10-29T00:00:00Z", "updatedAt": "2026-10-04T23:00:00Z",
                       "volume24hr": 20000, "liquidityNum": 100000, "oneDayPriceChange": -.03}

    def events(self, market=None):
        return [{"slug": "fed-october", "title": "Fed decision", "active": True, "closed": False,
                 "markets": [self.market if market is None else market]}]

    def test_attention_missing_baseline_is_not_infinite_growth(self):
        rows = context.normalize_attention({"results": [
            {"ticker": "MU", "rank": 1, "mentions": "120", "mentions_24h_ago": "20"},
            {"ticker": "SPY", "rank": 2, "mentions": 10, "mentions_24h_ago": 0},
            {"ticker": "QQQ", "rank": 3, "mentions": 5},
            {"ticker": "../bad", "rank": 4, "mentions": 5},
            {"ticker": "BAD", "rank": 5, "mentions": "nan"},
        ]})
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["change_pct"], 500)
        self.assertIsNone(rows[1]["change_pct"])
        self.assertIsNone(rows[2]["previous_mentions"])

    def test_prediction_outcome_mapping_units_and_deduplication(self):
        rows = context.normalize_predictions(self.events() * 2, self.now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["yes_pct"], 40)
        self.assertEqual(rows[0]["change_pp"], -3)
        self.assertEqual(rows[0]["warnings"], [])
        reversed_market = dict(self.market, outcomes='["No", "Yes"]')
        row = context.normalize_predictions(self.events(reversed_market), self.now)[0]
        self.assertEqual(row["yes_pct"], 60)
        self.assertIsNone(row["change_pp"])

    def test_predictions_reject_closed_expired_and_invalid_prices(self):
        for change in ({"closed": True}, {"endDate": "2026-01-01T00:00:00Z"},
                       {"outcomePrices": '["NaN", "0.6"]'}, {"outcomePrices": '["1.2", "0"]'},
                       {"outcomePrices": '["0.2", "0.2"]'}, {"outcomes": "not-json"}):
            with self.subTest(change=change):
                self.assertEqual(context.normalize_predictions(self.events(dict(self.market, **change)), self.now), [])

    def test_missing_liquidity_and_stale_time_are_explicit(self):
        market = dict(self.market, liquidityNum=None, volume24hr=0, updatedAt="2026-09-01T00:00:00Z")
        warnings = context.normalize_predictions(self.events(market), self.now)[0]["warnings"]
        self.assertIn("Liquidity unavailable", warnings)
        self.assertTrue(any("stale" in warning for warning in warnings))
        self.assertTrue(any("Low 24h" in warning for warning in warnings))

    @patch.dict("os.environ", {"EXTERNAL_CONTEXT_ENABLED": "1"})
    def test_failures_are_unavailable_and_cached_not_zero_activity(self):
        with patch.object(context, "_get", side_effect=requests.Timeout) as fetch:
            result = context.get_context("attention")
            self.assertEqual(result["status"], "unavailable")
            self.assertIsNone(result["fetched_at"])
            self.assertEqual(context.get_context("attention"), result)
            fetch.assert_called_once()

    @patch.dict("os.environ", {"EXTERNAL_CONTEXT_ENABLED": "0"})
    def test_operator_can_disable_all_external_requests(self):
        with patch.object(context, "_get") as fetch:
            self.assertEqual(context.get_context("predictions")["status"], "disabled")
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()