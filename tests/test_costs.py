from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

from astra import Reviewer, _packet, _prompt
from engine import analyze
from tests.test_engine import fixture
from tests.test_stock_model import stock_sample
from trading_costs import CENT, break_even_quote, execution, liquidation_proceeds


class Costs(unittest.TestCase):
    def test_round_trip_adverse_fill_and_tax(self):
        buy = execution("buy", 20, 100)
        sell = execution("sell", 20, 100)
        self.assertEqual((buy["fill_price"], sell["fill_price"]), (Decimal("20.01"), Decimal("19.99")))
        self.assertEqual(buy["stamp_tax"], 0)
        self.assertEqual(sell["stamp_tax"], Decimal("1.00"))
        self.assertEqual(buy["cash_delta"], Decimal("-2006.02"))
        self.assertEqual(sell["cash_delta"], Decimal("1992.98"))
        self.assertEqual(execution("buy", 300, 100)["commission"], Decimal("7.50"))
        self.assertEqual(execution("sell", ".01", 1)["fill_price"], CENT)
        for side, quote, size in [("short", 20, 100), ("buy", 0, 5), ("buy", "NaN", 5), ("sell", 20, True)]:
            with self.subTest(side=side, quote=quote, size=size), self.assertRaises(ValueError):
                execution(side, quote, size)

    def test_break_even_is_lowest_tick_covering_remaining_cost(self):
        for shares, quote, limit in [(1, ".10", 100), (100, "10.00", 100), (201, "20.13", 200), (7021, "581.11", 3000)]:
            with self.subTest(shares=shares):
                cost = -execution("buy", quote, shares)["cash_delta"]
                threshold = break_even_quote(cost, shares, limit)
                self.assertGreaterEqual(liquidation_proceeds(threshold, shares, limit), cost)
                self.assertLess(liquidation_proceeds(threshold-CENT, shares, limit), cost)
        self.assertEqual(liquidation_proceeds("1", 101, 100), execution("sell", 1, 100)["cash_delta"] +
                         execution("sell", 1, 1)["cash_delta"])

    def test_stock_forecast_net_scenarios_and_index_price_units(self):
        model = analyze(stock_sample(180), 5)
        scenarios = model["strategy"]["trade_costs"]
        n = scenarios["shares"]
        self.assertEqual(n, 200)
        cost = -execution("buy", model["base_price"], n)["cash_delta"]
        for target, name in [(model["interval"]["base"], "base_net_pnl"), (model["strategy"]["stop"], "stop_net_pnl")]:
            self.assertEqual(float(execution("sell", target, n)["cash_delta"] - cost), scenarios[name])
        self.assertNotIn("trade_costs", analyze(fixture(180), 5)["strategy"])


class PaperReview(unittest.TestCase):
    stock = {"id": "sh688836", "kind": "stock"}
    market = {"meta": {"quote_status": "latest", "history_status": "latest"}, "evidence": []}
    analysis = {"status": "ok", "as_of": "2026-11-19", "horizon": 5, "strategy": {"action": "观察"}, "validation": {"n": 15}}
    position = {"symbol": "sh688836", "quantity": 200, "sellable": 0, "quote_status": "latest"}

    def test_language_scope_and_privacy(self):
        key, packet = _packet(self.stock, self.market, self.analysis, position={**self.position, "orders": ["private data"]})
        public_key, public = _packet(self.stock, self.market, self.analysis)
        other_key, en = _packet(self.stock, self.market, self.analysis, position=self.position, lang="en")
        changed, _ = _packet(self.stock, self.market, self.analysis, position={**self.position, "sellable": 200})
        self.assertEqual(len({key, public_key, other_key, changed}), 4)
        self.assertEqual(packet["paper_position"], self.position)
        self.assertNotIn("paper_position", public)
        _, historical = _packet(self.stock, self.market, {**self.analysis, "historical": True}, position=self.position)
        self.assertNotIn("paper_position", historical)
        self.assertIn("in English", _prompt(en))

    def test_inflight_invalidation_does_not_publish_or_archive_positions(self):
        started, release = threading.Event(), threading.Event()
        public_reviews = []
        def runner(packet):
            started.set()
            release.wait(2)
            return dict(posture="follow", summary="Research", risk="Risk", refs=["M"])
        with TemporaryDirectory() as folder, patch.dict("os.environ", {"LILAC_OBSERVER_ENABLED":"1", "LILAC_OBSERVER_OFFLINE":"0"}):
            path = Path(folder, "review.sqlite")
            worker = Reviewer(path, runner=runner, on_ready=lambda *args: public_reviews.append(args))
            worker.configure({"provider": "codex"})
            worker.submit(self.stock, self.market, self.analysis, self.position, "en")
            self.assertTrue(started.wait(2))
            worker.invalidate_paper()
            release.set()
            worker.submit(self.stock, self.market, self.analysis, self.position)
            slot = (self.stock["id"], 5, "paper")
            deadline = time.monotonic()+3
            while worker.get(slot)["status"] != "ready" and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertEqual(worker.get(slot)["status"], "ready")
            self.assertIn("T+1", worker.get(slot)["decision"])
            self.assertEqual(worker.get((*slot, "en"))["status"], "insufficient")
            self.assertFalse(public_reviews)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM reviews").fetchone()[0], 0)
            db.close()
