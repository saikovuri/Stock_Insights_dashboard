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
from portfolio_models import ClosedSpreadRequest

EXPIRY = "2099-01-15"
LATER = "2099-03-19"


def leg(position, option_type, strike, premium, expiry=EXPIRY, ratio=1, **extra):
    return dict(position=position, option_type=option_type, strike=strike, premium=premium, expiry=expiry, ratio=ratio, **extra)


def vertical(kind, low, high, low_fill, high_fill, expiry=EXPIRY):
    """Legs of a vertical: bull spreads buy the low strike, bear spreads sell it."""
    option_type = kind.split("_")[1]
    bull = kind.startswith("bull")
    return [leg("long" if bull else "short", option_type, low, low_fill, expiry),
            leg("short" if bull else "long", option_type, high, high_fill, expiry)]


CONDOR = [leg("long", "put", 90, 0.5), leg("short", "put", 95, 1.5), leg("short", "call", 105, 1.4), leg("long", "call", 110, 0.4)]


class StructureMathTests(unittest.TestCase):
    def test_verticals(self):
        cases = {  # (kind, low, high, low fill, high fill) -> (max profit, max loss, breakeven) for 2 structures
            ("bull_call", 100, 105, 3.0, 1.0): (600, 400, 102),
            ("bear_put", 100, 105, 1.0, 3.0): (600, 400, 103),
            ("bull_put", 95, 100, 1.0, 2.5): (300, 700, 98.5),
            ("bear_call", 100, 105, 2.5, 1.0): (300, 700, 101.5),
        }
        for (kind, low, high, f1, f2), (profit, loss, breakeven) in cases.items():
            with self.subTest(kind=kind):
                info = spreads.validate_open(vertical(kind, low, high, f1, f2), 2, kind)
                self.assertEqual((info["kind"], info["max_profit"], info["max_loss"], info["breakeven"]), (kind, profit, loss, breakeven))
                self.assertEqual(info["collateral"], 1000 if info["style"] == "credit" else 0)
                self.assertEqual(info["strikes"], f"${low}/${high}")

    def test_iron_condor_and_butterfly(self):
        info = spreads.validate_open(CONDOR, 1, "iron_condor")
        self.assertEqual((info["style"], info["net_open"], info["max_profit"], info["max_loss"]), ("credit", 2.0, 200, 300))
        self.assertEqual(info["breakevens"], [93.0, 107.0])
        self.assertEqual(info["collateral"], 500, "only one side can finish in the money")
        iron_fly = [leg("long", "put", 90, 0.5), leg("short", "put", 100, 4), leg("short", "call", 100, 4), leg("long", "call", 110, 0.5)]
        self.assertEqual(spreads.classify(iron_fly), "iron_butterfly")
        fly = [leg("long", "call", 100, 6), leg("short", "call", 105, 3, ratio=2), leg("long", "call", 110, 1.2)]
        info = spreads.validate_open(fly, 1, "call_butterfly")
        self.assertEqual((info["style"], info["max_loss"], info["max_profit"], info["collateral"]), ("debit", 120, 380, 0))
        self.assertEqual(info["breakevens"], [101.2, 108.8])
        broken_wing = [leg("long", "put", 90, 0.4), leg("short", "put", 100, 2, ratio=2), leg("long", "put", 105, 3.7)]
        self.assertEqual(spreads.describe(broken_wing)["collateral"], 500, "the wider lower wing can owe $5")

    def test_calendar_and_diagonal(self):
        calendar = [leg("short", "call", 100, 2.0), leg("long", "call", 100, 4.5, LATER)]
        info = spreads.validate_open(calendar, 1, "call_calendar")
        self.assertEqual((info["max_loss"], info["max_profit"], info["collateral"]), (250, None, 0))
        self.assertEqual(info["strikes"], f"$100 {EXPIRY} / $100 {LATER}")
        diagonal = [leg("short", "call", 100, 2.0), leg("long", "call", 105, 3.0, LATER)]
        info = spreads.validate_open(diagonal, 1, "call_diagonal")
        self.assertEqual((info["max_loss"], info["collateral"]), (600, 500), "a higher long strike leaves the gap uncovered")
        with self.assertRaisesRegex(ValueError, "nearer expiry"):
            spreads.classify([leg("long", "call", 100, 4.5), leg("short", "call", 100, 2.0, LATER)])

    def test_rejections(self):
        with self.assertRaisesRegex(ValueError, "bear put, not a bull put"):
            spreads.validate_open(vertical("bear_put", 95, 100, 1, 2.5), 1, "bull_put")
        with self.assertRaisesRegex(ValueError, "opened for a credit"):
            spreads.validate_open(vertical("bull_put", 95, 100, 2.5, 1), 1)
        with self.assertRaisesRegex(ValueError, "most it can make"):
            spreads.validate_open(vertical("bull_call", 100, 102, 3, 0.5), 1)
        with self.assertRaisesRegex(ValueError, "iron condor"):
            spreads.classify([leg("long", "put", 90, 1), leg("short", "put", 95, 1), leg("short", "put", 100, 1), leg("long", "call", 110, 1)])
        with self.assertRaisesRegex(ValueError, "butterfly"):
            spreads.classify([leg("long", "call", 100, 1), leg("short", "call", 105, 1), leg("long", "call", 110, 1)])
        with self.assertRaises(ValidationError):
            ClosedSpreadRequest(ticker="SPY", legs=[{"position": "long"}], contracts=1, opened_at="2026-01-01",
                                closed_at="2026-01-02", idempotency_key="key-00001")


class StructureLedgerTests(unittest.TestCase):
    def setUp(self):
        conn = database.get_db()
        for table in ("transactions", "closed_options", "options", "holdings"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, display_name) VALUES (1, 'test', 'unused', 'Test')")
        conn.commit()
        conn.close()

    def client(self):
        import main
        from fastapi.testclient import TestClient
        return main, TestClient(main.app)

    def as_user(self, main):
        return patch.dict(main.app.dependency_overrides, {main.get_current_user: lambda: {"user_id": 1}})

    def test_open_partial_close_and_merge_bull_put(self):
        opened = database.add_user_spread(1, "spy", vertical("bull_put", 95, 100, 1.0, 2.5), 3, account="IRA", kind="bull_put")
        self.assertEqual((opened["kind"], opened["net_open"], opened["max_loss"]), ("bull_put", 1.5, 1050))
        legs = database.get_user_options(1)
        self.assertEqual({(o["spread_id"], o["spread_ratio"], o["spread_legs"], o["account"]) for o in legs},
                         {(opened["spread_id"], 1, 2, "IRA")})
        ids = {o["position"]: o["id"] for o in legs}
        first = database.close_user_spread(1, opened["spread_id"], {ids["long"]: 0.25, ids["short"]: 0.75}, 1)
        self.assertEqual((first["pnl"], first["close_net"]), (100.0, 0.5))
        self.assertEqual({o["contracts"] for o in database.get_user_options(1)}, {2})
        database.close_user_spread(1, opened["spread_id"], {ids["long"]: 0, ids["short"]: 0}, 2)
        self.assertEqual(database.get_user_options(1), [])
        merged = spreads.merge_closed(database.get_closed_options(1))
        self.assertEqual(sorted(row["pnl"] for row in merged), [100.0, 300.0])
        whole = next(row for row in merged if row["contracts"] == 2)
        self.assertEqual((whole["position"], whole["open_premium"], whole["close_premium"], whole["spread"]["label"]),
                         ("short", 1.5, 0.0, "Bull put"))
        with self.assertRaises(LookupError):
            database.close_user_spread(1, opened["spread_id"], {ids["long"]: 0, ids["short"]: 0}, 1)

    def test_iron_condor_and_butterfly_ratios(self):
        condor = database.add_user_spread(1, "SPY", CONDOR, 2, kind="iron_condor")
        fly = database.add_user_spread(1, "SPY", [leg("long", "call", 100, 6), leg("short", "call", 105, 3, ratio=2),
                                                  leg("long", "call", 110, 1.2)], 3, kind="call_butterfly")
        groups = spreads.group_open(database.get_user_options(1))
        self.assertEqual(len(groups[condor["spread_id"]]), 4)
        self.assertEqual(sorted(o["contracts"] for o in groups[fly["spread_id"]]), [3, 3, 6])
        body = next(o for o in groups[fly["spread_id"]] if o["position"] == "short")
        prices = {o["id"]: {100: 7.0, 105: 3.5, 110: 1.0}[o["strike"]] for o in groups[fly["spread_id"]]}
        result = database.close_user_spread(1, fly["spread_id"], prices, 1)
        self.assertEqual(result["pnl"], -20.0)  # (7-6) + (1-1.2) - 2×(3.5-3) = -0.20 per share on 1 butterfly
        left = spreads.group_open(database.get_user_options(1))[fly["spread_id"]]
        self.assertEqual(next(o for o in left if o["id"] == body["id"])["contracts"], 4)
        [merged] = [r for r in spreads.merge_closed(database.get_closed_options(1)) if r.get("spread")]
        self.assertEqual((merged["contracts"], merged["spread"]["kind"], merged["open_premium"]), (1, "call_butterfly", 1.2))

    def test_edit_link_unlink_and_broken_legs(self):
        opened = database.add_user_spread(1, "QQQ", vertical("bull_call", 400, 410, 6.0, 2.0), 1, kind="bull_call")
        legs = database.get_user_options(1)
        edited = [dict(leg("long" if o["position"] == "long" else "short", "call", o["strike"] + 5,
                           5.5 if o["position"] == "long" else 2.2), id=o["id"]) for o in legs]
        result = database.update_user_spread(1, opened["spread_id"], edited, 2)
        self.assertEqual((result["strikes"], result["contracts"], result["net_open"]), ("$405/$415", 2, 3.3))
        self.assertEqual({o["id"] for o in database.get_user_options(1)}, {o["id"] for o in legs}, "legs keep their ids")
        with self.assertRaisesRegex(ValueError, "every leg"):
            database.update_user_spread(1, opened["spread_id"], edited[:1] + [dict(edited[1], id=None)], 1)
        short = next(o for o in database.get_user_options(1) if o["position"] == "short")
        database.close_user_option(1, "QQQ", "call", short["strike"], EXPIRY, 1.0, 2, "short", option_id=short["id"])
        options = database.get_user_options(1)
        self.assertEqual(spreads.broken_legs(options), {options[0]["id"]: "Bull call"})
        with self.assertRaisesRegex(LookupError, "closed or changed"):
            database.close_user_spread(1, opened["spread_id"], {options[0]["id"]: 1}, 1)
        database.add_user_option(1, "QQQ", "call", 420, EXPIRY, 1.0, 2, "short")
        [suggestion] = spreads.suggest_links(database.get_user_options(1))
        self.assertEqual((suggestion["kind"], suggestion["strikes"]), ("bull_call", "$405/$420"))
        linked = database.link_user_options(1, suggestion["option_ids"])
        self.assertEqual(spreads.group_open(database.get_user_options(1)).keys(), {linked["spread_id"]})
        with self.assertRaisesRegex(ValueError, "already belongs"):
            database.link_user_options(1, suggestion["option_ids"])
        self.assertEqual(database.unlink_user_spread(1, linked["spread_id"])["unlinked"], 2)
        self.assertEqual(spreads.group_open(database.get_user_options(1)), {})
        self.assertEqual(spreads.broken_legs(database.get_user_options(1)), {})

    def test_suggestions_find_condors_and_calendars(self):
        for o in CONDOR:
            database.add_user_option(1, "SPY", o["option_type"], o["strike"], EXPIRY, o["premium"], 1, o["position"])
        database.add_user_option(1, "AAPL", "call", 200, EXPIRY, 2, 1, "short")
        database.add_user_option(1, "AAPL", "call", 200, LATER, 4, 1, "long")
        kinds = sorted(s["kind"] for s in spreads.suggest_links(database.get_user_options(1)))
        self.assertEqual(kinds, ["call_calendar", "iron_condor"])

    def test_api_open_summary_close_edit_link(self):
        main, client = self.client()
        with self.as_user(main):
            bad = {"ticker": "SPY", "kind": "bull_put", "contracts": 1, "legs": vertical("bear_put", 95, 100, 1, 2.5)}
            self.assertEqual(client.post("/api/portfolio/spreads", json=bad).status_code, 400)
            body = {"ticker": "SPY", "kind": "bear_call", "contracts": 1, "legs": vertical("bear_call", 100, 105, 2.0, 1.0)}
            spread_id = client.post("/api/portfolio/spreads", json=body).json()["spread_id"]
            with patch.object(main, "get_key_metrics", return_value={"price": 101}), \
                 patch.object(main.options_analytics, "_expirations", return_value=[EXPIRY]), \
                 patch.object(main.options_analytics, "_chain", return_value=(self.chain({100: 2.0, 105: 0.4}), self.chain({}))):
                summary = client.get("/api/portfolio/options/summary").json()
            [row] = summary["spreads"]
            self.assertEqual((row["label"], row["strikes"], row["net_open"], row["net_mark"], row["pnl"], row["zone"]),
                             ("Bear call", "$100/$105", 1.0, 1.6, -60.0, "between"))
            self.assertEqual(summary["link_suggestions"], [])
            ids = {leg["position"]: leg["id"] for leg in row["legs"]}
            self.assertEqual(client.post(f"/api/portfolio/spreads/{spread_id}/close",
                                         json={"prices": [{"id": ids["long"], "premium": 0.1}, {"id": 999999, "premium": 0.1}],
                                               "contracts": 1}).status_code, 400)
            edit = dict(body, legs=[dict(l, id=ids[l["position"]], premium=l["premium"] + 0.1) for l in body["legs"]])
            self.assertEqual(client.put(f"/api/portfolio/spreads/{spread_id}", json=edit).json()["net_open"], 1.0)
            closed = client.post(f"/api/portfolio/spreads/{spread_id}/close",
                                 json={"prices": [{"id": ids["long"], "premium": 0.1}, {"id": ids["short"], "premium": 0.3}], "contracts": 1})
            self.assertEqual(closed.json()["pnl"], 80.0)
            [trade] = client.get("/api/portfolio/options/closed").json()["trades"]
            self.assertEqual(trade["spread"]["strikes"], "$100/$105")
            a = client.post("/api/portfolio/options/buy", json={"ticker": "SPY", "option_type": "put", "strike": 90, "expiry": EXPIRY,
                                                                "premium": 1, "contracts": 1, "position": "long"}).json()
            b = client.post("/api/portfolio/options/buy", json={"ticker": "SPY", "option_type": "put", "strike": 95, "expiry": EXPIRY,
                                                                "premium": 2, "contracts": 1, "position": "short"}).json()
            linked = client.post("/api/portfolio/spreads/link", json={"option_ids": [a["id"], b["id"]]}).json()
            self.assertEqual(linked["kind"], "bull_put")
            self.assertEqual(client.post(f"/api/portfolio/spreads/{linked['spread_id']}/unlink").json()["unlinked"], 2)
            self.assertEqual(client.post("/api/portfolio/spreads/nope/unlink").status_code, 404)

    @staticmethod
    def chain(mids):
        import pandas as pd
        return pd.DataFrame([{"strike": strike, "bid": mid - 0.05, "ask": mid + 0.05, "lastPrice": mid,
                              "impliedVolatility": 0.3, "volume": 5, "openInterest": 50} for strike, mid in mids.items()],
                            columns=["strike", "bid", "ask", "lastPrice", "impliedVolatility", "volume", "openInterest"])

    def test_expire_settles_expired_legs_only(self):
        import pandas as pd
        main, client = self.client()
        past, future = "2026-01-16", "2099-01-15"
        with patch("database._option_values"):
            vertical_id = database.add_user_spread(1, "SPY", vertical("bull_put", 95, 100, 1.0, 2.5, past), 1)["spread_id"]
            calendar_id = database.add_user_spread(1, "SPY", [leg("short", "call", 100, 2.0, past), leg("long", "call", 100, 4.5, future)], 1)["spread_id"]
        closes = pd.DataFrame({"Close": [98.0, 120.0]}, index=pd.to_datetime([past, "2026-02-02"]))
        with self.as_user(main), patch("stock_data.get_stock_data", return_value=closes):
            result = client.post(f"/api/portfolio/spreads/{vertical_id}/expire").json()
            self.assertEqual((result["settle_price"], result["pnl"], result["remaining_legs"]), (98.0, -50.0, 0))
            calendar = client.post(f"/api/portfolio/spreads/{calendar_id}/expire").json()
        self.assertEqual((calendar["pnl"], calendar["remaining_legs"]), (200.0, 1))
        [left] = database.get_user_options(1)
        self.assertEqual((left["position"], left["expiry"]), ("long", future))
        self.assertEqual(spreads.broken_legs([left]), {left["id"]: "Call calendar"})

    def test_journal_structure_record_edit_and_delete(self):
        main, client = self.client()
        body = {"ticker": "nvda", "kind": "iron_condor", "contracts": 2, "opened_at": "2026-03-01", "closed_at": "2026-03-10",
                "fees": 5.2, "notes": "Range day", "idempotency_key": "condor-entry-01",
                "legs": [dict(position=o["position"], option_type=o["option_type"], strike=o["strike"], expiry="2026-03-20",
                              open_premium=o["premium"], close_premium=o["premium"] / 4) for o in CONDOR]}
        with self.as_user(main):
            first = client.post("/api/portfolio/options/closed/spread", json=body)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["pnl"], 300.0)  # $2 credit, closed for $0.50, 2 condors
            self.assertEqual(client.post("/api/portfolio/options/closed/spread", json=body).json()["spread_id"], first.json()["spread_id"])
            self.assertEqual(client.post("/api/portfolio/options/closed/spread", json=dict(body, fees=3)).status_code, 409)
            [trade] = client.get("/api/portfolio/options/closed").json()["trades"]
            self.assertEqual((trade["position"], trade["fees"], trade["net_pnl"], trade["notes"], trade["is_manual"]),
                             ("short", 5.2, 294.8, "Range day", True))
            edit = dict(body, idempotency_key="condor-edit-001", fees=4.0,
                        legs=[dict(l, id=spread_leg["id"], close_premium=0) for l, spread_leg in zip(body["legs"], trade["spread"]["legs"])])
            self.assertEqual(client.put(f"/api/portfolio/options/closed/spread/{trade['id']}", json=edit).json()["pnl"], 400.0)
            [trade] = client.get("/api/portfolio/options/closed").json()["trades"]
            self.assertEqual((trade["pnl"], trade["fees"]), (400.0, 4.0))
            self.assertEqual(client.put("/api/portfolio/options/closed/spread/999999", json=edit).status_code, 404)
            self.assertEqual(client.delete(f"/api/portfolio/options/closed/spread/{trade['id']}").json(), {"ok": True})
            self.assertEqual(database.get_closed_options(1), [])

    def test_deleting_one_partial_close_keeps_the_others(self):
        main, client = self.client()
        spread_id = database.add_user_spread(1, "SPY", vertical("bull_put", 95, 100, 1.0, 2.5), 2)["spread_id"]
        ids = {o["position"]: o["id"] for o in database.get_user_options(1)}
        database.close_user_spread(1, spread_id, {ids["long"]: 0.2, ids["short"]: 0.7}, 1)
        database.close_user_spread(1, spread_id, {ids["long"]: 0.1, ids["short"]: 0.4}, 1)
        with self.as_user(main):
            first, second = client.get("/api/portfolio/options/closed").json()["trades"]
            self.assertEqual(client.delete(f"/api/portfolio/options/closed/spread/{first['id']}").status_code, 200)
            [left] = client.get("/api/portfolio/options/closed").json()["trades"]
            self.assertEqual((left["id"], left["pnl"]), (second["id"], second["pnl"]))

    def test_collateral_per_structure(self):
        import accounts
        database.add_user_option(1, "AAPL", "put", 200, EXPIRY, 3.0, 1, "short")
        database.add_user_spread(1, "MSFT", vertical("bull_put", 390, 400, 1.0, 3.0), 2)
        database.add_user_spread(1, "TSLA", vertical("bear_call", 250, 260, 3.0, 1.0), 1)
        database.add_user_spread(1, "NVDA", vertical("bear_put", 490, 500, 7.0, 12.0), 1)
        database.add_user_spread(1, "SPY", CONDOR, 1)
        account = accounts.list_accounts(1)["accounts"][0]
        self.assertEqual(account["put_collateral"], 20000 + 2000 + 1000 + 0 + 500)

    def test_expiry_ladder_cash(self):
        import expiry_ladder
        bear = database.add_user_spread(1, "NVDA", vertical("bear_put", 490, 500, 7.0, 12.0), 1)
        bull = database.add_user_spread(1, "MSFT", vertical("bull_put", 390, 400, 1.0, 3.0), 1)
        condor = database.add_user_spread(1, "SPY", CONDOR, 1)
        shorts = {o["ticker"]: o["id"] for o in database.get_user_options(1) if o["position"] == "short" and o["option_type"] == "put"}
        with patch.object(expiry_ladder, "_spot", side_effect=lambda t, cache: {"NVDA": 480.0, "MSFT": 380.0, "SPY": 100.0}[t]), \
             patch.object(expiry_ladder.accounts, "list_accounts", return_value={"accounts": []}):
            [group] = expiry_ladder.build(1, {"positions": []})["expiries"]
        rows = {row["id"]: row for row in group["positions"]}
        self.assertEqual(rows[shorts["NVDA"]]["cash_if_assigned"], 0)
        self.assertEqual(rows[shorts["MSFT"]]["cash_if_assigned"], 1000, "both puts in the money: net is the width")
        self.assertEqual(rows[shorts["SPY"]]["cash_if_assigned"], 9500, "only the short put in the money: full strike")
        self.assertEqual(group["cash_if_all_puts_assigned"], 1000 + 500)
        self.assertIn("iron condor", rows[shorts["SPY"]]["spread_note"])
        self.assertTrue(bear and bull and condor)

    def test_rules_use_net_value_and_cover_short_calls(self):
        import options_desk
        legs = [dict(id=1, ticker="TSLA", option_type="call", position="short", strike=250, expiry=EXPIRY, premium=3.0,
                     contracts=1, account=None, spread_id="s1", spread_ratio=1, spread_legs=2, date_added="2026-01-01"),
                dict(id=2, ticker="TSLA", option_type="call", position="long", strike=260, expiry=EXPIRY, premium=1.0,
                     contracts=1, account=None, spread_id="s1", spread_ratio=1, spread_legs=2, date_added="2026-01-01"),
                dict(id=3, ticker="TSLA", option_type="put", position="short", strike=200, expiry=EXPIRY, premium=2.0,
                     contracts=1, account=None, spread_id="gone", spread_ratio=1, spread_legs=2, spread_kind="bull_put",
                     date_added="2026-01-01")]
        mids = {250: 8.5, 260: 2.5, 200: 1.0}
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
        codes = [a["code"] for a in by_id[1]["actions"]]
        self.assertNotIn("naked", codes)
        self.assertIn("stop_loss", codes)
        self.assertEqual((by_id[1]["loss_multiple"], by_id[1]["spread"]["role"], by_id[2]["spread"]["role"]), (2.0, "main", "hedge"))
        self.assertFalse(any(a.get("repair") for a in by_id[1]["actions"]))
        self.assertIn("spread_broken", [a["code"] for a in by_id[3]["actions"]])

    def test_covered_call_ideas_ignore_spread_short_calls(self):
        import next_steps
        holdings = [{"ticker": "TSLA", "shares": 100, "buy_price": 200, "account": None}]
        options = [dict(id=1, ticker="TSLA", option_type="call", position="short", strike=250, expiry=EXPIRY, contracts=1,
                        account=None, spread_id="s1", premium=3),
                   dict(id=2, ticker="TSLA", option_type="call", position="long", strike=260, expiry=EXPIRY, contracts=1,
                        account=None, spread_id="s1", premium=1)]
        self.assertEqual(len(next_steps._covered_call_items(holdings, options)), 1)
        self.assertEqual(next_steps._covered_call_items(holdings, [dict(options[0], spread_id=None)]), [])


if __name__ == "__main__":
    unittest.main()
