from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from watchlist import Watchlist


class WatchlistTest(unittest.TestCase):
    def test_concurrent_adds_survive_restart_and_remove(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "watchlist.sqlite"
            book = Watchlist(path)
            securities = [{"id": "sh688836", "name": "宇树科技"}, {"id": "sz000001", "name": "平安银行"}]
            with ThreadPoolExecutor(3) as pool:
                list(pool.map(lambda s: book.update(s["id"], s), securities * 2))
            reopened = Watchlist(path)
            self.assertEqual(len(reopened.all()), 2)
            self.assertEqual(reopened.get("sh688836"), securities[0])
            self.assertEqual(reopened.update("sh688836", None), [securities[1]])
            self.assertIsNone(Watchlist(path).get("sh688836"))
