from datetime import date
import unittest

from engine import analyze, eligible_evidence
from stock_fundamentals import _disclosed_report, evidence, sector_exposure
from tests.test_engine import fixture


def stock_sample(size):
    market = fixture(size)
    market.update(id="sh688836", kind="stock")
    market["meta"].update(adjustment="qfq", quote_status="latest")
    return market


class StockModelTest(unittest.TestCase):
    def test_ipo_with_zero_validated_signals(self):
        market = stock_sample(61)
        for horizon in (1, 5, 20):
            model = analyze(market, horizon)
            self.assertEqual(model["status"], "ok")
            self.assertEqual(model["validation"]["n"], 0)
            self.assertEqual(model["direction"], "样本待积累")
            self.assertIsNone(model["score"])
            self.assertEqual(model["interval_basis"], "volatility")
            self.assertEqual(model["interval"]["base"], round(model["base_price"], 2))
            self.assertEqual(model["interval"]["return_base"], 0)
            self.assertEqual(model["strategy"]["action"], "等待样本积累")
            self.assertIn("元", model["strategy"]["stop_note"])
            self.assertNotIn("指数", model["strategy"]["stop_note"])
        short = analyze(stock_sample(59), 5)
        self.assertEqual(short["status"], "insufficient")
        self.assertIsNone(short["strategy"]["stop"])

    def test_price_basis_and_suspension(self):
        m = stock_sample(180)
        self.assertEqual(analyze(m, 5)["interval_basis"], "forecast")
        m["meta"]["suspended"] = True
        self.assertTrue(analyze(m, 5)["historical"])
        m["meta"]["suspended"] = False
        m["quote"] = {"asof": m["bars"][-1]["date"] + "T15:10:00+08:00", "price": 0.5*m["bars"][-1]["close"]}
        self.assertTrue(analyze(m, 5)["historical"])
        m["meta"]["adjustment"] = "raw"
        self.assertIsNone(analyze(m, 1)["strategy"]["stop"])

    def test_publication_date_and_exchange_matching(self):
        row = dict(SECUCODE="000001.SZ", SECURITY_CODE="000001", SECURITY_NAME_ABBR="平安银行",
                   BOARD_NAME="银行Ⅱ", REPORTDATE="2026-09-30", NOTICE_DATE="2026-10-24", UPDATE_DATE="2026-11-01",
                   YSTZ=5, SJLTZ=1.5)
        rows = [row, dict(row, SECUCODE="000001.SH", REPORTDATE="2026-10-31")]
        with self.assertRaises(ValueError):
            _disclosed_report(rows, "000001.SZ", date(2026, 11, 1))
        current = _disclosed_report(rows, "000001.SZ", date(2026, 11, 2))
        self.assertEqual(current["period"], "2026-09-30")
        self.assertEqual(current["known_on"], "2026-11-01")
        self.assertIsNone(evidence({"id": "sh000001", "code": "000001", "exchange": "SZ"}))

    def test_sector_matches_and_filings_expire(self):
        release = dict(title="规模以上工业", sector_yoy={"通用设备制造业": 9.5}, summary="增长", fetched_at="2026-11-16")
        fin = dict(index_id="sh688836", report=dict(sector="自动化设备"), fetched_at="2026-11-20", url="example")
        result = sector_exposure(release, fin)
        self.assertGreater(result["signal"], 0)
        self.assertEqual(result["index_id"], "sh688836")
        self.assertIn("上市公告书", result["summary"])
        self.assertIs(sector_exposure(release, dict(fin, index_id="sh600000")), release)
        filing = dict(title="季报", source="公司公告", scope="sh688836", index_id="sh688836",
                      kind="filing", published_at="2026-10-29")
        self.assertTrue(eligible_evidence(filing, "2026-11-20", "sh688836"))
        self.assertFalse(eligible_evidence(filing, "2026-12-20", "sh688836"))
