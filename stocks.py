"""A-share company directory and explicitly dated stock quotes/adjusted daily bars."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
import json
import os
from pathlib import Path
import re
import threading
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

import sources


SNAPSHOTS = Path(__file__).resolve().parent / "data" / "stocks"
_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="stock-feed")
_CACHE = {}
_LOCKS = {}
_QUOTES_LOCK = threading.Lock()
_QUOTE_MEM = {}
_FAILURES = sources._FAILURES + (BadZipFile, ET.ParseError)
_CNINFO = "https://www.cninfo.com.cn/new/data/szse_stock.json"
_SSE = "https://query.sse.com.cn/sseQuery/commonQuery.do?"
_SZSE = "https://www.szse.cn/api/report/ShowReport?"
_SINA = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center."
_HISTORY = "https://push2his.eastmoney.com/api/qt/stock/kline/get?"


def _offline():
    return sources.offline()


def _stamp(fetched):
    return datetime.fromtimestamp(fetched, sources.CN).isoformat(timespec="seconds") if fetched else None


def _files(key):
    filename = key + ".json.gz"
    return sources.CACHE / "stocks" / filename, SNAPSHOTS / filename


def _fallback(key):
    cache, snapshot = _files(key)
    items = [(state, item) for state, path in (("cached", cache), ("snapshot", snapshot))
             if (item := sources._read(path))]
    if not items:
        return None, "unavailable", 0
    state, item = max(items, key=lambda pair: pair[1]["fetched"])
    return item["value"], state, item["fetched"]


def _save(key, value, fetched):
    try:
        sources._save(_files(key)[0], {"value": value, "fetched": fetched})
    except OSError:
        pass


def _cached(key, ttl, loader, fresh_after=0):
    """Per-resource single flight. A failed feed never promotes old data to current."""
    with _LOCKS.setdefault(key, threading.Lock()):
        now = time.time()
        offline = _offline()
        mem = _CACHE.get((key, offline))
        if mem and mem[0] > now and mem[1] >= fresh_after:
            return mem[2]
        val, state, fetched = _fallback(key)
        refresh = not offline and (not val or fetched < fresh_after or now - fetched >= ttl or
                                   (key != "directory" and state == "snapshot"))
        expiry = now + 30
        if refresh:
            try:
                val = loader()
                if not val:
                    raise ValueError("empty upstream response")
                fetched = time.time()
                state = "latest"
                _save(key, val, fetched)
                expiry = fetched + ttl
            except _FAILURES:
                val, state, fetched = _fallback(key)
        elif val and not offline:
            expiry = fetched + ttl
            state = "latest" if state == "cached" else state
        result = (val, state, fetched)
        _CACHE[key, offline] = (expiry, now, result)
        return result


def _instrument(code, exchange, name, board, full="", listed="", english=""):
    return {"id": exchange.lower() + code, "kind": "stock", "code": code, "exchange": exchange,
            "name": name.strip(), "board": board, "full_name": full, "listed_on": listed,
            "english": english, "unit": "元"}


def _shanghai(stock_type):
    params = {"sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L", "STOCK_TYPE": stock_type,
              "type": "inParams", "isPagination": "true", "pageHelp.pageSize": 3000, "pageHelp.pageNo": 1}
    obj = json.loads(sources._get(_SSE + urlencode(params), referer="https://www.sse.com.cn/"))
    rows = obj["result"]
    if len(rows) != int(obj["pageHelp"]["total"]):
        raise ValueError("incomplete SSE directory")
    result = []
    today = sources.now().date().isoformat()
    for row in rows:
        code, listed = row["A_STOCK_CODE"], row.get("LIST_DATE", "")
        if not re.fullmatch(r"(60\d{4}|688\d{3})", code) or row["DELIST_DATE"] not in ("", "-"):
            continue
        if row["STATE_CODE_STOCK"] != "4" or not re.fullmatch(r"\d{8}", listed):
            continue
        day = datetime.strptime(listed, "%Y%m%d").date().isoformat()
        if day <= today:
            result.append(_instrument(code, "SH", row["COMPANY_ABBR"], "科创板" if stock_type == 8 else "沪市主板",
                                      row.get("FULL_NAME", ""), day, row.get("COMPANY_ABBR_EN", "")))
    return result


def _shenzhen():
    params = {"SHOWTYPE": "xlsx", "CATALOGID": "1110", "TABKEY": "tab1", "random": str(time.time_ns())}
    req = Request(_SZSE + urlencode(params), headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.szse.cn/"})
    with urlopen(req, timeout=6) as response:
        raw = response.read(4_000_000)
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with ZipFile(BytesIO(raw)) as book:
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
        strings = ["".join(el.itertext()) for el in ET.fromstring(book.read("xl/sharedStrings.xml"))]
    headings, out = {}, []
    for row in sheet.iter(ns + "row"):
        fields = {}
        for cell in row:
            col = cell.attrib["r"].rstrip("0123456789")
            text = "".join(cell.itertext()).strip()
            fields[col] = strings[int(text)] if cell.get("t") == "s" else text
        if not headings:
            headings = {v: k for k, v in fields.items()}
            continue
        code = fields.get(headings["A股代码"], "")
        if not re.fullmatch(r"(00|30)\d{4}", code):
            continue
        day = fields.get(headings["A股上市日期"], "")
        if day and day <= sources.now().date().isoformat():
            out.append(_instrument(code, "SZ", fields[headings["A股简称"]], fields[headings["板块"]].replace("主板","深市主板"),
                                   fields.get(headings["公司全称"], ""), day))
    return out


def _beijing():
    total = int(json.loads(sources._get(_SINA + "getHQNodeStockCount?node=hs_bjs")))
    out = []
    for page in range(1, (total + 99) // 100 + 1):
        params = dict(page=page, num=100, sort="symbol", asc=1, node="hs_bjs")
        rows = json.loads(sources._get(_SINA + "getHQNodeData?" + urlencode(params)))
        for row in rows:
            code = row["code"]
            if re.fullmatch(r"920\d{3}", code) and row["symbol"] == "bj" + code:
                out.append(_instrument(code, "BJ", row["name"], "北交所"))
    if len({s["id"] for s in out}) != total:
        raise ValueError("incomplete BSE directory")
    return out


def _directory():
    jobs = [_POOL.submit(_shanghai, 1), _POOL.submit(_shanghai, 8),
            _POOL.submit(_shenzhen), _POOL.submit(_beijing)]
    try:
        cninfo = json.loads(sources._get(_CNINFO))["stockList"]
        lookup = {r["code"]: r for r in cninfo if r["category"] == "A股"}
    except _FAILURES:
        lookup = {}
    rows = {}
    for future in jobs:
        group = future.result()
        if not group:
            raise ValueError("incomplete exchange directory")
        for stock in group:
            basic = lookup.get(stock["code"], {})
            stock["pinyin"] = basic.get("pinyin", "")
            stock["org_id"] = basic.get("orgId", "")
            rows[stock["id"]] = stock
    return rows


def _catalog():
    return _cached("directory", 86400, _directory)[0] or {}


def directory_available():
    return bool(_catalog())


def resolve(stock_id):
    """Only return instruments in the exchange-qualified A-share directory."""
    return _catalog().get(str(stock_id).lower())


def _norm(s):
    return re.sub(r"[\s._-]+", "", unicodedata.normalize("NFKC", str(s)).casefold())


def search(query):
    # STAR-board quote names may carry a voting-rights/profitability suffix.
    query = re.sub(r"(?<=[\u4e00-\u9fff])[-－][UWD]{1,3}$", "", str(query).strip(), flags=re.I)
    query = _norm(query)
    if not query:
        return []
    matches = []
    for symbol, stock in _catalog().items():
        fields = [stock["name"], stock["code"], symbol, stock["code"] + stock["exchange"],
                  stock.get("pinyin", ""), stock.get("full_name", ""), stock.get("english", "")]
        fields = [_norm(f) for f in fields if f]
        rank = min((0 if f == query else 1 if f.startswith(query) else 2 for f in fields if query in f), default=3)
        if rank < 3:
            matches.append((rank, symbol, stock))
    return [s for _, _, s in sorted(matches)[:30]]


def _tencent_quotes(ids):
    text = sources._get("https://qt.gtimg.cn/q=" + ",".join(ids), "gb18030")
    found = {}
    for symbol, body in re.findall(r'v_((?:sh|sz|bj)\d{6})="([^"]*)"', text):
        if symbol not in ids:
            continue
        f = body.split("~")
        try:
            if f[2] != symbol[2:]:
                continue
            stamp = datetime.strptime(f[30], "%Y%m%d%H%M%S").replace(tzinfo=sources.CN)
            price, previous = map(sources._num, f[3:5])
            op, hi, lo = map(sources._num, (f[5], f[33], f[34]))
            volume = sources._num(f[6])
            # Tencent reports STAR-board volume in shares; other A shares use lots.
            if symbol.startswith("sh688"):
                volume /= 100
            if min(price, previous) <= 0 or stamp > sources.now() + timedelta(seconds=90):
                continue
            suspended = (not volume and not op and not hi and not lo and
                         (stamp.hour, stamp.minute) >= (9, 30))
            def book_price(i):
                try:
                    level = sources._num(f[i])
                    return level if level > 0 else None
                except (IndexError, ValueError):
                    return None
            found[symbol] = dict(id=symbol, name=f[1], code=f[2], price=price, prev_close=previous,
                                 change=sources._num(f[31]), change_pct=sources._num(f[32]), open=op or None,
                                 high=hi or None, low=lo or None, volume=volume, amount=sources._num(f[37])*10000,
                                 asof=stamp.isoformat(), suspended=suspended, source="腾讯财经",
                                 bid=book_price(9), ask=book_price(19),
                                 limit_up=book_price(47), limit_down=book_price(48),
                                 url=f"https://gu.qq.com/{symbol}")
        except _FAILURES:
            continue
    return found


def _quote_state(value, provenance, fetched):
    if not value:
        return None
    stamp = datetime.fromisoformat(value["asof"])
    now = sources.now()
    age = (now - stamp).total_seconds()
    session = sources._session(now, stamp)
    status = provenance
    if provenance == "latest":
        if value.get("suspended"):
            status = "suspended"
        elif session in ("morning", "afternoon"):
            status = "live" if -5 <= age <= 90 else "delayed"
        elif session == "unknown" or age > 4*86400 or (now.weekday() < 5 and now.hour >= 15 and stamp.date() != now.date()):
            status = "delayed"
    return {**value, "status": status, "session": session, "fetched_at": _stamp(fetched)}


def quotes(ids):
    catalog = _catalog()
    ids = list(dict.fromkeys(ids))
    symbols = list(dict.fromkeys(s for s in ids if s in catalog))
    offline = _offline()
    now = time.time()
    with _QUOTES_LOCK:
        missing = []
        for s in symbols:
            if _QUOTE_MEM.get((s, offline), (0,))[0] <= now:
                missing.append(s)
        for i in range(0, len(missing), 60):
            batch = missing[i:i+60]
            try:
                values = {} if offline else _tencent_quotes(batch)
            except _FAILURES:
                values = {}
            for s in batch:
                key = s + "-quote"
                if s in values:
                    value, state, fetched = values[s], "latest", time.time()
                    _save(key, value, fetched)
                else:
                    value, state, fetched = _fallback(key)
                _QUOTE_MEM[s, offline] = (now + 15, value, state, fetched)
        result = {s: _quote_state(*_QUOTE_MEM[s, offline][1:]) for s in symbols}
        return {s: result.get(s) for s in ids}


def _bars(rows, quote):
    """Discard partial current sessions and preserve a continuous positive-price tail."""
    instant, out = sources.now(), []
    today = instant.date().isoformat()
    close = instant.replace(hour=15, minute=0, second=0, microsecond=0)
    asof = datetime.fromisoformat(quote["asof"]) if quote else None
    for row in rows:
        day = datetime.strptime(row[0], "%Y-%m-%d").date().isoformat()
        op, cl, hi, lo, vol = map(sources._num, row[1:6])
        if day > today or (day == today and
                           (instant < close or not asof or asof < close or quote.get("suspended") or
                            abs(cl - quote["price"]) > .011)):
            continue
        if lo <= 0:
            out.clear()  # Old forward-adjusted cash-dividend prices may be nonpositive.
            continue
        if not (lo <= min(op, cl) <= max(op, cl) <= hi and vol >= 0) or (out and day <= out[-1]["date"]):
            raise ValueError("invalid or unordered stock bars")
        out.append(dict(date=day, open=op, close=cl, high=hi, low=lo, volume=vol))
    if not out:
        raise ValueError("no completed stock bars")
    return out[-1400:]


def _history(symbol, quote):
    market_no = "1" if symbol.startswith("sh") else "0"
    code = symbol[2:]
    params = dict(secid=f"{market_no}.{code}", klt=101, fqt=1, beg=0, end=20500101, lmt=1400,
                  fields1="f1,f2,f3,f4,f5,f6", fields2="f51,f52,f53,f54,f55,f56,f57")
    url = _HISTORY + urlencode(params)
    try:
        data = json.loads(sources._get(url, referer="https://quote.eastmoney.com/"))["data"]
        if not data or data["code"] != code or str(data["market"]) != market_no:
            raise ValueError("stock identity mismatch")
        bars = _bars((s.split(",") for s in data["klines"]), quote)
        return dict(bars=bars, adjustment="qfq", history_basis="前复权日线", history_source="东方财富", history_url=url)
    except _FAILURES:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,1400,qfq"
        data = json.loads(sources._get(url))["data"][symbol]
        adjusted = bool(data.get("qfqday"))
        rows = data["qfqday"] if adjusted else data["day"]
        bars = _bars(rows, quote)
        if symbol.startswith("sh688"):
            for bar in bars:
                bar["volume"] /= 100
        return dict(bars=bars, adjustment="qfq" if adjusted else "raw",
                    history_basis="前复权日线" if adjusted else "原始日线（复权口径未确认）",
                    history_source="腾讯财经", history_url=url)


def market(stock_id, watched=None):
    stock = resolve(stock_id)
    removed = False
    if not stock:
        if (not watched or watched.get("id") != stock_id or watched.get("kind") != "stock" or
                not re.fullmatch(r"(sh|sz|bj)\d{6}", stock_id)):
            raise ValueError("未找到该上市公司")
        stock = watched
        removed = True
    symbol = stock["id"]
    quote = None if removed else quotes([symbol]).get(symbol)
    qstatus = (quote or {}).get("status", "unavailable")
    instant = sources.now()
    close = instant.replace(hour=15, minute=0, second=0, microsecond=0)
    ttl = 60 if close <= instant < close + timedelta(minutes=30) else 1800
    if removed:
        hist, hstatus, fetched = _fallback(symbol + "-history")
    else:
        hist, hstatus, fetched = _cached(symbol + "-history", ttl, lambda: _history(symbol, quote),
                                        close.timestamp() if instant >= close else 0)
    hist = hist or {}
    bars = hist.get("bars", [])
    warnings = ["当前在市证券目录未收录该标的，已停止获取现价，仅显示本机已有历史。"] if removed else []
    for name, status in (("股价", qstatus), ("日线", hstatus)):
        reason = {"cached": "使用最近一次成功采集的缓存", "snapshot": "使用随附历史快照",
                  "unavailable": "数据暂缺", "delayed": "报价时间滞后", "suspended": "来源未显示当日成交"}.get(status)
        if reason:
            warnings.append(name + "：" + reason + "。")
    if hist.get("adjustment") == "raw":
        warnings.append("当前日线的复权口径未确认，跨除权除息日涨跌可能失真。")
    if quote and bars and quote["asof"][:10] > bars[-1]["date"]:
        warnings.append("最新报价与最近收盘日属于不同时点。")
    meta = {k: hist.get(k) for k in ("adjustment", "history_basis", "history_source", "history_url")}
    meta.update(history_status=hstatus, history_asof=bars[-1]["date"] if bars else None,
                history_fetched_at=_stamp(fetched), section="stock", asof=(quote or {}).get("asof"),
                quote_status=qstatus, evidence_status="unavailable", session=(quote or {}).get("session", "unknown"),
                suspended=bool((quote or {}).get("suspended")), evaluated_at=instant.isoformat(timespec="seconds"),
                warnings=warnings, volume_unit="手", price_unit="元")
    return dict(id=symbol, kind="stock", index=stock, quote=quote, bars=bars, evidence=[], meta=meta)
