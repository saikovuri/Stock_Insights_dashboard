import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

_database_dir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("STOCKPILOT_DB_PATH", os.path.join(_database_dir.name, "test.db"))

import alerts
import macro
import stock_data


class MarketDisplayTests(unittest.TestCase):
    def test_52_week_range_includes_todays_session(self):
        provider = {"name": "NVIDIA", "price": 239.24, "day_high": 243.37, "day_low": 238.93,
                    "52w_high": 237.88, "52w_low": 164.27}
        with patch.object(stock_data, "finnhub_enabled", return_value=True), \
             patch.object(stock_data, "_finnhub_metrics", return_value=dict(provider)), \
             patch.object(stock_data, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()):
            metrics = stock_data.get_key_metrics("NVDA")
        self.assertEqual((metrics["52w_high"], metrics["52w_low"]), (243.37, 164.27))
        with patch.object(stock_data, "finnhub_enabled", return_value=False), \
             patch.object(stock_data, "_yf_metrics", return_value=dict(provider, price=160, day_high=0, day_low=None)), \
             patch.object(stock_data, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()):
            self.assertEqual(stock_data.get_key_metrics("NVDA")["52w_low"], 160)

    def test_near_high_alert_never_reports_negative_distance(self):
        result = alerts.check_alerts({"name": "NVIDIA", "price": 239.24, "52w_high": 239.24, "52w_low": 164.27,
                                         "volume": 0, "avg_volume": 0, "change_pct": 0})
        high = next(alert for alert in result if alert["type"] == "NEAR_52W_HIGH")
        self.assertIn("new 52-week high", high["message"])
        self.assertEqual(high["value"], 0)

    def test_future_calendar_events_do_not_show_actual_values(self):
        today = date.today()
        future = today + timedelta(days=1)
        rows = {today: [{"date": today.isoformat(), "time_et": "08:30", "event": "CPI", "impact": "high",
                         "actual": "0.2%", "consensus": "0.2%", "previous": "0.1%"}],
                future: [{"date": future.isoformat(), "time_et": "11:30", "event": "Atlanta Fed GDPNow", "impact": "high",
                          "actual": "3.7%", "consensus": "3.7%", "previous": "3.7%"}]}
        with patch.object(macro, "_day", side_effect=lambda d: rows.get(d, [])):
            events = {e["event"]: e for e in macro.economic_calendar(7)["events"]}
        if today.weekday() < 5:
            self.assertEqual(events["CPI"]["actual"], "0.2%")
        if future.weekday() < 5:
            self.assertIsNone(events["Atlanta Fed GDPNow"]["actual"])
            self.assertEqual(events["Atlanta Fed GDPNow"]["previous"], "3.7%")


if __name__ == "__main__":
    unittest.main()
