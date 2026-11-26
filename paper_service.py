"""Market-facing checks for the local paper account. Prices come from the server feed."""
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
import re
import threading

import sources
import stocks
from paper import PaperBook


def _continuous(stamp):
    t = stamp.time()
    return time(9, 30) <= t < time(11, 30) or time(13) <= t < time(14, 57)


def fill_block(quote, now, side=None, fill_price=None):
    if not quote or not quote.get("price"):
        return "尚无可用报价"
    if quote.get("suspended"):
        return "该股停牌或尚无有效成交"
    if now.weekday() >= 5 or not _continuous(now):
        return "连续竞价时段以外，可预览费用和持仓变化"
    try:
        stamp = datetime.fromisoformat(quote["asof"])
        if stamp.tzinfo is None:
            raise ValueError
        stamp = stamp.astimezone(sources.CN)
    except (KeyError, TypeError, ValueError):
        return "报价时间无效，请刷新"
    if (quote.get("status") != "live" or now.date() != stamp.date() or not _continuous(stamp)
            or not -5 <= (now-stamp).total_seconds() <= 90):
        return "需要同一交易时段内的实时有效报价"
    if side and not quote.get("ask" if side == "buy" else "bid"):
        return "暂无可成交的对手方报价"
    if fill_price is not None:
        if ((quote.get("limit_up") and fill_price > quote["limit_up"])
                or (quote.get("limit_down") and fill_price < quote["limit_down"])):
            return "滑点后的成交价超出当日报价限制"
    return ""


class PaperDesk:
    def __init__(self, path, watchlist, risk_context=None):
        self.book = PaperBook(path)
        self.watchlist = watchlist
        self.risk_context = risk_context
        self.lock = threading.RLock()

    def stock(self, symbol):
        if not isinstance(symbol, str) or not re.fullmatch(r"(sh|sz|bj)\d{6}", symbol):
            raise ValueError("请选择自选股中的上市公司")
        stock = self.watchlist.get(symbol)
        if not stock or stock.get("kind") != "stock":
            raise ValueError("请先将该股票加入自选")
        return stock

    def snapshot(self, symbol):
        self.stock(symbol)
        quotes = stocks.quotes([*self.book.symbols(), symbol])
        now = sources.now()
        summary = self.book.snapshot(quotes, as_of=now)
        quote = quotes.get(symbol)
        reason = fill_block(quote, now)
        return {**summary, "quote": quote, "can_trade": not reason, "trade_reason": reason}

    def position(self, symbol):
        summary = self.snapshot(symbol)
        position = next((p for p in summary["positions"] if p["symbol"] == symbol), {})
        keys = ("quantity", "sellable", "cost_basis", "avg_cost", "market_value", "weight_pct",
                "unrealized_pnl", "break_even_quote", "exit_net_pnl", "quote_asof", "quote_status", "valuation_source")
        context = {k: position.get(k) for k in keys}
        quote = summary["quote"] or {}
        context.update(symbol=symbol, quantity=position.get("quantity", 0), sellable=position.get("sellable", 0),
                       price=position.get("price", quote.get("price")), cash=summary["cash"], equity=summary["equity"],
                       quote_asof=position.get("quote_asof", quote.get("asof")),
                       quote_status=position.get("quote_status", quote.get("status")),
                       valuation_source=position.get("valuation_source", "quote"))
        return context

    def order(self, data, confirm=False, on_fill=None):
        # Serialize quote checks, watchlist membership and review invalidation.
        with self.lock:
            return self._order(data, confirm, on_fill)

    def _order(self, data, confirm, on_fill):
        if not isinstance(data, dict):
            raise ValueError("无效的模拟订单")
        keys = {"symbol", "side", "quantity"}
        if confirm:
            keys.update(("request_id", "expected_price"))
        elif "horizon" in data:
            keys.add("horizon")
        if data.keys() != keys:
            raise ValueError("模拟订单字段不完整或含未知字段")
        symbol, side, quantity = data["symbol"], data["side"], data["quantity"]
        if not isinstance(symbol, str) or side not in ("buy", "sell") or type(quantity) is not int or quantity <= 0:
            raise ValueError("请选择买卖方向并输入正整数股数")
        if confirm:
            request_id = data["request_id"]
            if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", request_id):
                raise ValueError("无效的订单编号")
            old = self.book.lookup(request_id, symbol, side, quantity)
            if old:
                return {"order": old}
            try:
                expected = Decimal(str(data["expected_price"]))
                if not expected.is_finite() or expected <= 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                raise ValueError("请先预览当前报价") from None
        horizon = data.get("horizon", 5)
        if type(horizon) is not int or horizon not in (1, 5, 20):
            raise ValueError("预测周期可选 1、5、20 个交易日")
        stock = self.stock(symbol)
        symbols = [symbol] if confirm else list(dict.fromkeys([symbol, *self.book.symbols()]))
        marks = stocks.quotes(symbols)
        quote = marks.get(symbol)
        if not quote:
            raise ValueError("尚无可用报价")
        opposite = quote.get("ask" if side == "buy" else "bid")
        reference = (max if side == "buy" else min)(quote["price"], opposite) if opposite else quote["price"]
        executable = {**quote, "last_price": quote["price"], "price": reference}
        now = sources.now()
        if not confirm:
            research = self.risk_context(symbols, symbol, horizon, quote) if self.risk_context else {}
            preview, risk = self.book.preview_with_risk(symbol, side, quantity, executable, marks, research, horizon, now)
            reason = fill_block(quote, now, side, preview["fill_price"])
            return {"preview": preview, "risk": risk, "can_trade": not reason, "trade_reason": reason}
        preview = self.book.preview(symbol, side, quantity, executable, now=now)
        reason = fill_block(quote, now, side, preview["fill_price"])
        if reason:
            raise ValueError(reason)
        if Decimal(str(reference)) != expected:
            raise ValueError("报价已变化，请重新预览并确认")
        order = self.book.trade(symbol, stock["name"], side, quantity, executable, request_id, now=now)
        if on_fill:
            on_fill()
        return {"order": order}
