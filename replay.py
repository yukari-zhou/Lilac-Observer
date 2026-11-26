"""Forward-only comparison of frozen five-session stock signals on observed quotes."""
from contextlib import closing
from collections import deque
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3

from astra import replay_key as packet_digest
from paper import CN, INITIAL_CASH_FEN, market_order_limit
from paper_service import fill_block
from trading_costs import execution, liquidation_proceeds

INITIAL = Decimal(INITIAL_CASH_FEN) / 100
HORIZON = 5
_AWAITING_REVIEW = """review_packet IS NOT NULL AND review_attempted=0 AND posture IS NULL
                      AND quote IS NULL AND captured<=? AND trade_day>=?"""


def _stamp(value):
    try:
        instant = datetime.fromisoformat(value)
        return instant.astimezone(CN) if instant.tzinfo else None
    except (TypeError, ValueError):
        return None


def _now(value):
    return (value or datetime.now(CN)).astimezone(CN)


def _next_weekday(day):
    target = day + timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    return target


def _review_window(now):
    # Captures originate after close. At 09:15 the current trade day's window expires.
    first_trade_day = now.date() if now.time() < time(9, 15) else now.date() + timedelta(days=1)
    return now.isoformat(), first_trade_day.isoformat()


def _price(value):
    try:
        number = Decimal(str(value))
        if number.is_finite() and Decimal(".01") <= number < 100_000_000 and number == number.quantize(Decimal(".01")):
            return number
    except (ValueError, InvalidOperation):
        pass
    return None


def _signal(analysis, origin):
    if (analysis.get("as_of") != origin or analysis.get("horizon") != HORIZON or
            analysis.get("status") != "ok" or analysis.get("historical") or
            not (analysis.get("validation") or {}).get("n")):
        return None
    strategy = analysis.get("strategy") or {}
    pnl = (strategy.get("trade_costs") or {}).get("base_net_pnl")
    if pnl is None:
        return None
    return dict(long=analysis["direction"] == "偏强" and pnl > 0, direction=analysis["direction"],
                score=analysis.get("score"), pnl=pnl, stop=strategy.get("stop"),
                close=analysis.get("base_price"), evidence_groups=analysis.get("evidence_groups", 0))


def _capacity(cash, ref, symbol):
    # Binary search over the board's valid sizes, including commission rounding.
    minimum = 200 if symbol.startswith("sh688") else 100
    step = 1 if symbol.startswith(("sh688", "bj")) else 100
    maximum = min(market_order_limit(symbol), int(cash // ref))
    low, high = 0, (maximum - minimum) // step
    result = 0
    while low <= high:
        middle = (low + high) // 2
        shares = minimum + middle * step
        if -execution("buy", ref, shares)["cash_delta"] <= cash:
            result = shares
            low = middle + 1
        else:
            high = middle - 1
    return result


class _Portfolio:
    """A single isolated sleeve. One rebalance at most per observed session."""
    def __init__(self, key):
        self.key = key
        self.cash = self.peak = self.nav = INITIAL
        self.shares = self.trades = self.unfilled = 0
        self.drawdown = self.turnover = self.fees = Decimal(0)

    def step(self, symbol, want_long, quote):
        outcome = "hold" if self.shares else "cash"
        if bool(self.shares) != want_long:
            side = "buy" if want_long else "sell"
            reference = quote[side]
            shares = self.shares
            if reference is not None:
                ref = Decimal(str(reference))
                if want_long:
                    shares = _capacity(self.cash, ref, symbol)
            # Quotes are frozen in unique, increasing session dates. A sell can
            # only release a position opened on an earlier session (T+1).
            if shares and reference is not None:
                terms = execution(side, ref, shares)
                self.cash += terms["cash_delta"]
                self.shares = shares if want_long else 0
                self.fees += terms["fees"]
                self.turnover += terms["gross"]
                self.trades += 1
                outcome = side
            else:
                self.unfilled += 1
                outcome = "unfilled"
        self.mark(symbol, quote)
        return outcome

    def mark(self, symbol, quote):
        self.nav = self.cash
        if self.shares:
            self.nav += liquidation_proceeds(Decimal(str(quote["price"])), self.shares, market_order_limit(symbol))
        self.peak = max(self.peak, self.nav)
        self.drawdown = max(self.drawdown, 1 - self.nav / self.peak)

    def result(self, observed):
        return dict(key=self.key, net_return=float(self.nav / INITIAL - 1) if observed else None,
                    max_drawdown=float(self.drawdown) if observed else None,
                    turnover=float(self.turnover / INITIAL) if observed else None,
                    fees=float(self.fees), trades=self.trades, unfilled=self.unfilled)


def _latest_segment(observed):
    """Avoid carrying shares across an unverified or changed raw price basis."""
    start, reason = 0, None
    for i in range(1, len(observed)):
        prev, current = observed[i-1], observed[i]
        # Both values are unadjusted feed fields, frozen on their own dates.
        # An overnight change in the stock's traded price is not a basis change.
        raw_close = current["price_signal"].get("raw_close")
        next_reference = current["quote"].get("prev_close")
        if prev["trade_day"] != current["origin"]:
            start, reason = i, "observation_gap"
        elif raw_close is None or next_reference is None:
            start, reason = i, "missing_reference"
        elif raw_close != next_reference:
            start, reason = i, "price_basis_changed"
    return observed[start:], start, reason


def _comparison(symbol, segment, with_ai):
    accounts = [_Portfolio(key) for key in (("price", "evidence", "ai", "hold") if with_ai
                                           else ("price", "evidence", "hold"))]
    source = [r for r in segment if r["posture"] is not None] if with_ai else segment
    recent = deque(maxlen=5)
    for row in segment:
        if not source or row["trade_day"] > source[-1]["trade_day"]:
            break
        if row["trade_day"] < source[0]["trade_day"]:
            continue
        quote = row["quote"]
        if with_ai and row["posture"] is None:
            for account in accounts:
                account.mark(symbol, quote)
            continue
        price, evidence = row["price_signal"], row["evidence_signal"]
        targets = {"price": price["long"], "evidence": evidence["long"], "hold": True}
        if with_ai:
            # Waiting vetoes new exposure; it never vetoes an underlying exit.
            targets["ai"] = evidence["long"] and (row["posture"] == "follow" or
                                                  (row["posture"] == "wait" and accounts[2].shares > 0))
        actions = {a.key: a.step(symbol, targets[a.key], quote) for a in accounts}
        recent.append(dict(origin=row["origin"], day=row["trade_day"], quote_asof=quote["asof"],
                           price=quote["price"], posture=row["posture"], actions=actions))
    return {"samples": len(source), "from": source[0]["trade_day"] if source else None,
            "through": source[-1]["trade_day"] if source else None, "rows": [a.result(bool(source)) for a in accounts],
            "recent": list(reversed(recent))}


class ReplayBook:
    """Persist inputs when they become observable. Reports never estimate missing sessions."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS replay_settings (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS replay_v1 (
                symbol TEXT NOT NULL, origin TEXT NOT NULL, captured TEXT NOT NULL,
                trade_day TEXT NOT NULL, price_signal TEXT NOT NULL, evidence_signal TEXT NOT NULL,
                review_key TEXT, posture TEXT, reviewed_at TEXT, quote TEXT, review_packet TEXT,
                review_attempted INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(symbol,origin), UNIQUE(symbol,trade_day))""")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(replay_v1)")}
            if "review_packet" not in columns:
                db.execute("ALTER TABLE replay_v1 ADD COLUMN review_packet TEXT")
            if "review_attempted" not in columns:
                db.execute("ALTER TABLE replay_v1 ADD COLUMN review_attempted INTEGER NOT NULL DEFAULT 0")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def needs_capture(self, symbol, day):
        with closing(self._connect()) as db:
            return not db.execute("SELECT 1 FROM replay_v1 WHERE symbol=? AND origin=?", (symbol, str(day))).fetchone()

    def pending_symbols(self, day):
        with closing(self._connect()) as db:
            return {r[0] for r in db.execute("SELECT symbol FROM replay_v1 WHERE trade_day=? AND quote IS NULL",
                                             (str(day),))}

    def pending_reviews(self, now=None):
        with closing(self._connect()) as db:
            rows = db.execute("SELECT symbol,review_packet FROM replay_v1 WHERE " + _AWAITING_REVIEW,
                              _review_window(_now(now)))
            return {r["symbol"]: json.loads(r["review_packet"]) for r in rows}

    def claim_review(self, symbol, origin, key, now=None):
        with closing(self._connect()) as db, db:
            result = db.execute("UPDATE replay_v1 SET review_attempted=1 WHERE symbol=? AND origin=? "
                                "AND review_key=? AND " + _AWAITING_REVIEW,
                                (symbol, origin, key, *_review_window(_now(now))))
            return bool(result.rowcount)

    def auto_ai(self):
        with closing(self._connect()) as db:
            row = db.execute("SELECT value FROM replay_settings WHERE key='auto_ai'").fetchone()
            return bool(row and row[0])

    def set_auto_ai(self, value):
        if type(value) is not bool:
            raise ValueError("Invalid review preference")
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO replay_settings(key,value) VALUES ('auto_ai',?)", (int(value),))
        return value

    def capture(self, symbol, market, price_analysis, evidence_analysis, review_key=None, now=None, packet=None):
        clock = _now(now)
        origin = clock.date().isoformat()
        meta, q = market.get("meta") or {}, market.get("quote") or {}
        stamp = _stamp(q.get("asof"))
        if (clock.weekday() >= 5 or clock.time() < time(15) or market.get("kind") != "stock" or
                market.get("id") != symbol or q.get("id", symbol) != symbol or not stamp or
                stamp.date() != clock.date() or stamp.time() < time(15) or stamp > clock + timedelta(seconds=5) or
                meta.get("adjustment") != "qfq" or meta.get("quote_status") != "latest" or
                meta.get("history_status") != "latest" or meta.get("suspended")):
            return False
        price, evidence = _signal(price_analysis, origin), _signal(evidence_analysis, origin)
        raw_close = _price(q.get("price"))
        if price is None or evidence is None or raw_close is None:
            return False
        review_packet = None
        if packet is not None:
            public_fields = {"index", "quote", "quote_status", "history_status", "adjustment", "analysis", "evidence", "lang"}
            if (not isinstance(packet, dict) or set(packet) != public_fields or
                    (packet.get("index") or {}).get("id") != symbol or packet["analysis"] != evidence_analysis or
                    not review_key or packet_digest(packet) != review_key):
                return False
            review_packet = json.dumps(packet, ensure_ascii=False, allow_nan=False)
        price["raw_close"] = float(raw_close)
        trade_day = _next_weekday(clock.date()).isoformat()
        with closing(self._connect()) as db, db:
            return bool(db.execute("""INSERT OR IGNORE INTO replay_v1
                (symbol,origin,captured,trade_day,price_signal,evidence_signal,review_key,review_packet)
                VALUES (?,?,?,?,?,?,?,?)""",
                (symbol, origin, clock.isoformat(), trade_day, json.dumps(price), json.dumps(evidence),
                 review_key, review_packet)).rowcount)

    def attach_review(self, symbol, origin, review_key, review, now=None):
        clock = _now(now)
        stamp = _stamp(review.get("updated_at"))
        if (not review_key or review.get("status") != "ready" or not stamp or stamp > clock + timedelta(seconds=5)
                or review.get("posture") not in ("follow", "wait", "defensive") or
                review.get("as_of", origin) != origin):
            return False
        # The timed cutoff uses actual completion and arrival. Never attach a
        # fresh model view or a backdated response once the market can move.
        with closing(self._connect()) as db, db:
            row = db.execute("SELECT trade_day FROM replay_v1 WHERE symbol=? AND origin=?", (symbol, origin)).fetchone()
            if not row:
                return False
            deadline = datetime.combine(date.fromisoformat(row["trade_day"]), time(9, 15), CN)
            closed = datetime.combine(date.fromisoformat(origin), time(15), CN)
            if not closed <= stamp < deadline or not closed <= clock < deadline:
                return False
            return bool(db.execute("""UPDATE replay_v1 SET posture=?,reviewed_at=?
                WHERE symbol=? AND origin=? AND review_key=? AND posture IS NULL AND quote IS NULL""",
                (review["posture"], stamp.isoformat(), symbol, origin, review_key)).rowcount)

    def observe(self, symbol, quote, now=None):
        clock = _now(now)
        if not quote or quote.get("id", symbol) != symbol or fill_block(quote, clock):
            return False
        price = _price(quote.get("price"))
        if price is None:
            return False
        prev_close = _price(quote.get("prev_close"))
        mark = {"price": float(price), "asof": quote["asof"], "source": quote.get("source"),
                "prev_close": float(prev_close) if prev_close is not None else None}
        for side, opposite in (("buy", "ask"), ("sell", "bid")):
            opposing_price = _price(quote.get(opposite))
            mark[side] = None
            if opposing_price is not None:
                reference = (max if side == "buy" else min)(price, opposing_price)
                fill = float(execution(side, reference, 1)["fill_price"])
                if not fill_block(quote, clock, side, fill):
                    mark[side] = float(reference)
        with closing(self._connect()) as db, db:
            return bool(db.execute("UPDATE replay_v1 SET quote=? WHERE symbol=? AND trade_day=? AND quote IS NULL",
                                   (json.dumps(mark), symbol, clock.date().isoformat())).rowcount)

    def report(self, symbol, now=None):
        clock = _now(now)
        with closing(self._connect()) as db:
            records = db.execute("""SELECT origin,trade_day,price_signal,evidence_signal,posture,quote
                                    FROM replay_v1 WHERE symbol=? ORDER BY origin""", (symbol,)).fetchall()
        observed = [{**dict(r), **{k: json.loads(r[k]) for k in ("price_signal", "evidence_signal", "quote")}}
                    for r in records if r["quote"] is not None]
        segment, earlier, reason = _latest_segment(observed)
        missed = sum(not r["quote"] and
                     datetime.combine(date.fromisoformat(r["trade_day"]), time(14, 57), CN) <= clock for r in records)
        return dict(symbol=symbol, horizon=HORIZON, initial_cash=float(INITIAL), signals=len(records),
                    pending=len(records) - len(observed) - missed, missed=missed,
                    last_origin=records[-1]["origin"] if records else None,
                    segment_start=segment[0]["trade_day"] if segment else None,
                    restart_reason=reason, earlier_samples=earlier,
                    paired=_comparison(symbol, segment, False), common=_comparison(symbol, segment, True))
