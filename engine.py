"""Close-to-close equity and index forecasting with chronological evaluation."""

from collections import deque
from datetime import date, datetime, time, timedelta, timezone
from math import expm1, isfinite, log, sqrt, tanh
from statistics import fmean, pstdev


SHANGHAI = timezone(timedelta(hours=8))
HORIZONS = (1, 5, 20)
NAMES = ("历史漂移", "均线趋势", "期限动量", "量价确认", "下行波动")
PRIOR = (0.0, 0.12, 0.06, 0.05, 0.04)
INTERVAL_KEYS = ("low", "base", "high", "return_low", "return_base", "return_high")


def _number(value):
    try:
        value = float(value)
        return value if isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _bounded(value, limit=1.0):
    return max(-limit, min(value, limit))


def _timestamp(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if len(str(value)) == 10:  # A date alone gives no earlier release time.
        stamp = datetime.combine(stamp.date(), time.max)
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=SHANGHAI)).astimezone(SHANGHAI)


def _closed_bars(rows, now):
    clean = {}
    for row in rows or ():
        if not isinstance(row, dict) or row.get("complete") is False:
            continue
        try:
            day = date.fromisoformat(row["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if day > now.date() or day == now.date() and now.time() < time(15):
            continue
        o, h, low, c = (_number(row.get(k)) for k in ("open", "high", "low", "close"))
        if None in (o, h, low, c) or not 0 < low <= min(o, c) <= max(o, c) <= h:
            continue
        volume = _number(row.get("volume"))
        clean[day] = (day, o, h, low, c, max(0, volume or 0))
    return [clean[day] for day in sorted(clean)]


def _factor_state(bars, closes, changes, i, horizon):
    # changes[i] is the close-to-close log return ending on bar i.
    sigma = max(0.001, pstdev(changes[i - 19:i + 1]))
    sma20 = fmean(closes[i - 19:i + 1])
    sma60 = fmean(closes[i - 59:i + 1])
    trend = tanh(log(sma20 / sma60) / (sigma * sqrt(20)))
    lookback = {1: 3, 5: 10, 20: 40}[horizon]
    momentum = tanh(log(closes[i] / closes[i - lookback]) / (sigma * sqrt(lookback)))
    # Zero volume receives no vote. Use balanced signed participation.
    signed_vol = total_vol = 0.0
    for j in range(i - 9, i + 1):
        volume = bars[j][5]
        signed_vol += _bounded(changes[j] / sigma) * volume
        total_vol += volume
    pressure = signed_vol / total_vol if total_vol else 0.0
    window = changes[i - 19:i + 1]
    downside = sum(min(0, x) ** 2 for x in window)
    total = sum(x * x for x in window)
    balance = 1 - 2 * downside / total if total else 0.0
    details = (
        "已兑现区间收益的收缩截距",
        f"20 日均线 {sma20:,.2f}，60 日均线 {sma60:,.2f}",
        f"过去 {lookback} 个交易日涨跌 {closes[i] / closes[i-lookback] - 1:+.2%}",
        f"10 日成交量加权涨跌强度 {pressure:+.2f}" if total_vol else "成交量缺失，因子贡献为零",
        f"20 日负收益平方和占比 {downside / total:.0%}" if total else "20 日收盘价持平",
    )
    return (1.0, trend, momentum, pressure, balance), sigma * sqrt(horizon), details


class _Ridge:
    """Rolling X'X and X'y from non-overlapping, fully realized returns."""

    def __init__(self, limit):
        self.limit = limit
        self.rows = deque()
        self.matrix = [[0.0] * 5 for _ in PRIOR]
        self.target = [0.0] * 5

    def _change(self, features, outcome, sign):
        for j, x in enumerate(features):
            self.target[j] += sign * x * outcome
            for k, other in enumerate(features):
                self.matrix[j][k] += sign * x * other

    def add(self, features, outcome):
        if len(self.rows) == self.limit:
            self._change(*self.rows.popleft(), -1)
        row = (features, _bounded(outcome, 3))
        self.rows.append(row)
        self._change(*row, 1)

    def coefficients(self):
        # The strictly positive ridge penalty ensures nonzero pivots.
        system = []
        for j, center in enumerate(PRIOR):
            penalty = 40 if j == 0 else 24
            row = self.matrix[j][:] + [self.target[j] + penalty * center]
            row[j] += penalty
            system.append(row)
        for j in range(5):
            pivot = system[j][j]
            system[j] = [v / pivot for v in system[j]]
            for k in range(5):
                if k != j:
                    multiple = system[k][j]
                    system[k] = [a - multiple * b for a, b in zip(system[k], system[j])]
        return [row[-1] for row in system]


def _quantile(values, fraction):
    p = (len(values) - 1) * fraction
    i = int(p)
    return values[i] + (p - i) * (values[min(i + 1, len(values) - 1)] - values[i])


def _band(errors):
    if len(errors) < 12:
        return -1.28, 1.28
    values = sorted(errors)
    # Include the point estimate even on one-sided samples.
    return min(0.0, _quantile(values, .1)), max(0.0, _quantile(values, .9))


def _history(bars, horizon):
    closes = [b[4] for b in bars]
    changes = [0.0] + [log(a / b) for a, b in zip(closes[1:], closes)]
    end = len(bars) - 1
    start = end - ((end - 59) // horizon) * horizon
    fit = _Ridge(max(30, 756 // horizon))
    errors = deque(maxlen=max(24, 504 // horizon))
    scores = deque(maxlen=max(25, 504 // horizon))
    previous = None
    for i in range(start, end + 1, horizon):
        if previous is not None:
            old_factors, scale, old_center, lo, hi, testable, calibrated = previous
            realized = log(closes[i] / closes[i - horizon]) / scale
            simple = closes[i] / closes[i - horizon] - 1
            if testable:
                hit = (old_center > 0) == (simple > 0) if old_center and simple else old_center == simple
                scores.append((bars[i-horizon][0], hit, simple > 0,
                               abs(simple - expm1(old_center * scale)), abs(simple),
                               lo <= realized - old_center <= hi if calibrated else None))
            errors.append(realized - old_center)
            fit.add(old_factors, realized)
        x, scale, details = _factor_state(bars, closes, changes, i, horizon)
        coefs = fit.coefficients()
        center = _bounded(sum(a * b for a, b in zip(x, coefs)), 1.25)
        lo, hi = _band(errors)
        previous = x, scale, center, lo, hi, len(fit.rows) >= 12, len(errors) >= 12
    coverage = [s[5] for s in scores if s[5] is not None]
    validation = {
        "n": len(scores),
        "hit_rate": fmean(s[1] for s in scores) if scores else None,
        "baseline_hit_rate": fmean(s[2] for s in scores) if scores else None,
        "mae": fmean(s[3] for s in scores) if scores else None,
        "baseline_mae": fmean(s[4] for s in scores) if scores else None,
        "coverage": fmean(coverage) if coverage else None,
        "from": scores[0][0].isoformat() if scores else None,
        "through": bars[-1][0].isoformat() if scores else None,
        "interval_n": len(coverage),
        "note": "每次仅使用当时已收盘的数据，训练满 12 个已兑现区间后开始检验，同期限窗口互不重叠。"
                "方向按价格模型中枢涨跌的正负判定，方向基准为始终看涨，绝对收益误差基准为点位持平。覆盖率检验目标 80% 的价格模型区间。"
                "当前情报修正、成交成本和止损执行未纳入检验。",
    }
    return x, coefs, details, center, scale, (lo, hi), len(errors), validation


def _category(kind):
    kind = str(kind).lower()
    if any(k in kind for k in ("earn", "fundament", "financ", "valu", "财报", "基本面", "估值")):
        return "基本面", 100
    if any(k in kind for k in ("industry", "sector", "行业", "产业")):
        return "行业景气", 30
    if any(k in kind for k in ("macro", "pmi", "宏观")):
        return "宏观景气", 45
    if any(k in kind for k in ("sentiment", "breadth", "情绪", "宽度")):
        return "市场情绪", 3
    if kind == "filing":
        return "公司公告", 30
    return "新闻与政策", 7


def eligible_evidence(item, cutoff, index_id=None, historical=False):
    """Point-in-time eligibility shared by the numeric model and Astra."""
    if not isinstance(item, dict) or not item.get("title") or not item.get("source"):
        return False
    now = _timestamp(cutoff)
    stamp = _timestamp(item.get("published_at"))
    if not now or not stamp or stamp > now:
        return False
    group, days = _category(item.get("kind") or item.get("category", ""))
    if (now.date() - stamp.date()).days > days:
        return False
    if historical and (group == "基本面" or "fetched_at" in item):
        acquired = _timestamp(item.get("fetched_at"))
        if not acquired or acquired > now:
            return False
    item_index = item.get("index_id")
    if item_index and index_id and item_index != index_id:
        return False
    scope = item.get("scope")
    return scope in ("index", "market", "constituent", "industry", "sector") or bool(item_index and scope == item_index)


def _context(rows, now, index_id, historical):
    groups, seen = {}, set()
    for item in rows or ():
        if not eligible_evidence(item, now, index_id, historical):
            continue
        stamp = _timestamp(item.get("published_at"))
        group, days = _category(item.get("kind") or item.get("category", ""))
        age = (now.date() - stamp.date()).days
        identity = str(item["title"]).strip()
        if identity in seen:
            continue
        signal = _number(item.get("signal"))
        confidence = _number(item.get("confidence"))
        if signal is None:
            continue
        scope = item.get("scope")
        item_index = item.get("index_id")
        if item_index and scope == item_index:
            scope = "index"
        relevance = {"index": 1.0, "market": .45, "industry": .22, "sector": .22,
                     "constituent": .10}[scope]
        if scope == "constituent" and (weight := _number(item.get("index_weight"))) is not None:
            relevance = min(.25, max(0, weight))
        confidence = .5 if confidence is None else max(0, min(1, confidence))
        # Disclosure completeness and the sample's weight in the full index
        # measure different kinds of missing information.
        coverage = _number(item.get("coverage"))
        if coverage is not None:
            confidence *= min(1, max(0, coverage))
        strength = _bounded(signal) * confidence * relevance * (0.5 ** (age / (days / 2)))
        if strength == 0:
            continue
        seen.add(identity)
        groups.setdefault(group, {}).setdefault(item["source"], []).append(strength)
    context = []
    for group, by_source in groups.items():
        count = sum(len(v) for v in by_source.values())
        score = fmean(fmean(v) for v in by_source.values())
        detail = f"{count} 条有方向证据，{len(by_source)} 个来源，按披露时效、适用范围和置信度折减"
        context.append((group, score, detail))
    return context


def _empty(horizon, bars, reason=None):
    reason = reason or f"当前有 {len(bars)} 根有效日线，模型至少需要 60 根。"
    return {
        "status": "insufficient", "horizon": horizon,
        "as_of": bars[-1][0].isoformat() if bars else None,
        "base_price": bars[-1][4] if bars else None, "direction": "数据不足", "score": None,
        "interval": dict.fromkeys(INTERVAL_KEYS), "factors": [],
        "strategy": {"action": "等待数据", "position": "暂缓新增风险敞口", "stop": None,
                     "trigger": reason, "stop_note": "暂无止损参考", "review": "更新日线后复核"},
        "validation": {"n": 0, "hit_rate": None, "baseline_hit_rate": None, "mae": None,
                       "baseline_mae": None, "coverage": None, "note": "尚无可用检验窗口。"},
        "notes": [reason],
    }


def analyze(market, horizon):
    """Analyze one instrument over 1, 5 or 20 trading sessions. Rates are fractions."""
    if isinstance(horizon, bool) or horizon not in HORIZONS:
        raise ValueError("预测周期可选 1、5、20 个交易日")
    horizon = int(horizon)
    meta = market.get("meta") or {}
    is_stock = market.get("kind") == "stock" or meta.get("instrument_type") == "stock"
    unit = "元" if is_stock else "点"
    now = _timestamp(meta.get("evaluated_at")) or datetime.now(SHANGHAI)
    bars = _closed_bars(market.get("bars"), now)
    if len(bars) < 60:
        return _empty(horizon, bars)
    if is_stock and meta.get("adjustment") != "qfq":
        return _empty(horizon, bars, "个股日线的前复权口径尚未确认。当前可查看走势图，待复权序列可用后评估。")
    x, coef, details, technical, scale, (lo, hi), calib_n, validation = _history(bars, horizon)
    day, _, _, _, close, _ = bars[-1]
    stale_reason = ""
    quote = market.get("quote") or {}
    quote_stamp = _timestamp(quote.get("asof"))
    quoted_previous = _number(quote.get("prev_close"))
    quoted_last = _number(quote.get("price"))
    if is_stock and meta.get("suspended"):
        stale_reason = "个股当前停牌或当日尚无有效成交"
    elif (now.date() - day).days > 7:
        stale_reason = "最新日线距评估日超过 7 个自然日"
    elif quote_stamp and quote_stamp.date() > day and (quote_stamp.date() < now.date() or quote_stamp.time() >= time(15)):
        stale_reason = "已有更新交易日的报价，日线尚未补齐该交易日收盘数据"
    elif quote_stamp and quote_stamp.date() > day and quoted_previous and abs(quoted_previous - close) > .02:
        stale_reason = "最新报价的昨收与日线末值不符"
    elif is_stock and quote_stamp and quote_stamp.date() == day and quote_stamp.time() >= time(15) and quoted_last and abs(quoted_last - close) > .011:
        stale_reason = "收盘报价与前复权末根日线价格不一致，等待核对除权或数据更新"
    elif meta.get("quote_status") in ("delayed", "cached", "snapshot", "unavailable"):
        stale_reason = "报价来源未确认当前有效行情"
    stale = bool(stale_reason)
    cutoff = datetime.combine(day, time(15), SHANGHAI) if stale else now
    evidence = _context(market.get("evidence"), cutoff, market.get("id") or meta.get("index_id"), stale)

    terms = [(name, "价格模型", v, w, detail) for name, v, w, detail in zip(NAMES, x, coef, details)]
    if evidence:
        # Up to 0.20 horizon volatilities even if every source agrees.
        terms.extend((group, "外部情报", value, 0.20 / len(evidence), detail)
                     for group, value, detail in evidence)
    center = _bounded(technical + sum(v * w for _, g, v, w, _ in terms if g == "外部情报"), 1.45)
    total_weight = sum(abs(w) for _, _, _, w, _ in terms) or 1
    factors = [{"name": name, "group": group, "weight": abs(w) / total_weight,
                "score": round(v * (1 if w > 0 else -1) * 100) if w else 0, "detail": detail,
                "contribution": v * w * scale}
               for name, group, v, w, detail in terms]
    score = round(100 * tanh(center))
    direction = "偏强" if score >= 15 else "偏弱" if score <= -15 else "震荡"
    untested = is_stock and validation["n"] == 0
    # Include both pre- and post-overlay envelopes; current evidence lacks a
    # timestamped historical archive for validation of its incremental edge.
    bounds = (min(technical, center) + lo, center, max(technical, center) + hi)
    if untested:
        # In particular an IPO can have 60 bars but zero validated forecasts.
        # Preserve observed factors while withholding any directional call.
        direction, score = "样本待积累", None
        bounds = (-1.28, 0.0, 1.28)
    returns = [expm1(k * scale) for k in bounds]
    interval = dict(zip(INTERVAL_KEYS, [round(close * (1 + r), 2) for r in returns] + returns))
    true_ranges = [max(bars[j][2] - bars[j][3], abs(bars[j][2] - bars[j-1][4]),
                       abs(bars[j][3] - bars[j-1][4])) for j in range(len(bars)-14, len(bars))]
    atr = fmean(true_ranges)
    stop_distance = max(atr * {1: 1.25, 5: 2.0, 20: 3.0}[horizon], close * .005, .01)
    stop = round(max(.01, close - stop_distance), 2)
    confirm = round(max(b[2] for b in bars[-min(horizon+2, 10):]), 2)
    validated = (validation["n"] >= 24 and validation["mae"] < validation["baseline_mae"]
                 and validation["hit_rate"] > validation["baseline_hit_rate"])
    if stale:
        action, position, trigger = "历史复盘", "等待新日线后再评估", f"数据截止 {day}，历史情景不可直接作为当前入场依据"
    elif untested:
        action, position, trigger = "等待样本积累", "暂缓新增个股敞口", f"{horizon} 日周期尚无成熟的样本外验证窗口，待更多交易日收盘后复核"
    elif direction == "偏弱":
        action, position, trigger = "防守观察", "暂停新增多头敞口", f"收盘跌破 {stop:,.2f} {unit}时，复核已有多头敞口并降低风险"
    elif direction == "偏强" and validated:
        action, position, trigger = "等待突破确认", "收盘确认后分批建立研究仓位", f"收盘突破近 {min(horizon+2, 10)} 日高点 {confirm:,.2f} {unit}后，再按可承受损失确定份额"
    elif direction == "偏强":
        action, position, trigger = "观察偏强信号", "保持观察仓位，暂缓加仓", "方向与误差检验尚未同时超过基准，等待下一收盘复核"
    else:
        action, position, trigger = "区间观察", "暂缓追涨，保留可用资金", f"观察能否收盘突破 {confirm:,.2f} {unit}，并在新日线到达后重新计算"
    execution = ("除权除息后按同口径重算保护价。停牌、跌停或跳空时，实际成交价可能偏离保护价。" if is_stock
                 else "指数点位需换算为跟踪产品价格，跳空会扩大损失。")
    strategy = {"action": action, "position": position, "trigger": trigger,
                "stop": stop, "stop_note": f"现有多头按参考收盘价下方 {close-stop:,.2f} {unit}设置复核线，"
                      "以同一价格口径下入场时确定的保护线为下限，收盘触及后按可成交价格减仓。" + execution,
                "review": f"每次收盘复核，最迟在第 {horizon} 个交易日收盘重新评估"}
    notes = [f"预测从 {day} 收盘 {close:,.2f} {unit}起算，区间为第 {horizon} 个交易日的收盘情景。",
             f"情报截止 {cutoff:%Y-%m-%d %H:%M}（上海），共 {len(evidence)} 个方向性类别参与。"
             if evidence else "未取得时点、范围及方向均可用的外部证据，本次采用价格模型。"]
    if not any(group == "基本面" for group, _, _ in evidence):
        notes.append("尚无纳入本次估计的财报或估值证据。")
    if calib_n < 12:
        notes.append("已兑现的误差不足 12 个，区间暂用 20 日波动率的 1.28 倍估算。")
    if is_stock:
        validation["note"] = (validation["note"].replace("点位持平", "股价持平")
                              + "个股检验使用本次取得的前复权序列，分红送转后历史基准可能与当时留档的价格不同。")
        notes.append("个股走势、验证收益与保护线使用前复权日线。发生分红送转后，历史价格基准会更新。")
    if untested:
        notes.insert(0, "本周期尚无可用样本外记录，中枢沿用收盘价，上下沿仅作波动参考。")
    if not validated:
        notes.append("当前检验尚未同时满足至少 24 个样本、方向命中率和平均绝对误差超过各自基准。")
    if stale:
        notes.append(stale_reason + "，展示历史复盘。")
    return {"status": "ok", "horizon": horizon, "as_of": day.isoformat(), "base_price": close,
            "interval_basis": "volatility" if untested else "forecast",
            "score": score, "direction": direction, "interval": interval, "factors": factors,
            "strategy": strategy, "validation": validation, "notes": notes, "historical": stale,
            "evidence_cutoff": cutoff.isoformat(), "calibration_n": calib_n, "atr14": round(atr, 2),
            "method": "逐期滚动岭回归 · 误差分位数校准", "evidence_groups": len(evidence)}
