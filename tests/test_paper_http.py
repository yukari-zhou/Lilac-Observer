from datetime import datetime, timedelta
from http.client import HTTPConnection
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from app import Endpoint, Harness, LocalServer
import sources
from trading_costs import liquidation_proceeds


class PaperAPI(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, LILAC_OBSERVER_RUNTIME_DIR=directory.name, LILAC_OBSERVER_PROVIDER="off")
        env.start()
        self.addCleanup(env.stop)
        self.app = Harness()
        self.addCleanup(self.app.pool.shutdown)
        self.server = LocalServer(("127.0.0.1", 0), Endpoint)
        self.server.harness = self.app
        self.addCleanup(self.server.server_close)
        thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": .02})
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.stock = {"id": "sh600001", "name": "Demo", "kind": "stock"}
        self.app.watchlist.update(self.stock["id"], self.stock)
        self.now = datetime(2026, 11, 19, 10, tzinfo=sources.CN)
        self.quote = dict(price=20, bid=19.98, ask=20.02, asof=self.now.isoformat(),
                          status="live", source="fixture", id=self.stock["id"])
        timer = patch("sources.now", side_effect=lambda: self.now)
        feeds = patch("stocks.quotes", side_effect=lambda ids: {s: self.quote for s in ids})
        timer.start()
        feeds.start()
        self.addCleanup(timer.stop)
        self.addCleanup(feeds.stop)
        self.assertTrue(Path(directory.name, "paper.sqlite").is_file())

    def api(self, path, data=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request("POST" if data is not None else "GET", path, json.dumps(data) if data is not None else None,
                         {"Content-Type": "application/json", **(headers or {})})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_round_trip_and_replay_after_close(self):
        body = dict(symbol=self.stock["id"], side="buy", quantity=100)
        status, result = self.api("/api/paper/preview", body)
        self.assertEqual((status, result["can_trade"], result["preview"]["quote_price"]), (200, True, 20.02))
        buy = {**body, "request_id": "example-buy-1", "expected_price": 20.02}
        self.assertEqual(self.api("/api/paper/orders", {**buy, "expected_price": 20})[0], 400)
        status, filled = self.api("/api/paper/orders", buy)
        self.assertEqual((status, filled["order"]["last_price"]), (200, 20))
        account = self.api("/api/paper?symbol=sh600001")[1]
        self.assertEqual(account["positions"][0]["sellable"], 0)
        self.assertEqual(self.api("/api/watchlist", {"action":"remove", "id":self.stock["id"]})[0], 409)
        self.assertEqual(self.api("/api/paper/preview", {**body, "side":"sell"})[0], 400)
        self.now = self.now.replace(hour=16)
        self.assertEqual(self.api("/api/paper/orders", buy)[1], filled)
        self.assertFalse(self.api("/api/paper/preview", body)[1]["can_trade"])
        self.assertEqual(self.api("/api/paper/orders", {**buy, "request_id":"example-buy-2"})[0], 400)
        self.now = (self.now + timedelta(days=1)).replace(hour=10)
        self.quote.update(asof=self.now.isoformat(), price=21, bid=20.98)
        sell = {**body, "side":"sell", "request_id":"example-sell-1", "expected_price":20.98}
        status, sold = self.api("/api/paper/orders", sell)
        self.assertEqual((status, sold["order"]["quote_price"]), (200, 20.98))
        account = self.api("/api/paper?symbol=sh600001")[1]
        self.assertEqual(account["positions"], [])
        self.assertAlmostEqual(account["cash"] - account["initial_cash"], sold["order"]["realized_pnl"], places=2)

    def test_refuse_invalid_quotes_origins_and_unwatched_symbols(self):
        body = dict(symbol=self.stock["id"], side="buy", quantity=100)
        self.assertEqual(self.api("/api/paper/preview", body, {"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.api("/api/paper/preview", {**body, "symbol":"sh000300"})[0], 400)
        self.assertEqual(self.api("/api/paper/preview", {**body, "price":1})[0], 400)
        for changed in ({"status":"cached"}, {"ask":None}, {"suspended":True}, {"limit_up":20.02},
                        {"asof": (self.now-timedelta(minutes=5)).isoformat()}):
            with self.subTest(changed=changed), patch.dict(self.quote, changed):
                self.assertFalse(self.api("/api/paper/preview", body)[1]["can_trade"])
                self.assertEqual(self.api("/api/paper/orders", {**body,"request_id":"invalid-fill","expected_price":20.02})[0], 400)
        self.assertEqual(self.app.paper.book.symbols(), [])

    def test_replay_page_and_background_review_preference(self):
        status, empty = self.api("/api/replay?symbol=sh600001")
        self.assertEqual((status, empty["paired"]["samples"], empty["auto_ai"], empty["model_enabled"]),
                         (200, 0, False, False))
        self.assertIsNone(empty["paired"]["rows"][0]["net_return"])
        self.assertEqual(self.api("/api/replay?symbol=sh000300")[0], 400)
        path = "/api/replay/settings"
        self.assertEqual(self.api(path, {"auto_ai":True}, {"Origin":"https://example.com"})[0], 403)
        for invalid in [[], {"auto_ai":"true"}, {"auto_ai":True, "extra":1}]:
            self.assertEqual(self.api(path, invalid)[0], 400)
        self.assertEqual(self.api(path, {"auto_ai":True}), (200, {"model_enabled":False, "auto_ai":True}))
        self.assertTrue(self.api("/api/replay?symbol=sh600001")[1]["auto_ai"])

    def test_preview_projected_account_and_sector_coverage(self):
        stock = self.stock["id"]
        peer, unclassified = "sh600002", "sh600003"
        yesterday = self.now - timedelta(days=1)
        for symbol, shares in ((stock, 200), (peer, 300), (unclassified, 100)):
            mark = {**self.quote, "id":symbol, "asof":yesterday.isoformat()}
            self.app.paper.book.trade(symbol, "Demo", "buy", shares, mark, symbol, now=yesterday)
        marks = {s:{**self.quote, "id":s} for s in (stock, peer)}
        self.app.paper.risk_context = lambda symbols, selected, horizon, quote: {
            "sectors": {stock:"电子", peer:"电子"}, "stop":18, "stop_asof":yesterday.date().isoformat()}
        body = dict(symbol=stock, side="buy", quantity=100, horizon=20)
        with patch("stocks.quotes", return_value=marks) as feeds:
            status, result = self.api("/api/paper/preview", body)
            self.assertEqual(status, 200)
            self.assertEqual(set(feeds.call_args.args[0]), {stock, peer, unclassified})
            self.assertEqual(feeds.call_count, 1)
        risk = result["risk"]
        self.assertEqual((risk["horizon"], risk["quantity_after"], risk["sellable_after"], risk["locked_after"]),
                         (20, 300, 200, 100))
        before = self.app.paper.book.snapshot(marks, as_of=self.now)
        self.assertEqual(risk["equity_before"], before["equity"])
        self.assertAlmostEqual(risk["equity_after"], before["equity"] + result["preview"]["cash_delta"] + 2000)
        self.assertAlmostEqual(risk["sector_after_pct"], 100 * (6000 + 6000) / risk["equity_after"], places=4)
        self.assertEqual((risk["sector"], risk["unknown_sector_count_after"], risk["stale_mark_count"]), ("电子", 1, 1))
        self.assertEqual(risk["stop_state"], "available")
        loss = 6000 - float(liquidation_proceeds(18, 300))
        self.assertEqual(risk["stop_loss"], loss)
        self.assertAlmostEqual(risk["equity_at_stop"], risk["equity_after"] - loss)
        self.assertAlmostEqual(risk["stop_loss_pct"], 100 * loss / risk["equity_after"], places=4)
        self.assertEqual(before["positions"][0]["quantity"], 200)  # Preview is read-only.

    def test_full_exit_and_unavailable_price_scenarios(self):
        stock = self.stock["id"]
        self.app.paper.risk_context = None
        body = dict(symbol=stock, side="buy", quantity=100)
        status, base = self.api("/api/paper/preview", body)
        self.assertEqual(status, 200)
        self.assertEqual(base["risk"]["stop_state"], "missing")
        self.assertIsNone(base["risk"]["stop_loss"])
        self.assertIsNone(base["risk"]["sector_after_pct"])
        self.assertEqual(self.api("/api/paper/preview", {**body, "horizon":True})[0], 400)
        self.app.paper.risk_context = lambda *_: {"stop":21, "stop_asof":self.now.date().isoformat()}
        self.assertEqual(self.api("/api/paper/preview", body)[1]["risk"]["stop_state"], "breached")
        with patch.dict(self.quote, {"status":"cached"}):
            risk = self.api("/api/paper/preview", body)[1]["risk"]
            self.assertEqual(risk["stop_state"], "stale")
            self.assertEqual(risk["stale_mark_count"], 1)
            self.assertIsNone(risk["equity_at_stop"])
        yesterday = self.now-timedelta(days=1)
        mark = {**self.quote, "asof":yesterday.isoformat()}
        self.app.paper.book.trade(stock, "Demo", "buy", 100, mark, "held", now=yesterday)
        sell = self.api("/api/paper/preview", {**body,"side":"sell"})[1]
        risk = sell["risk"]
        self.assertEqual((risk["stop_state"], risk["quantity_after"], risk["sellable_after"], risk["locked_after"]),
                         ("closed", 0, 0, 0))
        self.assertEqual(risk["stop_loss"], 0)
        self.assertEqual(risk["equity_after"], sell["preview"]["cash_after"])
