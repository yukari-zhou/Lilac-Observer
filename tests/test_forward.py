from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from astra import _packet
from forward import ForwardBook


class ForwardTest(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.book = ForwardBook(Path(self.folder.name) / "forecasts.sqlite")
        self.packet = dict(index={"id": "sh000300"}, quote={"asof": "2026-11-19T15:01:00+08:00"},
                           quote_status="latest", history_status="latest",
                           analysis=dict(as_of="2026-11-19", base_price=100, horizon=1, direction="偏强",
                                         interval=dict(low=98, base=101, high=103)))
        self.review = dict(status="ready", updated_at="2026-11-20T09:14:00+08:00", posture="wait")
        self.bars = [{"date": "2026-11-19", "close": 100}, {"date": "2026-11-20", "close": 102}]

    def test_freezes_first_and_settles_after_horizon(self):
        self.book.record(self.packet, self.review)
        self.review["posture"] = "follow"
        self.packet["analysis"]["interval"]["base"] = 99
        self.book.record(self.packet, self.review)
        self.assertEqual(self.book.track("sh000300", 1, self.bars[:1])["pending"], 1)
        result = self.book.track("sh000300", 1, self.bars)
        self.assertEqual((result["settled"], result["hit_rate"], result["coverage"]), (1, 1, 1))
        self.assertEqual(result["recent"][0]["posture"], "wait")
        self.assertAlmostEqual(result["recent"][0]["actual_return"], .02)

    def test_no_late_or_historical_issue(self):
        self.book.record(self.packet, {**self.review, "updated_at": "2026-11-20T09:15:00+08:00"})
        self.book.record({**self.packet, "history_status": "snapshot"}, self.review)
        self.assertEqual(self.book.track("sh000300", 1, self.bars)["settled"], 0)

    def test_corporate_action_preserves_forward_return_basis(self):
        self.packet.update(index={"id": "sh688836", "kind": "stock"}, adjustment="qfq")
        self.packet["analysis"]["validation"] = {"n": 35}
        self.book.record(self.packet, self.review)
        rebased = [{"date": "2026-11-19", "close": 50}, {"date": "2026-11-20", "close": 51}]
        self.assertEqual(self.book.track("sh688836", 1, rebased, "raw")["settled"], 0)
        settled = self.book.track("sh688836", 1, rebased, "qfq")
        self.assertAlmostEqual(settled["recent"][0]["actual_return"], .02)
        self.assertEqual(settled["coverage"], 1)

    def test_old_quote_and_future_evidence_excluded_from_astra(self):
        analysis = {**self.packet["analysis"], "historical": True, "evidence_cutoff": "2026-11-18T15:00:00+08:00"}
        item = dict(title="收评", source="source", scope="market", category="news", published_at="2026-11-19T15:05:00+08:00")
        market = dict(quote=self.packet["quote"], meta={"quote_status": "latest"}, evidence=[item])
        _, packet = _packet(self.packet["index"], market, analysis)
        self.assertIsNone(packet["quote"]["asof"])
        self.assertEqual(packet["evidence"], [])
