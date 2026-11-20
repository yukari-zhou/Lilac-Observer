"""Persist a user's selected company securities independently of provider availability."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3


class Watchlist:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS stocks (symbol TEXT PRIMARY KEY, security TEXT NOT NULL)")

    def all(self):
        with closing(sqlite3.connect(self.path)) as db:
            return self._rows(db)

    @staticmethod
    def _rows(db):
        return [json.loads(row[0]) for row in db.execute("SELECT security FROM stocks ORDER BY rowid")]

    def get(self, symbol):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT security FROM stocks WHERE symbol=?", (symbol,)).fetchone()
        return json.loads(row[0]) if row else None

    def update(self, symbol, security):
        with closing(sqlite3.connect(self.path)) as db, db:
            if security is None:
                db.execute("DELETE FROM stocks WHERE symbol=?", (symbol,))
            else:
                db.execute("""INSERT INTO stocks(symbol,security) VALUES(?,?)
                           ON CONFLICT(symbol) DO UPDATE SET security=excluded.security""",
                           (symbol, json.dumps(security, ensure_ascii=False)))
            return self._rows(db)
