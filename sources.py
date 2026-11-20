"""Public A-share market feeds. All display timestamps use exchange local time."""
import gzip
import html
import json
import math
import os
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from llm_config import env_setting, offline

CN = timezone(timedelta(hours=8))
_SYMBOLS = {
    "sh000001": "上证指数", "sz399001": "深证成指", "sh000300": "沪深300",
    "sz399006": "创业板指", "sh000016": "上证50", "sh000905": "中证500",
}
SNAPSHOTS = Path(__file__).resolve().parent / "data" / "market"
CACHE = Path(env_setting("CACHE_DIR") or os.environ.get("ASTRA_CACHE_DIR") or
             Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "astra-index" / "market-v1")
_LOCKS = {key: threading.Lock() for key in [*_SYMBOLS, "quotes", "news", "pmi"]}
_MEM = {}
_IO = ThreadPoolExecutor(max_workers=10, thread_name_prefix="market-source")
_NBS = "https://www.stats.gov.cn/sj/zxfb/"
_NEWS = "https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&page=1&page_size=16&tag_id=10"
_FAILURES = (OSError, ValueError, KeyError, IndexError, TypeError, OverflowError, EOFError, HTTPException)


def now():
    return datetime.now(CN)


def catalog():
    return [{"id": key, "name": name, "code": key[2:],
             "exchange": "SH" if key.startswith("sh") else "SZ"}
            for key, name in _SYMBOLS.items()]


def _get(url, encoding="utf-8", referer=None):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    with urlopen(Request(url, headers=headers), timeout=4) as response:
        raw = response.read(3_000_001)
    if len(raw) > 3_000_000:
        raise ValueError("response too large")
    return raw.decode(encoding)


def _read(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            item = json.load(handle)
        if isinstance(item, dict) and item.get("value") and 0 < item["fetched"] <= time.time() + 60:
            return item
    except _FAILURES:
        pass


def _save(path, item):
    path.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        with gzip.open(temp_path, "wt", encoding="utf-8") as fp:
            json.dump(item, fp, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _load(key, ttl, loader, fresh_after=0):
    """Single-flight cache with bounded network attempts, explicit fallback provenance."""
    is_offline = offline()
    with _LOCKS.setdefault(key, threading.Lock()):
        instant = time.time()
        slot = _MEM.get((key, is_offline))
        if slot and instant < slot[0] and slot[1] >= fresh_after:
            return slot[2:]
        filename = key + ".json.gz"
        stored = _read(CACHE / filename)
        if not is_offline and stored and fresh_after <= stored["fetched"] and instant - stored["fetched"] < ttl:
            result = (stored["value"], "latest", stored["fetched"])
            expiry = stored["fetched"] + ttl
            verified = stored["fetched"]
        else:
            verified = instant
            try:
                if is_offline:
                    raise OSError("offline")
                fresh = loader()
                if not fresh:
                    raise ValueError("empty")
                item = {"fetched": time.time(), "value": fresh}
                try:
                    _save(CACHE / filename, item)
                except OSError:
                    pass  # Read-only home still permits live data in memory.
                result, expiry = (fresh, "latest", item["fetched"]), instant + ttl
            except _FAILURES:
                snap = _read(SNAPSHOTS / filename)
                item = max((x for x in (stored, snap) if x), key=lambda x: x["fetched"], default=None)
                state = ("cached" if item is stored else "snapshot") if item else "unavailable"
                result, expiry = ((item or {}).get("value"), state, (item or {}).get("fetched")), instant + min(ttl, 45)
        _MEM[key, is_offline] = (expiry, verified, *result)
        return result


def _num(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite")
    return number


def _quotes_tencent():
    raw = _get("https://qt.gtimg.cn/q=" + ",".join(_SYMBOLS), "gb18030")
    out = {}
    for symbol, body in re.findall(r'v_((?:sh|sz)\d{6})="([^"]+)"', raw):
        fields = body.split("~")
        asof = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(tzinfo=CN)
        price, previous = map(_num, fields[3:5])
        if symbol not in _SYMBOLS or fields[2] != symbol[2:] or min(price, previous) <= 0 or asof > now() + timedelta(seconds=90):
            raise ValueError("invalid quote")
        out[symbol] = dict(id=symbol, name=_SYMBOLS[symbol], code=symbol[2:],
                           price=price, prev_close=previous, change=_num(fields[31]),
                           change_pct=_num(fields[32]), open=_num(fields[5]), high=_num(fields[33]),
                           low=_num(fields[34]), volume=_num(fields[6]),
                           amount=_num(fields[37])*10000, asof=asof.isoformat(),
                           source="腾讯财经", url="https://gu.qq.com/" + symbol)
    if out.keys() != _SYMBOLS.keys():
        raise ValueError("partial quotes")
    return out


def _quotes_sina():
    raw = _get("https://hq.sinajs.cn/list=" + ",".join(_SYMBOLS), "gb18030", "https://finance.sina.com.cn/")
    out = {}
    for symbol, body in re.findall(r'hq_str_((?:sh|sz)\d{6})="([^"]+)"', raw):
        fields = body.split(",")
        asof = datetime.fromisoformat(" ".join(fields[30:32])).replace(tzinfo=CN)
        previous, price = map(_num, fields[2:4])
        if min(previous, price) <= 0 or asof > now() + timedelta(seconds=90):
            raise ValueError("invalid quote")
        out[symbol] = dict(id=symbol, name=_SYMBOLS[symbol], code=symbol[2:], price=price, prev_close=previous,
                           change=round(price-previous, 4), change_pct=round(100*(price/previous-1), 3),
                           open=_num(fields[1]), high=_num(fields[4]), low=_num(fields[5]),
                           volume=_num(fields[8]), amount=_num(fields[9]), asof=asof.isoformat(),
                           source="新浪财经", url=f"https://finance.sina.com.cn/realstock/company/{symbol}/nc.shtml")
    if out.keys() != _SYMBOLS.keys():
        raise ValueError("partial quotes")
    return out


def _fetch_quotes():
    try:
        return _quotes_tencent()
    except _FAILURES:
        return _quotes_sina()


def _session(instant, asof):
    minutes = instant.hour * 60 + instant.minute
    if instant.weekday() >= 5 or minutes < 570 or minutes >= 900:
        return "closed"
    if asof.date() != instant.date():
        return "unknown"  # Includes exchange holidays and a delayed upstream feed.
    if minutes < 690:
        return "morning"
    return "break" if minutes < 780 else "afternoon"


def quotes():
    raw, state, fetched = _load("quotes", 15, _fetch_quotes)
    instant = now()
    out = {}
    for symbol in _SYMBOLS:
        item = (raw or {}).get(symbol)
        if not item:
            out[symbol] = None
            continue
        when = datetime.fromisoformat(item["asof"])
        session = _session(instant, when)
        age = (instant-when).total_seconds()
        status = state
        if state == "latest":
            if session in ("morning", "afternoon"):
                status = "live" if -5 <= age <= 90 else "delayed"
            elif (session == "unknown" or age > 4*86400 or
                  (instant.weekday() < 5 and instant.hour >= 15 and when.date() != instant.date())):
                status = "delayed"
        out[symbol] = {**item, "status": status, "session": session,
                       "fetched_at": datetime.fromtimestamp(fetched, CN).isoformat(timespec="seconds")}
    return out


def _history(symbol):
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,1400,qfq"
    payload = json.loads(_get(url))["data"][symbol]
    rows = payload["day"]
    bars = []
    instant = now()
    close = instant.replace(hour=15, minute=0, second=0, microsecond=0)
    vendor_quote = payload.get("qt", {}).get(symbol) or []
    confirmed_today = False
    if len(vendor_quote) > 30 and str(vendor_quote[30]).isdigit():
        vendor_time = datetime.strptime(vendor_quote[30], "%Y%m%d%H%M%S").replace(tzinfo=CN)
        confirmed_today = close <= vendor_time <= instant + timedelta(seconds=90)
    for row in rows:
        day = datetime.strptime(row[0], "%Y-%m-%d").date()
        if day > instant.date() or (day == instant.date() and (instant < close or not confirmed_today)):
            continue
        op, cl, hi, lo, vol = map(_num, row[1:6])
        if day == instant.date() and abs(cl - _num(vendor_quote[3])) > 0.011:
            continue
        if not (0 < lo <= min(op, cl) <= max(op, cl) <= hi and vol >= 0):
            raise ValueError("inconsistent daily bar")
        if bars and row[0] <= bars[-1]["date"]:
            raise ValueError("non-increasing bar dates")
        bars.append(dict(date=row[0], open=op, close=cl, high=hi, low=lo, volume=vol))
    if len(bars) < 60:
        raise ValueError("partial daily history")
    return bars


def _news():
    rows = json.loads(_get(_NEWS))["result"]["data"]["feed"]["list"]
    seen_days, result = set(), []
    for row in rows:
        full = html.unescape(re.sub("<[^>]+>", "", row["rich_text"])).strip()
        title = re.match(r"【([^】]+)】", full)
        ext = json.loads(row.get("ext") or "{}")
        url = ext.get("docurl", "")
        if urlsplit(url).scheme != "https" or urlsplit(url).hostname != "finance.sina.com.cn":
            url = f"https://wap.cj.sina.cn/pc/7x24/{int(row['id'])}"
        moment = datetime.fromisoformat(row["create_time"]).replace(tzinfo=CN)
        if moment > now() or moment.date() in seen_days:
            continue
        title = title.group(1) if title else full[:65]
        if not re.search(r"A股|全市场|沪指|上证|两市|沪深|创业板|科创50|深证|板块", title):
            continue
        seen_days.add(moment.date())
        # Keep the publisher headline and a short digest of explicitly reported breadth.
        breadth = re.search(r"(?:全市场|两市|沪深两市|全市)[^。；，]{0,12}?(?:超|逾|超过|近|有)?(\d{4})[余多]?只(?:个股|股票)?(?:飘)?(上涨|下跌|翻红|飘绿)", full)
        summary = "A 股市场快讯。正文可查看行业表现与盘面细节。"
        item = dict(kind="news", category="news", scope="market", title=title, summary=summary,
                    source="新浪财经", url=url, published_at=moment.isoformat())
        if breadth:
            item["summary"] = "快讯报道的市场广度：" + breadth.group(0) + "。家数来自新闻文本。"
            count, move = int(breadth[1]), breadth[2]
            # Only score the most recent report. This describes risk appetite, not an index return.
            if count >= 3500 and not result:
                sign = 1 if move in ("上涨", "翻红") else -1
                item.update(kind="sentiment", category="sentiment",
                            signal=round(sign*min(1, count/5500), 3), confidence=0.55,
                            basis="全市场同向个股达到3500家时，按报道家数÷5500限幅计分。")
        result.append(item)
        if len(result) == 3:
            break
    if not result:
        raise ValueError("empty market news")
    return result


def _releases(listing):
    return re.findall(r'<a\b[^>]*href=["\'](\./\d{6}/t\d{8}_\d+\.html)["\'][^>]*title=["\']([^"\']+)["\']', listing)


def _publication(url):
    page = _get(url)
    pub = re.search(r'<meta name="PubDate" content="([^"]+)"', page)
    if not pub:
        raise ValueError("publication time unavailable")
    moment = datetime.fromisoformat(pub[1].replace("/", "-")).replace(tzinfo=CN)
    if moment > now():
        raise ValueError("future release")
    body = re.sub(r"\s+", "", html.unescape(re.sub("<[^>]+>", "", page)))
    return moment, body


def _pmi():
    patterns = _releases(_get(_NBS))
    link, title = next(((link, title) for link, title in patterns
                        if "中国采购经理指数运行情况" in title), (None, None))
    if not link:
        # On busy release days the latest PMI can be on the next archive page.
        archive = _get(urljoin(_NBS, "index_1.html"))
        links = _releases(archive)
        link, title = next(((u, t) for u, t in links if "中国采购经理指数运行情况" in t), (None, None))
    if not link:
        raise ValueError("PMI publication unavailable")
    url = urljoin(_NBS, link)
    moment, body = _publication(url)
    match = re.search(r"(?<!非)制造业采购经理指数[（(]PMI[）)]为([\d.]+)[%％]", body)
    if not match:
        raise ValueError("PMI release schema changed")
    pmi = _num(match[1])
    change_match = re.search(r"比上月(下降|上升|提高|回落)([\d.]+)个百分点", body[match.end():match.end()+50])
    change = (-1 if change_match[1] in ("下降","回落") else 1)*_num(change_match[2]) if change_match else None
    signal = max(-1, min(1, (pmi - 50)/3 if change is None else (0.7*(pmi-50)+0.3*change)/3))
    note = f"制造业 PMI {pmi:.1f}%，荣枯线 50%。"
    if change is not None:
        note += f"环比{change:+.1f}个百分点。"
    result = [dict(kind="macro", category="macro", scope="market", title=title, summary=note,
                 published_at=moment.isoformat(), source="国家统计局", url=url,
                 signal=round(signal, 3), confidence=0.55, value=pmi, change_points=change,
                 basis="相对50的偏离与环比分别占70%、30%，除以3后限幅；无环比时只用偏离。")]
    industry = next(((u, t) for u, t in patterns if "规模以上工业增加值" in t), None)
    if industry:
        url = urljoin(_NBS, industry[0])
        try:
            published, body = _publication(url)
            sectors = ("汽车制造业", "计算机、通信和其他电子设备制造业", "专用设备制造业", "通用设备制造业",
                       "电气机械和器材制造业", "铁路、船舶、航空航天和其他运输设备制造业",
                       "化学原料和化学制品制造业", "医药制造业", "纺织业", "非金属矿物制品业",
                       "黑色金属冶炼和压延加工业", "有色金属冶炼和压延加工业", "电力、热力生产和供应业",
                       "农副食品加工业", "酒、饮料和精制茶制造业")
            sector_yoy = {}
            for sector in sectors:
                move = re.search(re.escape(sector) + r"(增长|下降)([\d.]+)%", body)
                if move:
                    sector_yoy[sector] = float(move[2]) * (-1 if move[1] == "下降" else 1)
            if sector_yoy:
                changes = [f"{name}{value:+.1f}%" for name, value in list(sector_yoy.items())[:4]]
                result.append(dict(kind="industry", category="industry", scope="market",
                                   title=industry[1], summary="分行业工业增加值同比：" + "，".join(changes) + "。",
                                   sector_yoy=sector_yoy, source="国家统计局", url=url, published_at=published.isoformat()))
        except _FAILURES:
            pass  # PMI remains independently usable when the industry release is unavailable.
    return result


def _minute_tape(symbol):
    url = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=" + symbol
    session = json.loads(_get(url))["data"][symbol]["data"]
    day = datetime.strptime(session["date"], "%Y%m%d").date()
    instant = now()
    points = []
    for row in session["data"]:
        clock, value, *_ = row.split()
        stamp = datetime.combine(day, datetime.strptime(clock, "%H%M").time(), CN)
        price = _num(value)
        if price <= 0 or stamp > instant:
            continue
        point = {"time": stamp.strftime("%H:%M"), "price": price}
        if points and point["time"] <= points[-1]["time"]:
            continue
        points.append(point)
    if not points:
        raise ValueError("no published minute prices")
    return {"date": day.isoformat(), "points": points,
            "asof": day.isoformat() + "T" + points[-1]["time"] + ":00+08:00"}


def minute_tape(symbol):
    if not re.fullmatch(r"(sh|sz|bj)\d{6}", symbol):
        raise ValueError("股票代码无效")
    data, status, _ = _load("minute-" + symbol, 30, lambda: _minute_tape(symbol))
    if data and status == "latest":
        instant = now()
        stamp = datetime.fromisoformat(data["asof"])
        session = _session(instant, stamp)
        if session == "unknown" or (instant - stamp).days > 4 or (
                session in ("morning", "afternoon") and (instant - stamp).total_seconds() > 150):
            status = "delayed"
    return {**(data or {"date": None, "points": [], "asof": None}), "status": status, "source": "腾讯财经"}


def _filings(symbol):
    code = symbol[2:]
    url = ("https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=15"
           "&page_index=1&ann_type=A&stock_list=" + code)
    records = json.loads(_get(url))["data"]["list"]
    result = []
    instant = now()
    for row in records:
        notice = row.get("art_code", "")
        if not re.fullmatch(r"AN\d+", notice) or not any(r.get("stock_code") == code for r in row.get("codes", [])):
            continue
        # Provider display_time carries a fourth colon before milliseconds. If
        # unavailable, conservatively wait until the notice date has elapsed.
        stamp = row.get("display_time")
        if stamp:
            published = datetime.fromisoformat(stamp[:19]).replace(tzinfo=CN)
        else:
            day = datetime.fromisoformat(row["notice_date"]).date()
            published = datetime.combine(day, datetime.max.time(), CN)
        if published > instant:
            continue
        result.append(dict(title=row["title"], summary="公告类别：" + "、".join(
            c["column_name"] for c in row.get("columns", []) if c.get("column_name")),
            source="东方财富 · 公司公告", published_at=published.isoformat(timespec="seconds"),
            kind="filing", category="filing", scope=symbol, index_id=symbol,
            url=f"https://data.eastmoney.com/notices/detail/{code}/{notice}.html"))
        if len(result) == 5:
            break
    return result


def company_filings(symbol):
    rows, status, acquired = _load("filings-" + symbol, 900, lambda: _filings(symbol))
    return [dict(row, data_status=status, fetched_at=datetime.fromtimestamp(acquired, CN).isoformat(timespec="seconds"))
            for row in rows or []], status


def public_evidence():
    p_news = _IO.submit(_load, "news", 120, _news)
    p_pmi = _IO.submit(_load, "pmi", 21600, _pmi)
    news, news_status, news_fetched = p_news.result()
    pmi, macro_status, macro_fetched = p_pmi.result()
    instant = now()
    evidence = [dict(row, data_status=status, fetched_at=datetime.fromtimestamp(acquired, CN).isoformat(timespec="seconds"))
                for rows, status, acquired in ((news, news_status, news_fetched), (pmi, macro_status, macro_fetched))
                for row in rows or [] if datetime.fromisoformat(row["published_at"]) <= instant]
    state = news_status if news_status == macro_status else "partial"
    return evidence, dict(evidence_status=state, news_status=news_status, macro_status=macro_status)


def market(index_id):
    if index_id not in _SYMBOLS:
        raise ValueError("未知指数")
    pending_quote = _IO.submit(quotes)
    # Reload soon after the close, including when the page stayed open across 15:00.
    t = now()
    close = t.replace(hour=15, minute=0, second=0, microsecond=0)
    # Force a new daily feed retrieval after 15:00. Poll more often during finalization.
    ttl = 90 if close <= t <= close + timedelta(minutes=30) else 1800
    p_history = _IO.submit(_load, index_id, ttl, lambda: _history(index_id),
                           close.timestamp() if t >= close else 0)
    evidence, context = public_evidence()
    quote = pending_quote.result()[index_id]
    bars, history_status, history_fetched = p_history.result()
    bars = bars or []
    instant = now()
    today = instant.date().isoformat()
    bars = [row for row in bars if row["date"] < today or (row["date"] == today and instant.hour >= 15)]
    warnings = []
    statuses = {"报价": quote["status"] if quote else "unavailable", "日线": history_status,
                "市场新闻": context["news_status"], "宏观数据": context["macro_status"]}
    for name, status in statuses.items():
        text = {"cached": "本次使用上次成功采集的本地缓存。", "snapshot": "本次使用随附历史快照。",
                "unavailable": "数据暂缺。", "delayed": "来源时标落后，实时性未确认。"}.get(status)
        if text:
            warnings.append(name + "：" + text)
    if quote and bars and quote["asof"][:10] > bars[-1]["date"]:
        warnings.append("最新报价与已完成日线基准日不同，模型以最近收盘日校准。")
    meta = dict(quote_status=statuses["报价"], history_status=history_status, **context,
                session=(quote or {}).get("session", "unknown"),
                asof=(quote or {}).get("asof"), evaluated_at=instant.isoformat(timespec="seconds"),
                history_source="腾讯财经", history_url=f"https://gu.qq.com/{index_id}",
                history_fetched_at=datetime.fromtimestamp(history_fetched, CN).isoformat(timespec="seconds") if history_fetched else None,
                history_asof=bars[-1]["date"] if bars else None, warnings=warnings, volume_unit="手")
    return dict(index={"id": index_id, "name": _SYMBOLS[index_id], "code": index_id[2:]},
                quote=quote, bars=bars, evidence=evidence, meta=meta)
