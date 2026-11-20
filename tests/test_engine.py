import json
from datetime import date, timedelta
from math import sin
import random
import unittest

from engine import analyze, eligible_evidence


def fixture(count):
    today = date(2024, 1, 1)
    close = 3500
    rng = random.Random(17)
    bars = []
    for i in range(count):
        while today.weekday() >= 5:
            today += timedelta(days=1)
        start = close
        close *= 1 + .0006 * sin(i / 15) + rng.gauss(0, .009)
        bars.append(dict(date=today.isoformat(), open=start, close=close,
                         low=min(start, close) * .998, high=max(start, close) * 1.003,
                         volume=rng.randint(50, 210)))
        today += timedelta(days=1)
    return {"id": "sh000300", "bars": bars, "evidence": [],
            "meta": {"evaluated_at": bars[-1]["date"] + "T19:00:00+08:00"}}


class EngineTest(unittest.TestCase):
    def test_insufficient_and_horizon(self):
        market = fixture(59)
        a = analyze(market, 5)
        self.assertEqual(a["status"], "insufficient")
        self.assertIsNone(a["strategy"]["stop"])
        with self.assertRaises(ValueError):
            analyze(market, 2)

    def test_missing_and_unfinished_bars(self):
        market = fixture(61)
        previous = market["bars"][-2]["date"]
        market["meta"]["evaluated_at"] = market["bars"][-1]["date"] + "T11:00:00+08:00"
        market["bars"].append(dict(date=previous, open=1, close=float("nan"), high=4, low=2))
        result = analyze(market, 1)
        self.assertEqual(result["as_of"], previous)
        self.assertEqual(result["status"], "ok")
        json.dumps(result, allow_nan=False)

    def test_evidence_cutoff_relevance_and_validation(self):
        market = fixture(240)
        clean = analyze(market, 5)
        signal = dict(title="样本盈利修订", source="披露测试", published_at=market["bars"][-1]["date"]+"T16:00:00+08:00",
                      kind="fundamental", scope="sh000300", index_id="sh000300", confidence=.8, coverage=.4, signal=1)
        market["evidence"] = [dict(signal, published_at="2099-01-01"), dict(signal, published_at="2000-01-01"),
                              dict(signal, index_id="sz399006", scope="sz399006")]
        self.assertEqual(analyze(market, 5), clean)
        market["evidence"] += [signal, signal]
        revised = analyze(market, 5)
        self.assertGreater(revised["interval"]["base"], clean["interval"]["base"])
        self.assertEqual(clean["validation"], revised["validation"])
        self.assertEqual(revised["evidence_groups"], 1)
        self.assertIn("1 条", revised["factors"][-1]["detail"])
        self.assertAlmostEqual(sum(f["weight"] for f in revised["factors"]), 1)
        market["meta"]["evaluated_at"] = "2029-07-03T17:00:00+08:00"
        archival = analyze(market, 5)
        self.assertEqual(archival["evidence_groups"], 0)
        self.assertEqual(archival["strategy"]["action"], "历史复盘")

    def test_last_walkforward_error_matches_a_real_prior_forecast(self):
        market = fixture(270)
        for horizon in (1, 5, 20):
            prefix = fixture(270-horizon)
            before = analyze(prefix, horizon)
            after = analyze(market, horizon)
            self.assertEqual(after["horizon"], horizon)
            self.assertLess(after["strategy"]["stop"], after["base_price"])
            self.assertLessEqual(after["interval"]["low"], after["interval"]["base"])
            self.assertLessEqual(after["interval"]["base"], after["interval"]["high"])
            n = before["validation"]["n"]
            if not n:  # A 20-day test has fewer than twelve mature windows here.
                self.assertEqual(after["validation"]["n"], 0)
                continue
            self.assertEqual(after["validation"]["n"], n+1)
            v = market["bars"][-1]["close"] / prefix["bars"][-1]["close"] - 1
            error = abs(v - before["interval"]["return_base"])
            combined = (before["validation"]["mae"] * n + error) / (n + 1)
            self.assertAlmostEqual(after["validation"]["mae"], combined)
            outcome = before["interval"]["return_low"] <= v <= before["interval"]["return_high"]
            coverage = (before["validation"]["coverage"] * n + outcome) / (n+1)
            self.assertAlmostEqual(after["validation"]["coverage"], coverage)

    def test_intraday_anchor_and_stale_protection(self):
        market = fixture(180)
        bar = market["bars"][-1]
        tomorrow = (date.fromisoformat(bar["date"]) + timedelta(days=1)).isoformat()
        clock = tomorrow + "T10:00:00+08:00"
        market["meta"].update(evaluated_at=clock, quote_status="live", history_status="cached")
        market["quote"] = {"asof": clock, "prev_close": bar["close"]}
        self.assertFalse(analyze(market, 5)["historical"])
        for state in ("delayed", "snapshot", "cached", "unavailable"):
            market["meta"]["quote_status"] = state
            result = analyze(market, 5)
            self.assertTrue(result["historical"])
            self.assertEqual(result["strategy"]["action"], "历史复盘")
        market["meta"]["quote_status"] = "live"
        market["quote"]["prev_close"] += 5
        self.assertTrue(analyze(market, 5)["historical"])
        market["quote"]["prev_close"] = bar["close"]
        close = tomorrow + "T15:01:00+08:00"
        market["meta"]["evaluated_at"] = market["quote"]["asof"] = close
        self.assertTrue(analyze(market, 5)["historical"])

    def test_archived_evidence_requires_known_vintage(self):
        cutoff = "2026-11-12T15:00:00+08:00"
        item = {"kind": "fundamental", "scope": "index", "source": "披露测试", "title": "业绩摘要",
                "published_at": "2026-11-02T12:00:00+08:00", "fetched_at": "2026-11-20T14:00:00+08:00"}
        self.assertFalse(eligible_evidence(item, cutoff, historical=True))
        self.assertTrue(eligible_evidence(dict(item, fetched_at=cutoff), cutoff, historical=True))
        del item["fetched_at"]
        self.assertFalse(eligible_evidence(item, cutoff, historical=True))
        news = dict(item, kind="news", published_at=cutoff)
        self.assertTrue(eligible_evidence(news, cutoff, historical=True))
        news["fetched_at"] = "2026-11-13T15:00:00+08:00"
        self.assertFalse(eligible_evidence(news, cutoff, historical=True))


if __name__ == "__main__":
    unittest.main()
