from datetime import datetime, timedelta
import os
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch

from app import Harness
from astra import _packet, replay_key
from tests.test_stock_model import stock_sample


class ReplayIntegration(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, LILAC_OBSERVER_RUNTIME_DIR=directory.name,
                         LILAC_OBSERVER_PROVIDER="off", LILAC_OBSERVER_OFFLINE="0", LILAC_OBSERVER_ENABLED="1")
        env.start()
        self.addCleanup(env.stop)
        self.app = Harness()
        self.addCleanup(self.app.pool.shutdown)
        self.market = stock_sample(179)
        self.symbol = self.market["id"]
        self.stock = {"id": self.symbol, "kind": "stock", "name": "Fixture"}
        self.app.watchlist.update(self.symbol, self.stock)
        self.clock = datetime.fromisoformat(self.market["meta"]["evaluated_at"])
        self.price = round(self.market["bars"][-1]["close"], 2)
        self.market["bars"][-1]["close"] = self.price
        self.market["quote"] = self.quote = dict(id=self.symbol, price=self.price, status="latest",
                                                 source="fixture", asof=self.clock.replace(hour=15).isoformat())
        self.market["meta"].update(asof=self.quote["asof"], history_status="latest")
        self.market["evidence"] = [dict(index_id=self.symbol, source="Fixture", title="Quarterly report",
                                        published_at=self.clock.replace(hour=16).isoformat(), kind="fundamental",
                                        scope=self.symbol, signal=.4, report={"sector": "Fixture industry"})]
        for p in [patch("sources.now", side_effect=lambda: self.clock), patch("astra._now", side_effect=lambda: self.clock.isoformat()),
                  patch.object(self.app, "_market", return_value=self.market),
                  patch("stocks.quotes", side_effect=lambda symbols: {s: self.quote for s in symbols})]:
            p.start()
            self.addCleanup(p.stop)

    def next_quote(self):
        self.clock += timedelta(days=1)
        while self.clock.weekday() >= 5:
            self.clock += timedelta(days=1)
        self.clock = self.clock.replace(hour=10)
        self.quote = dict(id=self.symbol, price=self.price, prev_close=self.price, bid=self.price-.01, ask=self.price+.01,
                          status="live", source="fixture", asof=self.clock.isoformat())
        self.app.collect_replay()

    def test_quant_collector_and_preview_basis(self):
        self.app.reviewer.configure({"provider":"codex"})
        with patch.object(self.app.reviewer, "submit_frozen", side_effect=AssertionError("unexpected model request")):
            self.app.collect_replay()
            self.assertFalse(self.app.replay.needs_capture(self.symbol, self.clock.date()))
            self.assertEqual(self.app.replay_eligibility(self.symbol), "ready")
            context = self.app.risk_context([self.symbol], self.symbol, 5, self.quote)
            self.assertEqual(context["sectors"], {self.symbol:"Fixture industry"})
            self.assertGreater(context["stop"], 0)
            self.assertNotIn("stop", self.app.risk_context([self.symbol], self.symbol, 5, {**self.quote, "price":self.price / 2}))
            self.next_quote()
            report = self.app.replay.report(self.symbol, self.clock)
            self.assertEqual((report["paired"]["samples"], report["common"]["samples"]), (1, 0))

    def test_explicit_automation_shares_one_frozen_public_review(self):
        frozen = Event()
        self.app.reviewer.configure({"provider":"codex"})
        self.app.replay_settings({"auto_ai": True})
        runner = Mock(return_value=dict(posture="wait", summary="Review", risk="Risk", refs=["M"]))
        self.app.reviewer.runner = runner
        def ready(packet, result):
            self.app.review_completed(packet, result)
            frozen.set()
        self.app.reviewer.on_ready = ready
        self.app.collect_replay()
        self.assertTrue(frozen.wait(3))
        reviewed = self.app.research(self.symbol, 5)
        self.assertEqual(reviewed["review"]["status"], "ready")
        runner.assert_called_once()
        packet = runner.call_args.args[0]
        self.assertNotIn("paper_position", packet)
        self.assertEqual(reviewed["review"]["replay_key"], replay_key(packet))
        analysis = reviewed["analysis"]
        changed = {**analysis, "validation": {**analysis["validation"], "n":999}}
        self.assertNotEqual(replay_key(packet), replay_key(_packet(self.stock, self.market, changed)[1]))
        self.next_quote()
        self.assertEqual(self.app.replay.report(self.symbol, self.clock)["common"]["samples"], 1)

    def test_enabling_later_reuses_original_evidence_after_restart(self):
        self.app.collect_replay()
        saved = self.app.replay.pending_reviews(self.clock)[self.symbol]
        self.market["evidence"][0]["title"] = "Late revision"
        restarted = Harness()
        self.addCleanup(restarted.pool.shutdown)
        done = Event()
        restarted.reviewer.configure({"provider": "codex"})
        restarted.reviewer.runner = Mock(return_value=dict(posture="follow", summary="OK", risk="Risk", refs=["M"]))
        def completed(packet, review):
            restarted.review_completed(packet, review)
            done.set()
        restarted.reviewer.on_ready = completed
        restarted.replay_settings({"auto_ai": True})
        self.assertTrue(done.wait(3))
        restarted.reviewer.runner.assert_called_once_with(saved)
        self.assertEqual(saved["evidence"][0]["title"], "Quarterly report")
        self.assertFalse(restarted.replay.pending_reviews(self.clock))
