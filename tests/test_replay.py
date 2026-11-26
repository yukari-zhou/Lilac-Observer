import concurrent.futures
from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from astra import _packet, replay_key
from paper import CN
from replay import ReplayBook
from trading_costs import execution

SYMBOL = "sh688836"
THU = datetime(2026, 11, 26, 15, 10, tzinfo=CN)
FRI = THU + timedelta(days=1)
MON = FRI + timedelta(days=3)


def quote(clock, price=20.0, **overrides):
    return {**dict(id=SYMBOL, status="live", price=price, prev_close=20.0, bid=price-.01, ask=price+.01,
                   source="fixture", asof=clock.isoformat()), **overrides}


def inputs(clock, bullish=True):
    market = dict(kind="stock", id=SYMBOL, quote=quote(clock, status="latest"),
                  meta=dict(adjustment="qfq", quote_status="latest", history_status="latest"))
    model = dict(as_of=clock.date().isoformat(), horizon=5, status="ok", validation={"n":10},
                 direction="偏强" if bullish else "偏弱", base_price=20.0,
                 strategy={"trade_costs":{"base_net_pnl":3.21}})
    return market, model


def review(clock, model, posture="follow"):
    return dict(status="ready", as_of=model["as_of"], posture=posture, updated_at=clock.isoformat())


class ReplayTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name, "replay.sqlite")
        self.book = ReplayBook(self.path)

    def test_concurrent_freeze_preferences_and_quote_survive_restart(self):
        market, model = inputs(THU)
        self.assertFalse(self.book.auto_ai())
        self.assertTrue(self.book.set_auto_ai(True))
        with self.assertRaises(ValueError):
            self.book.set_auto_ai("false")
        def freeze(_):
            return self.book.capture(SYMBOL, market, model, model, "key", now=THU)
        with concurrent.futures.ThreadPoolExecutor(6) as pool:
            self.assertEqual(list(pool.map(freeze, range(12))).count(True), 1)
        restarted = ReplayBook(self.path)
        self.assertTrue(restarted.auto_ai())
        self.assertFalse(restarted.needs_capture(SYMBOL, THU.date()))
        self.assertEqual(restarted.pending_symbols(FRI.date()), {SYMBOL})
        before = restarted.report(SYMBOL, now=THU)
        self.assertEqual((before["signals"], before["pending"], before["missed"]), (1, 1, 0))
        self.assertIsNone(before["paired"]["rows"][0]["net_return"])
        session = FRI.replace(hour=10)
        for invalid in [quote(THU), quote(session, status="cached"), quote(session, id="sz000001")]:
            self.assertFalse(restarted.observe(SYMBOL, invalid, now=session))
        self.assertTrue(restarted.observe(SYMBOL, quote(session), now=session))
        self.assertFalse(restarted.observe(SYMBOL, quote(session, price=79), now=session))
        self.assertFalse(restarted.pending_symbols(FRI.date()))
        report = self.book.report(SYMBOL, now=session)
        self.assertEqual(report["paired"]["recent"][0]["price"], 20)
        self.assertEqual(report["paired"]["samples"], 1)
        self.assertEqual(report["common"]["samples"], 0)
        self.assertLess(report["paired"]["rows"][0]["net_return"], 0)

    def test_public_frozen_review_can_be_claimed_once_across_restarts(self):
        market, model = inputs(FRI)
        index = {"id": SYMBOL, "kind": "stock"}
        _, packet = _packet(index, market, model)
        key = replay_key(packet)
        self.assertFalse(self.book.capture(SYMBOL, market, model, model, key, FRI, {**packet, "paper_position": {}}))
        self.assertFalse(self.book.capture(SYMBOL, market, model, model, "changed", FRI, packet))
        self.assertTrue(self.book.capture(SYMBOL, market, model, model, key, FRI, packet))
        # Mutating a caller's structures cannot change the next recovery's inputs.
        packet["lang"] = "en"
        recovered = ReplayBook(self.path)
        weekend = FRI + timedelta(days=1)
        cutoff = MON.replace(hour=9, minute=15)
        self.assertEqual(recovered.pending_reviews(weekend)[SYMBOL]["lang"], "zh")
        self.assertIn(SYMBOL, recovered.pending_reviews(cutoff - timedelta(seconds=1)))
        self.assertEqual(recovered.pending_reviews(cutoff), {})
        self.assertFalse(recovered.claim_review(SYMBOL, model["as_of"], "wrong", weekend))
        self.assertFalse(recovered.claim_review(SYMBOL, model["as_of"], key, cutoff))
        with concurrent.futures.ThreadPoolExecutor(5) as pool:
            claims = list(pool.map(lambda _: recovered.claim_review(SYMBOL, model["as_of"], key, weekend), range(10)))
        self.assertEqual(claims.count(True), 1)
        self.assertFalse(ReplayBook(self.path).pending_reviews(weekend))
        self.assertTrue(recovered.attach_review(SYMBOL, model["as_of"], key, review(weekend, model), weekend))

    def test_migration_preserves_old_signals_without_manufacturing_model_input(self):
        old_path = self.path.with_name("old.sqlite")
        with closing(sqlite3.connect(old_path)) as db, db:
            db.execute("""CREATE TABLE replay_v1 (
                symbol TEXT, origin TEXT, captured TEXT, trade_day TEXT, price_signal TEXT, evidence_signal TEXT,
                review_key TEXT, posture TEXT, reviewed_at TEXT, quote TEXT, PRIMARY KEY(symbol,origin),
                UNIQUE(symbol,trade_day))""")
            db.execute("INSERT INTO replay_v1 VALUES(?,?,?,?,'{}','{}','old',NULL,NULL,NULL)",
                       (SYMBOL, THU.date().isoformat(), THU.isoformat(), FRI.date().isoformat()))
        book = ReplayBook(old_path)
        self.assertFalse(book.needs_capture(SYMBOL, THU.date()))
        self.assertEqual(book.pending_symbols(FRI.date()), {SYMBOL})
        self.assertEqual(book.pending_reviews(THU), {})
        market, model = inputs(FRI)
        _, packet = _packet({"id":SYMBOL, "kind":"stock"}, market, model)
        key = replay_key(packet)
        self.assertTrue(book.capture(SYMBOL, market, model, model, key, FRI, packet))
        self.assertTrue(book.attach_review(SYMBOL, model["as_of"], key, review(FRI, model), FRI))
        self.assertFalse(book.claim_review(SYMBOL, model["as_of"], key, FRI))
        self.assertEqual(book.pending_reviews(FRI), {})

    def test_common_dates_ai_filter_and_costs(self):
        market, long = inputs(THU)
        self.assertTrue(self.book.capture(SYMBOL, market, long, long, "thu-key", now=THU))
        self.assertFalse(self.book.attach_review(SYMBOL, long["as_of"], "other", review(THU, long), now=THU))
        self.assertTrue(self.book.attach_review(SYMBOL, long["as_of"], "thu-key", review(THU, long), now=THU))
        self.assertFalse(self.book.attach_review(SYMBOL, long["as_of"], "thu-key", review(THU, long, "wait"), now=THU))
        first = FRI.replace(hour=10)
        self.assertTrue(self.book.observe(SYMBOL, quote(first, 20), now=first))
        market, flat = inputs(FRI, bullish=False)
        _, long = inputs(FRI, bullish=True)
        self.assertTrue(self.book.capture(SYMBOL, market, flat, long, "fri", now=FRI))
        self.assertTrue(self.book.attach_review(SYMBOL, flat["as_of"], "fri", review(FRI, flat, "defensive"), now=FRI))
        last = MON.replace(hour=9, minute=41)
        self.assertTrue(self.book.observe(SYMBOL, quote(last, price=22), now=last))
        result = self.book.report(SYMBOL, now=last)["common"]
        rows = {r["key"]:r for r in result["rows"]}
        self.assertEqual(result["samples"], 2)
        self.assertEqual((rows["price"]["trades"], rows["hold"]["trades"], rows["ai"]["trades"]), (2, 1, 2))
        self.assertEqual(rows["ai"]["net_return"], rows["price"]["net_return"])
        self.assertEqual(rows["evidence"]["net_return"], rows["hold"]["net_return"])
        self.assertEqual(result["recent"][0]["actions"]["ai"], "sell")
        buy_quote = Decimal("20.01")
        shares = int(Decimal(1_000_000) // buy_quote)
        while -execution("buy", buy_quote, shares)["cash_delta"] > 1_000_000:
            shares -= 1
        buy = execution("buy", buy_quote, shares)
        sell = execution("sell", Decimal("21.99"), shares)
        self.assertAlmostEqual(rows["ai"]["fees"], float(buy["fees"] + sell["fees"]))
        self.assertAlmostEqual(rows["ai"]["net_return"], float((buy["cash_delta"] + sell["cash_delta"]) / 1_000_000))

    def test_missed_day_and_late_ai_do_not_fabricate_observations(self):
        market, long = inputs(THU)
        self.assertFalse(self.book.capture(SYMBOL, market, long, long, "key", now=THU.replace(hour=11)))
        self.assertFalse(self.book.capture(SYMBOL, market, long, long, "key", now=FRI))
        self.assertTrue(self.book.capture(SYMBOL, market, long, long, "key", now=THU))
        at_open = FRI.replace(hour=9, minute=15)
        self.assertFalse(self.book.attach_review(SYMBOL, long["as_of"], "key", review(THU, long), now=at_open))
        later = MON.replace(hour=10)
        self.assertFalse(self.book.observe(SYMBOL, quote(later), now=later))
        report = self.book.report(SYMBOL, now=later)
        self.assertEqual((report["missed"], report["pending"], report["paired"]["samples"]), (1, 0, 0))

    def test_empty_ask_and_insufficient_lot_are_unfilled(self):
        for isolated, data in [("limit", {"ask":None}), ("expensive", {"price":8000.0, "ask":8000.0})]:
            with self.subTest(isolated=isolated):
                book = ReplayBook(self.path.with_name(isolated+".sqlite"))
                market, long = inputs(THU)
                self.assertTrue(book.capture(SYMBOL, market, long, long, None, now=THU))
                session = FRI.replace(hour=10)
                self.assertTrue(book.observe(SYMBOL, quote(session, **data), now=session))
                row = book.report(SYMBOL, now=session)["paired"]["rows"][0]
                self.assertEqual((row["trades"], row["unfilled"], row["net_return"]), (0, 1, 0.0))

    def test_basis_change_missing_reference_or_gap_starts_fresh_period(self):
        for origin, reference, reason in [(FRI, 10, "price_basis_changed"), (FRI, None, "missing_reference"),
                                          (MON, 20, "observation_gap")]:
            with self.subTest(reason=reason):
                book = ReplayBook(self.path.with_name(reason+".sqlite"))
                market, model = inputs(THU)
                book.capture(SYMBOL, market, model, model, "first", now=THU)
                book.attach_review(SYMBOL, model["as_of"], "first", review(THU, model), now=THU)
                first = FRI.replace(hour=10)
                book.observe(SYMBOL, quote(first), now=first)
                market, model = inputs(origin)
                book.capture(SYMBOL, market, model, model, now=origin)
                later = (MON if origin == FRI else MON + timedelta(days=1)).replace(hour=10)
                book.observe(SYMBOL, quote(later, price=10, prev_close=reference), now=later)
                after = ReplayBook(book.path).report(SYMBOL, now=later)
                self.assertEqual((after["earlier_samples"], after["restart_reason"], after["signals"]), (1, reason, 2))
                self.assertEqual(after["segment_start"], later.date().isoformat())
                self.assertEqual((after["common"]["samples"], after["paired"]["samples"]), (0, 1))
                row = after["paired"]["rows"][0]
                self.assertEqual(row["trades"], 1)
                self.assertGreater(row["net_return"], -.01)

    def test_missing_ai_day_marks_drawdown_without_trading(self):
        tue = MON + timedelta(days=1)
        for origin, day, price, has_review in [(THU, FRI, 20, True), (FRI, MON, 15, False), (MON, tue, 20, True)]:
            market, model = inputs(origin, bullish=has_review)
            self.book.capture(SYMBOL, market, model, model, "review", now=origin)
            if has_review:
                self.book.attach_review(SYMBOL, model["as_of"], "review", review(origin, model), now=origin)
            at = day.replace(hour=10)
            self.book.observe(SYMBOL, quote(at, price), now=at)
        report = self.book.report(SYMBOL, now=tue)
        self.assertEqual((report["earlier_samples"], report["restart_reason"]), (0, None))
        self.assertEqual((report["common"]["samples"], report["paired"]["samples"]), (2, 3))
        for row in report["common"]["rows"]:
            self.assertEqual(row["trades"], 1)
            self.assertGreater(row["max_drawdown"], .24)
            self.assertGreater(row["net_return"], -.01)


if __name__ == "__main__":
    unittest.main()
