"""Local long-only A-share simulation. Cash, basis and realized P&L are stored in fen."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re
import sqlite3

from trading_costs import break_even_quote, execution, liquidation_proceeds


CN = timezone(timedelta(hours=8))
INITIAL_CASH_FEN = 100_000_000


def _now(instant):
    return datetime.now(CN) if instant is None else instant.astimezone(CN)


def _yuan(fen):
    return Decimal(fen).scaleb(-2)


def _fen(yuan):
    return int((yuan * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _quote(symbol, quote):
    if not isinstance(quote, dict) or quote.get("id", symbol) != symbol:
        raise ValueError("缺少该股票的有效报价")
    try:
        stamp = datetime.fromisoformat(quote["asof"])
        price = Decimal(str(quote["price"]))
        if (stamp.tzinfo is None or not price.is_finite() or not 0 < price < 100_000_000
                or price != price.quantize(Decimal(".01"))):
            raise ValueError()
        source = quote["source"]
        if not isinstance(source, str) or not source.strip():
            raise ValueError()
        return price, stamp.astimezone(CN), source
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise ValueError("报价须包含有效的原始股价、来源和交易所时点") from None


def _check_order(symbol, side, quantity):
    if not isinstance(symbol, str) or not re.fullmatch(r"(sh(60\d{4}|688\d{3})|sz(00|30)\d{4}|bj\d{6})", symbol):
        raise ValueError("模拟交易仅支持自选 A 股股票")
    if side not in ("buy", "sell") or type(quantity) is not int or quantity < 1:
        raise ValueError("请选择买入或卖出，并填写正整数股数")


def market_order_limit(symbol):
    if symbol.startswith("sh688"):
        return 50_000
    if symbol.startswith("sz30"):
        return 150_000
    return 1_000_000


def _check_lot(symbol, side, quantity, sellable):
    star = symbol.startswith("sh688")
    minimum = 200 if star else 100
    step = 1 if star or symbol.startswith("bj") else 100
    maximum = market_order_limit(symbol)
    if quantity > maximum:
        raise ValueError(f"该板块单笔模拟市价成交上限为 {maximum} 股")
    if side == "sell":
        if quantity > sellable:
            raise ValueError(f"当前仅有 {sellable} 股可卖；当日买入的股票须待下个交易日")
        # An entire odd-lot balance can be sold in one order.
        if quantity == sellable or (step == 100 and sellable % 100 and quantity % 100 == sellable % 100):
            return
    if quantity < minimum or quantity % step:
        raise ValueError(f"该板块每笔至少 {minimum} 股，按 {step} 股递增；不足起点的余股可一次卖清")


def _today_buys(db, symbol, day):
    return db.execute("""SELECT COALESCE(SUM(quantity),0) FROM orders
        WHERE symbol=? AND side='buy' AND trade_date=?""", (symbol, day)).fetchone()[0]


class PaperBook:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY CHECK (id=1), initial_cents INTEGER NOT NULL,
                cash_cents INTEGER NOT NULL CHECK (cash_cents>=0), realized_cents INTEGER NOT NULL)""")
            db.execute("INSERT OR IGNORE INTO account VALUES (1,?,?,0)", (INITIAL_CASH_FEN, INITIAL_CASH_FEN))
            db.execute("""CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY, name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK (quantity>0),
                basis_cents INTEGER NOT NULL, quote_cents INTEGER NOT NULL,
                quote_asof TEXT NOT NULL, quote_source TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS orders (
                request_id TEXT UNIQUE NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
                quantity INTEGER NOT NULL, trade_date TEXT NOT NULL, receipt TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS orders_day ON orders(symbol,trade_date,side)")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def symbols(self):
        with closing(self._connect()) as db:
            return [r[0] for r in db.execute("SELECT symbol FROM positions ORDER BY symbol")]

    @staticmethod
    def _lookup(db, request_id, symbol, side, quantity):
        _check_order(symbol, side, quantity)
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
            raise ValueError("模拟订单标识无效")
        prior = db.execute("SELECT receipt FROM orders WHERE request_id=?", (request_id,)).fetchone()
        if prior is None:
            return None
        order = json.loads(prior[0])
        if (symbol, side, quantity) != (order["symbol"], order["side"], order["quantity"]):
            raise ValueError("该订单标识已用于另一笔模拟交易，请重新预览")
        return order

    def lookup(self, request_id, symbol, side, quantity):
        with closing(self._connect()) as db:
            return self._lookup(db, request_id, symbol, side, quantity)

    @staticmethod
    def _price_order(db, symbol, side, quantity, quote, now, for_trade):
        _check_order(symbol, side, quantity)
        price, stamp, source = _quote(symbol, quote)
        if for_trade and (quote.get("suspended") or stamp.date() != now.date() or stamp > now + timedelta(seconds=5)):
            raise ValueError("当前报价不可用于模拟成交")
        position = db.execute("SELECT quantity,basis_cents FROM positions WHERE symbol=?", (symbol,)).fetchone()
        held, basis = position if position else (0, 0)
        sellable = held - _today_buys(db, symbol, now.date().isoformat())
        _check_lot(symbol, side, quantity, sellable)
        terms = execution(side, price, quantity)
        delta = _fen(terms["cash_delta"])
        cash_after = db.execute("SELECT cash_cents FROM account WHERE id=1").fetchone()[0] + delta
        if cash_after < 0:
            raise ValueError("模拟可用现金不足以支付本笔交易及费用")
        if side == "buy":
            quantity_after, basis_after, realized = held + quantity, basis - delta, 0
        else:
            # Allocate the moving-average book cost in integer fen; closing the
            # remainder releases every last fen, even after several partial fills.
            released = int((Decimal(basis) * quantity / held).to_integral_value(rounding=ROUND_HALF_UP))
            quantity_after, basis_after, realized = held - quantity, basis - released, delta - released
        receipt = dict(symbol=symbol, side=side, quantity=quantity, quote_asof=stamp.isoformat(),
                       last_price=quote.get("last_price", float(price)),
                       quote_source=source, cash_after=float(_yuan(cash_after)), realized_pnl=float(_yuan(realized)),
                       **{k: float(v) for k, v in terms.items()})
        return receipt, quantity_after, basis_after, cash_after, realized

    def preview(self, symbol, side, quantity, quote, now=None):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN")
            return self._price_order(db, symbol, side, quantity, quote, _now(now), False)[0]

    def trade(self, symbol, name, side, quantity, quote, request_id, now=None):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            prior = self._lookup(db, request_id, symbol, side, quantity)
            if prior:
                return prior
            now = _now(now)
            order, held, basis, cash, realized = self._price_order(db, symbol, side, quantity, quote, now, True)
            order.update(name=name, request_id=request_id, executed_at=now.isoformat(timespec="seconds"))
            db.execute("UPDATE account SET cash_cents=?, realized_cents=realized_cents+? WHERE id=1", (cash, realized))
            if held:
                db.execute("""INSERT INTO positions VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, quantity=excluded.quantity,
                    basis_cents=excluded.basis_cents, quote_cents=excluded.quote_cents,
                    quote_asof=excluded.quote_asof, quote_source=excluded.quote_source""",
                           (symbol, name, held, basis, _fen(Decimal(str(order["last_price"]))),
                            order["quote_asof"], order["quote_source"]))
            else:
                db.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)",
                       (request_id, symbol, side, quantity, now.date().isoformat(), json.dumps(order, ensure_ascii=False)))
            return order

    def snapshot(self, quotes=None, as_of=None):
        now = _now(as_of)
        quotes = quotes or {}
        with closing(self._connect()) as db, db:
            db.execute("BEGIN")
            account = db.execute("SELECT initial_cents,cash_cents,realized_cents FROM account WHERE id=1").fetchone()
            initial, cash, realized = map(_yuan, account)
            history = [json.loads(r[0]) for r in db.execute("SELECT receipt FROM orders ORDER BY rowid DESC LIMIT 50")]
            positions = []
            market_value = net_exit = total_basis = Decimal(0)
            for row in db.execute("SELECT * FROM positions ORDER BY symbol"):
                symbol, quantity = row["symbol"], row["quantity"]
                basis, price = _yuan(row["basis_cents"]), _yuan(row["quote_cents"])
                stamp = datetime.fromisoformat(row["quote_asof"])
                source, valuation, status = row["quote_source"], "last_trade_quote", "last_trade_quote"
                candidate = quotes.get(symbol)
                if candidate:
                    try:
                        next_price, next_stamp, next_source = _quote(symbol, candidate)
                    except ValueError:
                        pass
                    else:
                        if stamp <= next_stamp <= now + timedelta(seconds=5):
                            price, stamp, source = next_price, next_stamp, next_source
                            valuation, status = "quote", candidate.get("status", "unknown")
                value = price * quantity
                maximum = market_order_limit(symbol)
                proceeds = liquidation_proceeds(price, quantity, maximum)
                market_value += value
                net_exit += proceeds
                total_basis += basis
                positions.append(dict(symbol=symbol, name=row["name"], quantity=quantity,
                                      sellable=quantity - _today_buys(db, symbol, now.date().isoformat()),
                                      cost_basis=float(basis), avg_cost=round(float(basis / quantity), 4),
                                      price=float(price), market_value=float(value), unrealized_pnl=float(value - basis),
                                      exit_net_pnl=float(proceeds - basis),
                                      break_even_quote=float(break_even_quote(basis, quantity, maximum)),
                                      quote_asof=stamp.isoformat(), quote_source=source, valuation_source=valuation,
                                      quote_status=status))
            equity = cash + market_value
            for position in positions:
                position["weight_pct"] = round(position["market_value"] * 100 / float(equity), 4) if equity else 0
            return dict(initial_cash=float(initial), cash=float(cash), equity=float(equity), market_value=float(market_value),
                        net_liquidation_equity=float(cash + net_exit), realized_pnl=float(realized),
                        unrealized_pnl=float(market_value - total_basis), total_pnl=float(equity - initial),
                        positions=positions, history=history)
