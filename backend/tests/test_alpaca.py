import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

if not os.environ.get("STOCKPILOT_DB_PATH"):
    _database_dir = tempfile.TemporaryDirectory()
    os.environ["DATABASE_URL"] = ""
    os.environ["STOCKPILOT_DB_PATH"] = os.path.join(_database_dir.name, "test.db")

import pandas as pd

import providers
import stock_data


def response(status, body=None):
    resp = MagicMock(status_code=status)
    resp.json.return_value = body or {}
    return resp


DAILY = {"bars": [{"t": "2026-10-15T04:00:00Z", "o": 100, "h": 102, "l": 99, "c": 101, "v": 1000},
                  {"t": "2026-10-16T04:00:00Z", "o": 101, "h": 104, "l": 100, "c": 103.5, "v": 1500}],
         "next_page_token": None}


class AlpacaTests(unittest.TestCase):
    def setUp(self):
        self.keys = patch.multiple(providers, ALPACA_API_KEY_ID="id", ALPACA_API_SECRET_KEY="secret")
        self.keys.start()
        providers._alpaca_bucket.tokens = providers._alpaca_bucket.capacity

    def tearDown(self):
        self.keys.stop()

    def test_disabled_without_keys(self):
        with patch.multiple(providers, ALPACA_API_KEY_ID="", ALPACA_API_SECRET_KEY=""), \
             patch.object(providers._session, "get") as get:
            self.assertIsNone(providers.alpaca_history("SPY", "1y", "1d"))
            self.assertIsNone(providers.alpaca_quote("SPY"))
        get.assert_not_called()

    def test_daily_history_is_shaped_like_yahoo_in_new_york_time(self):
        with patch.object(providers._session, "get", return_value=response(200, DAILY)) as get:
            df = providers.alpaca_history("SPY", "1y", "1d")
        self.assertEqual(list(df.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual([d.isoformat() for d in df.index.date], ["2026-10-15", "2026-10-16"])
        self.assertEqual(str(df.index.tz), "America/New_York")
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["timeframe"], params["feed"], params["adjustment"]), ("1Day", "sip", "all"))
        self.assertEqual(get.call_args.kwargs["headers"]["APCA-API-KEY-ID"], "id")
        self.assertIsNone(providers.alpaca_history("^VIX", "1y", "1d"), "indices are not on Alpaca")

    def test_falls_back_to_iex_and_pages_through_results(self):
        page1 = {"bars": DAILY["bars"][:1], "next_page_token": "abc"}
        page2 = {"bars": DAILY["bars"][1:], "next_page_token": None}
        with patch.object(providers._session, "get", side_effect=[response(403), response(200, page1), response(200, page2)]) as get:
            df = providers.alpaca_history("SPY", "1y", "1d")
        self.assertEqual(len(df), 2)
        self.assertEqual([c.kwargs["params"]["feed"] for c in get.call_args_list], ["sip", "iex", "iex"])
        self.assertEqual(get.call_args_list[2].kwargs["params"]["page_token"], "abc")

    def test_intraday_drops_extended_hours_unless_asked(self):
        bars = {"bars": [{"t": "2026-10-16T12:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},   # 8:00 ET
                         {"t": "2026-10-16T14:00:00Z", "o": 2, "h": 2, "l": 2, "c": 2, "v": 1},   # 10:00 ET
                         {"t": "2026-10-16T20:30:00Z", "o": 3, "h": 3, "l": 3, "c": 3, "v": 1}]}  # 16:30 ET
        with patch.object(providers._session, "get", return_value=response(200, bars)):
            self.assertEqual(list(providers.alpaca_history("SPY", "5d", "5m")["Close"]), [2.0])
            self.assertEqual(len(providers.alpaca_history("SPY", "5d", "5m", prepost=True)), 3)

    def test_bad_key_gives_up_without_retrying(self):
        with patch.object(providers._session, "get", return_value=response(401)) as get:
            self.assertIsNone(providers.alpaca_history("SPY", "1y", "1d"))
        self.assertEqual(get.call_count, 1)

    def test_quote_from_snapshot(self):
        snap = {"latestTrade": {"p": 105.0, "t": "2026-10-19T15:00:00Z"}, "dailyBar": {"o": 103, "h": 106, "l": 102},
                "prevDailyBar": {"c": 100.0}}
        with patch.object(providers._session, "get", return_value=response(200, snap)), \
             patch.object(providers, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()):
            q = providers.alpaca_quote("AAPL")
        self.assertEqual((q["c"], q["pc"], round(q["dp"], 2), q["source"]), (105.0, 100.0, 5.0, "Alpaca (IEX)"))

    def test_stock_data_uses_alpaca_when_yahoo_fails(self):
        alpaca_df = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1.0]},
                                 index=pd.DatetimeIndex(["2026-10-16"], tz="America/New_York"))
        with patch.object(stock_data.yf, "Ticker", side_effect=RuntimeError("blocked")), \
             patch.object(stock_data, "alpaca_history", return_value=alpaca_df) as alpaca, \
             patch.object(stock_data, "twelvedata_history") as twelve, \
             patch.object(stock_data, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()):
            df = stock_data.get_stock_data("ZZZ", period="1y", interval="1d")
        self.assertEqual(float(df["Close"].iloc[-1]), 1.0)
        alpaca.assert_called_once_with("ZZZ", "1y", "1d", False)
        twelve.assert_not_called()

    def test_quote_and_metrics_fall_back_to_alpaca(self):
        q = {"c": 50.0, "pc": 49.0, "d": 1.0, "dp": 2.04, "o": 49.5, "h": 51, "l": 49, "source": "Alpaca (IEX)"}
        with patch.object(stock_data, "finnhub_enabled", return_value=False), \
             patch.object(stock_data, "alpaca_quote", return_value=q):
            self.assertEqual(stock_data.get_quote("ZZZ")["price"], 50.0)
            with patch.object(stock_data, "_yf_metrics", side_effect=ValueError("No data")), \
                 patch.object(stock_data, "get_or_fetch", side_effect=lambda key, fetch, ttl: fetch()):
                metrics = stock_data.get_key_metrics("ZZZ")
        self.assertEqual((metrics["price"], metrics["previous_close"], metrics["price_source"]), (50.0, 49.0, "Alpaca (IEX)"))


if __name__ == "__main__":
    unittest.main()
