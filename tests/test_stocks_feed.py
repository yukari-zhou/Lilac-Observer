from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sources
import stocks


class StockFeeds(unittest.TestCase):
    def test_new_ipo_search_and_offline_pack(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(sources, "CACHE", Path(tmp) / "cache"),
            patch.object(stocks, "SNAPSHOTS", Path(tmp) / "snapshots"),
            patch.dict(os.environ, {"HENGJIAN_OFFLINE": "1"}),
            patch.object(stocks, "_CACHE", {}),
            patch.object(stocks, "_QUOTE_MEM", {}),
            patch.object(sources, "_get", side_effect=AssertionError("network")),
        ):
            with patch.object(stocks, "_CACHE", {}):
                self.assertFalse(stocks.directory_available())

            sh = stocks._instrument("688001", "SH", "示例科技", "科创板", english="EXAMPLE TECH")
            sh["pinyin"] = "slkj"
            bj = stocks._instrument("920001", "BJ", "示例材料", "北交所")
            quote = {"id": sh["id"], "price": 12.5, "asof": "2020-01-02T15:00:00+08:00"}
            bar = {"date": "2020-01-02", "open": 12, "high": 13, "low": 11, "close": 12.5, "volume": 100}
            records = {
                "directory": {s["id"]: s for s in (sh, bj)},
                "sh688001-quote": quote,
                "sh688001-history": {"bars": [bar], "adjustment": "qfq", "history_basis": "前复权日线"},
            }
            for key, value in records.items():
                sources._save(stocks.SNAPSHOTS / (key + ".json.gz"),
                              {"value": value, "fetched": datetime.fromisoformat(quote["asof"]).timestamp()})

            self.assertTrue(stocks.directory_available())
            for query in ("示例科技", "示例科技-W", "sh688001", "688001.SH", "EXAMPLE TECH", "slkj"):
                self.assertEqual(stocks.search(query)[0]["id"], sh["id"])
            self.assertEqual(stocks.search("600005"), [])
            self.assertIsNone(stocks.resolve("sh000001"))
            self.assertEqual(stocks.resolve(bj["id"])["exchange"], "BJ")
            result = stocks.market(sh["id"])
        self.assertEqual(result["meta"]["history_status"], "snapshot")
        self.assertEqual(result["meta"]["quote_status"], "snapshot")
        self.assertEqual(result["meta"]["adjustment"], "qfq")
        self.assertEqual(result["quote"]["price"], quote["price"])
        self.assertEqual(result["bars"], [bar])

    def test_partial_session_and_ex_dividend_edge(self):
        instant = datetime(2026, 11, 20, 12, 0, tzinfo=sources.CN)
        rows = [["2026-11-17", -3, -2, 1, -3, 10], ["2026-11-19", 20, 21, 21, 20, 12],
                ["2026-11-20", 22, 23, 23, 22, 10]]
        quote = {"asof": instant.isoformat(), "price": 23}
        with patch.object(sources, "now", return_value=instant):
            self.assertEqual([r["date"] for r in stocks._bars(rows, quote)], ["2026-11-19"])
        closed = instant.replace(hour=16)
        with patch.object(sources, "now", return_value=closed):
            self.assertEqual(len(stocks._bars(rows, quote)), 1)
            self.assertEqual(len(stocks._bars(rows, {**quote, "asof": closed.isoformat()})), 2)

    def test_fallback_never_claims_unadjusted_bars_are_adjusted(self):
        payload = {"data": {"sh688836": {"day": [["2026-08-19", 10, 11, 12, 9, 200]]}}}
        with patch.object(sources, "_get", side_effect=[OSError("unavailable"), json.dumps(payload)]):
            hist = stocks._history("sh688836", None)
        self.assertEqual(hist["adjustment"], "raw")
        self.assertEqual(hist["bars"][0]["volume"], 2)

    def test_removed_symbol_never_refreshes_prices(self):
        stock = dict(id="sh600005", kind="stock", name="武钢股份")
        with patch.object(stocks, "resolve", return_value=None), \
                patch.object(stocks, "_fallback", return_value=(None, "unavailable", 0)), \
                patch.object(stocks, "quotes", side_effect=AssertionError("network")):
            market = stocks.market("sh600005", watched=stock)
        self.assertEqual(market["meta"]["quote_status"], "unavailable")
        self.assertIsNone(market["quote"])
        with self.assertRaises(ValueError):
            stocks.market("../../example", watched={**stock, "id": "../../example"})
