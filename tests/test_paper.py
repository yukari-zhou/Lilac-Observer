from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from paper import CN, PaperBook
from trading_costs import execution


FIRST = datetime(2026, 11, 19, 10, 0, tzinfo=CN)
NEXT = FIRST + timedelta(days=1)
STOCK = "sh600519"


def quote(price, when=FIRST, symbol=STOCK):
    return dict(id=symbol, price=price, asof=when.isoformat(), source="合成行情", status="live")


class PaperAccount(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name, "paper.sqlite")
        self.book = PaperBook(self.path)

    def buy(self, key, quantity, price, now=FIRST, symbol=STOCK):
        return self.book.trade(symbol, "样本", "buy", quantity, quote(price, now, symbol), key, now=now)

    def sell(self, key, quantity, price, now=NEXT, symbol=STOCK):
        return self.book.trade(symbol, "样本", "sell", quantity, quote(price, now, symbol), key, now=now)

    def test_weighted_cost_partial_close_and_persistence(self):
        o1 = self.buy("first", 200, 10.09)
        o2 = self.buy("second", 100, 24.51)
        with self.assertRaisesRegex(ValueError, "可卖"):
            self.sell("too_early", 100, 30, now=FIRST)
        start = self.book.snapshot(as_of=FIRST)
        self.assertEqual(start["positions"][0]["sellable"], 0)
        basis = -(Decimal(str(o1["cash_delta"])) + Decimal(str(o2["cash_delta"])))
        self.assertEqual(start["initial_cash"], 1_000_000)
        self.assertEqual(start["positions"][0]["cost_basis"], float(basis))
        self.buy("third", 100, 25.45, now=NEXT)
        quotes = {STOCK: quote(26, NEXT)}
        before = self.book.snapshot(quotes, as_of=NEXT)
        self.assertEqual(before["positions"][0]["sellable"], 300)
        self.assertEqual(before["positions"][0]["valuation_source"], "quote")
        self.assertEqual(before["net_liquidation_equity"],
                         float(Decimal(str(before["cash"])) + execution("sell", 26, 400)["cash_delta"]))
        preview = self.book.preview(STOCK, "sell", 100, quotes[STOCK], now=NEXT)
        self.assertEqual(before, self.book.snapshot(quotes, as_of=NEXT))
        partial = self.sell("sell_100", 100, 26)
        self.assertEqual(preview, {k: partial[k] for k in preview})
        after = self.book.snapshot(quotes, as_of=NEXT)
        self.assertEqual(after["positions"][0]["sellable"], 200)
        self.assertEqual(after["realized_pnl"], partial["realized_pnl"])
        self.assertAlmostEqual(after["total_pnl"], after["unrealized_pnl"] + after["realized_pnl"], places=8)
        self.assertEqual(after, PaperBook(self.path).snapshot(quotes, as_of=NEXT))
        self.sell("sell_200", 200, 26)
        self.sell("sell_remaining", 100, 30, now=NEXT + timedelta(days=3))
        closed = self.book.snapshot()
        self.assertEqual(closed["positions"], [])
        self.assertEqual(closed["net_liquidation_equity"], closed["cash"])
        self.assertEqual(closed["realized_pnl"], closed["total_pnl"])
        self.assertEqual(len(closed["history"]), 6)

    def test_previews_can_use_old_marks_and_execution_rejects_bad_inputs(self):
        mark = quote(10)
        preview = self.book.preview(STOCK, "buy", 100, mark, now=NEXT)
        self.assertEqual(preview["quote_asof"], FIRST.isoformat())
        for bad in (mark, {**quote(10, NEXT), "id": "sz000001"}, quote(float("nan"), NEXT),
                    {**quote(10, NEXT), "suspended": True}, quote(-1, NEXT), quote(10, NEXT + timedelta(hours=1))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.book.trade(STOCK, "样本", "buy", 100, bad, "bad", now=NEXT)
        for quantity in (True, -100, "100", 1000.0, 99, 101, 1_000_001):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                self.buy("bad", quantity, 10)
        with self.assertRaisesRegex(ValueError, "现金不足"):
            self.buy("excess", 100, 10_000)
        self.assertEqual(self.book.symbols(), [])
        self.assertEqual(self.book.snapshot()["cash"], 1_000_000)
        self.buy("ok", 100, 20)
        for bad_mark in (None, quote(18, FIRST - timedelta(seconds=1)), quote(25, NEXT + timedelta(days=1))):
            snap = self.book.snapshot({STOCK: bad_mark}, as_of=NEXT)
            pos = snap["positions"][0]
            self.assertEqual((pos["valuation_source"], pos["price"]), ("last_trade_quote", 20))
        even = Decimal(str(pos["break_even_quote"]))
        basis = Decimal(str(pos["cost_basis"]))
        self.assertGreaterEqual(execution("sell", even, 100)["cash_delta"], basis)
        self.assertLess(execution("sell", even - Decimal(".01"), 100)["cash_delta"], basis)

    def test_lot_rules_and_odd_lot_exit(self):
        for symbol, minimum, maximum in (("sh688836", 200, 50_000), ("bj920001", 100, 1_000_000)):
            with self.subTest(symbol=symbol):
                for quantity in (minimum - 1, maximum + 1):
                    with self.assertRaises(ValueError):
                        self.buy("bad", quantity, 10, symbol=symbol)
                self.buy(symbol, minimum + 7, 10, symbol=symbol)
                self.sell(symbol + "_sell", minimum, 11, symbol=symbol)
                with self.assertRaises(ValueError):
                    self.sell("split_odd", 2, 11, symbol=symbol)
                self.sell(symbol + "_odd", 7, 11, symbol=symbol)
        self.assertFalse(self.book.symbols())

    def test_idempotent_retry_and_atomic_competing_buys(self):
        def order(_):
            return self.buy("same_key", 100, 6_000)
        with ThreadPoolExecutor(6) as pool:
            orders = list(pool.map(order, range(8)))
        self.assertTrue(all(o == orders[0] for o in orders))
        # An already-confirmed order survives quote disappearance and T+1 rollover.
        self.assertEqual(self.book.trade(STOCK, "样本", "buy", 100, None, "same_key", now=NEXT), orders[0])
        self.assertEqual(self.book.lookup("same_key", STOCK, "buy", 100), orders[0])
        with self.assertRaisesRegex(ValueError, "另一笔"):
            self.book.lookup("same_key", STOCK, "buy", 200)
        def smaller(i):
            try:
                return self.buy(f"unique_{i}", 100, 2_500)
            except ValueError:
                return None
        with ThreadPoolExecutor(6) as pool:
            self.assertEqual(sum(bool(o) for o in pool.map(smaller, range(6))), 1)
        snapshot = self.book.snapshot()
        self.assertEqual(len(snapshot["history"]), 2)
        self.assertEqual(snapshot["positions"][0]["quantity"], 200)
        self.assertGreater(snapshot["cash"], 0)

    def test_liquidation_includes_each_required_order_fee(self):
        symbol = "sh688836"
        self.buy("star_main", 50_000, 0.11, symbol=symbol)
        self.buy("star_extra", 250, 0.12, symbol=symbol)
        snapshot = self.book.snapshot({symbol: quote(0.12, NEXT, symbol)}, as_of=NEXT)
        cash = Decimal(str(snapshot["cash"]))
        position = snapshot["positions"][0]
        def net(price):
            return sum(execution("sell", price, qty)["cash_delta"] for qty in (50_000, 250))
        self.assertEqual(snapshot["net_liquidation_equity"], float(cash + net(0.12)))
        basis = Decimal(str(position["cost_basis"]))
        even = Decimal(str(position["break_even_quote"]))
        self.assertGreaterEqual(net(even), basis)
        self.assertLess(net(even - Decimal(".01")), basis)
