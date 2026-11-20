"""Immutable first-issued pre-open research calls and subsequent close-to-close outcomes."""
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from statistics import fmean


TZ = timezone(timedelta(hours=8))


class ForwardBook:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as cx, cx:
            cx.execute("BEGIN IMMEDIATE")
            cx.execute("""CREATE TABLE IF NOT EXISTS forecasts (
                symbol TEXT, horizon INTEGER, origin TEXT, issued TEXT, base REAL, center REAL,
                low REAL, high REAL, direction TEXT, posture TEXT, research TEXT,
                matured TEXT, close REAL, PRIMARY KEY (symbol,horizon,origin))""")
            if "basis" not in {r[1] for r in cx.execute("PRAGMA table_info(forecasts)")}:
                cx.execute("ALTER TABLE forecasts ADD COLUMN basis TEXT NOT NULL DEFAULT 'index'")

    def record(self, packet, review):
        model = packet["analysis"]
        if (review.get("status") != "ready" or model.get("historical") or packet["quote_status"] != "latest"
                or packet.get("history_status") != "latest"):
            return
        stock = packet["index"].get("kind") == "stock"
        if stock and (not model.get("validation", {}).get("n") or packet.get("adjustment") != "qfq"):
            return
        day = date.fromisoformat(model["as_of"])
        quote = packet.get("quote") or {}
        if str(quote.get("asof") or "")[:10] != day.isoformat():
            return
        issued = datetime.fromisoformat(review["updated_at"]).astimezone(TZ)
        # Conservatively skip later holiday dates when the exchange calendar is unknown.
        next_weekday = day + timedelta(days=1)
        while next_weekday.weekday() >= 5:
            next_weekday += timedelta(days=1)
        if not datetime.combine(day, time(15), TZ) <= issued < datetime.combine(next_weekday, time(9, 15), TZ):
            return
        band = model["interval"]
        args = (packet["index"]["id"], model["horizon"], day.isoformat(), issued.isoformat(),
                model["base_price"], band["base"], band["low"], band["high"], model["direction"],
                review["posture"], json.dumps({"input": packet, "review": review}, ensure_ascii=False),
                "qfq" if stock else "index")
        with closing(sqlite3.connect(self.path)) as cx, cx:
            cx.execute("""INSERT OR IGNORE INTO forecasts
                       (symbol,horizon,origin,issued,base,center,low,high,direction,posture,research,basis)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", args)

    def track(self, symbol, horizon, bars, adjustment=None):
        with closing(sqlite3.connect(self.path)) as cx, cx:
            cx.row_factory = sqlite3.Row
            pending = cx.execute("SELECT origin,base,basis FROM forecasts WHERE symbol=? AND horizon=? AND matured IS NULL",
                                 (symbol, horizon)).fetchall()
            if pending:
                positions = {r["date"]: i for i, r in enumerate(bars)}
                for p in pending:
                    i = positions.get(p["origin"])
                    if i is not None and i + horizon < len(bars):
                        result = bars[i + horizon]
                        close = result["close"]
                        if p["basis"] == "qfq":
                            if adjustment != "qfq" or bars[i]["close"] <= 0:
                                continue
                            # Rebasing the observed return avoids a spurious loss
                            # when a later corporate action shifts the qfq series.
                            close = p["base"] * (close / bars[i]["close"])
                        cx.execute("""UPDATE forecasts SET matured=?, close=?
                                   WHERE symbol=? AND horizon=? AND origin=? AND matured IS NULL""",
                                   (result["date"], close, symbol, horizon, p["origin"]))
            rows = cx.execute("""SELECT origin,horizon,issued,base,center,low,high,direction,posture,matured,close
                                FROM forecasts WHERE symbol=? AND horizon=? ORDER BY origin DESC""",
                              (symbol, horizon)).fetchall()
        done = [r for r in rows if r["matured"]]
        def sign(value):
            return (value > 0) - (value < 0)
        return dict(pending=len(rows) - len(done), settled=len(done),
                    hit_rate=fmean(sign(r["center"]-r["base"]) == sign(r["close"]-r["base"]) for r in done) if done else None,
                    coverage=fmean(r["low"] <= r["close"] <= r["high"] for r in done) if done else None,
                    recent=[dict(origin=r["origin"], horizon=horizon, issued_at=r["issued"], posture=r["posture"],
                                 direction=r["direction"], status="settled" if r["matured"] else "pending",
                                 matured=r["matured"], actual_return=r["close"]/r["base"]-1 if r["matured"] else None)
                            for r in rows[:10]])
