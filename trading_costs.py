"""Deterministic RMB A-share paper fills. All monetary calculations use Decimal."""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP


CENT = Decimal("0.01")
HALF_CENT = CENT / 2
COMMISSION = Decimal("0.00025")  # Assumed all-in commission, excluding transfer fee.
MIN_COMMISSION = Decimal("5.00")
TRANSFER = Decimal("0.00001")
SELL_STAMP = Decimal("0.0005")
SLIPPAGE = Decimal("0.0005")


def _amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("金额必须为有效数值") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("金额必须为非负有限数值")
    return amount


def _shares(shares):
    if type(shares) is not int or shares < 1:
        raise ValueError("股数必须为正整数")


def _cents(amount):
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def execution(side, quote_price, shares):
    """Estimate a single buy/sell fill. cash_delta is signed and includes fees."""
    _shares(shares)
    if side not in ("buy", "sell"):
        raise ValueError("请选择买入或卖出")
    quote = _cents(_amount(quote_price))
    if quote < CENT:
        raise ValueError("报价至少为 0.01 元")
    # Apply adverse slippage symmetrically in whole quote ticks on both legs.
    shift = _cents(quote * SLIPPAGE)
    fill = quote + shift if side == "buy" else max(CENT, quote - shift)
    gross = fill * shares
    commission = max(MIN_COMMISSION, _cents(gross * COMMISSION))
    transfer_fee = _cents(gross * TRANSFER)
    stamp_tax = _cents(gross * SELL_STAMP) if side == "sell" else Decimal("0.00")
    fees = commission + transfer_fee + stamp_tax
    return dict(quote_price=quote, fill_price=fill, gross=gross, commission=commission,
                transfer_fee=transfer_fee, stamp_tax=stamp_tax, fees=fees,
                slippage=abs(fill - quote) * shares,
                cash_delta=(gross if side == "sell" else -gross) - fees)


def liquidation_proceeds(quote_price, shares, max_shares_per_order=None):
    """Net proceeds of selling a position across the fewest eligible orders."""
    _shares(shares)
    limit = shares if max_shares_per_order is None else max_shares_per_order
    _shares(limit)
    full, tail = divmod(shares, limit)
    proceeds = execution("sell", quote_price, limit)["cash_delta"] * full if full else Decimal(0)
    if tail:
        proceeds += execution("sell", quote_price, tail)["cash_delta"]
    return proceeds


def break_even_quote(cost_basis, shares, max_shares_per_order=None):
    """Smallest quoted sell price in cents covering the entire open cost basis."""
    _shares(shares)
    cost = _amount(cost_basis)
    limit = shares if max_shares_per_order is None else max_shares_per_order
    _shares(limit)
    orders = (shares + limit - 1) // limit
    # Fee rounding can improve proceeds by at most half a cent per component.
    # Start at a provable lower bound, then verify the first actual fill.
    target = cost - orders * 3 * HALF_CENT
    gross = max((target + orders * MIN_COMMISSION) / (1 - TRANSFER - SELL_STAMP),
                target / (1 - TRANSFER - SELL_STAMP - COMMISSION))
    lower = (gross / shares - HALF_CENT) / (1 - SLIPPAGE)
    quote = max(CENT, lower.quantize(CENT, rounding=ROUND_FLOOR))
    while liquidation_proceeds(quote, shares, limit) < cost:
        quote += CENT
    return quote


def stock_scenarios(symbol, entry_quote, base_quote, stop_quote):
    """One illustrative round trip, separate from the forecast of raw prices."""
    shares = 200 if symbol.startswith("sh688") else 100
    buy = execution("buy", entry_quote, shares)
    cost = -buy["cash_delta"]
    base_pnl = execution("sell", max(.01, base_quote), shares)["cash_delta"] - cost
    stop_pnl = execution("sell", stop_quote, shares)["cash_delta"] - cost
    return dict(shares=shares, entry_quote=float(buy["quote_price"]), entry_cash=float(cost),
                break_even=float(break_even_quote(cost, shares)), base_net_pnl=float(base_pnl),
                base_net_return=float(base_pnl / cost), stop_net_pnl=float(stop_pnl))
