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
