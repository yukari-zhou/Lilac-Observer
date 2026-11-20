"""Match the largest index constituents to dated earnings disclosures."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import sources


ROOT = Path(__file__).resolve().parent
SHANGHAI = timezone(timedelta(hours=8))
CSI = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/{0}closeweight.xls"
CNI = "https://www.cnindex.com.cn/sample-detail/download-history?indexcode={0}"
REPORTS = "https://datacenter-web.eastmoney.com/api/data/v1/get?"
_locks = defaultdict(Lock)
_refresh = {}


def _read(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    with urlopen(request, timeout=6) as response:
        return response.read(8_000_000)


def _weights(index_id):
    code = index_id[2:]
    if index_id.startswith("sz"):
        url = CNI.format(code)
        ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        with ZipFile(BytesIO(_read(url))) as workbook:
            sheet = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        rows = [[next(cell.itertext(), "") for cell in row] for row in sheet.iter(ns + "row")]
        if rows[0][:2] != ["日期", "样本代码"] or "权重" not in rows[0][5]:
            raise ValueError("国证权重表格式变化")
        records = [(r[0], r[1], r[2], float(r[5])) for r in rows[1:] if len(r) >= 6]
    else:
        import xlrd
        url = CSI.format(code)
        try:
            sheet = xlrd.open_workbook(file_contents=_read(url)).sheet_by_index(0)
        except xlrd.XLRDError as exc:
            raise ValueError("无效的中证权重文件") from exc
        if "权重" not in sheet.cell_value(0, 9) or "代码" not in sheet.cell_value(0, 4):
            raise ValueError("中证权重表格式变化")
        records = []
        for i in range(1, sheet.nrows):
            day, ticker, _, _, stock, name, _, _, _, weight = sheet.row_values(i)[:10]
            if str(ticker).zfill(6) == code:
                records.append((datetime.strptime(str(day), "%Y%m%d").date().isoformat(), str(stock), name, float(weight)))
    today = datetime.now(SHANGHAI).date().isoformat()
    stamp = max(row[0] for row in records if row[0] <= today)
    members = sorted((r for r in records if r[0] == stamp and r[1].isdigit() and r[3] > 0),
                     key=lambda r: r[3], reverse=True)
    return stamp, members[:20], url


def _collect(index_id):
    stamp, members, weights_url = _weights(index_id)
    codes = ",".join(f'"{r[1]}"' for r in members)
    params = dict(reportName="RPT_LICO_FN_CPD",
                  columns="SECURITY_CODE,SECURITY_NAME_ABBR,REPORTDATE,NOTICE_DATE,UPDATE_DATE,YSTZ,SJLTZ,BOARD_NAME",
                  filter=f"(SECURITY_CODE in ({codes}))", sortColumns="REPORTDATE", sortTypes="-1", pageSize=100)
    url = REPORTS + urlencode(params)
    disclosures = json.loads(_read(url))["result"]["data"]
    today = datetime.now(SHANGHAI).date()
    reports = {}
    for r in disclosures:
        report = str(r["REPORTDATE"])[:10]
        known = max(str(r["NOTICE_DATE"] or "")[:10], str(r["UPDATE_DATE"] or "")[:10])
        # The provider only states a date. Use it from the following day.
        if not known or not (today - timedelta(days=210)).isoformat() <= report <= known < today.isoformat():
            continue
        if all(isinstance(r[k], (int, float)) and math.isfinite(r[k]) for k in ("YSTZ", "SJLTZ")):
            reports.setdefault(r["SECURITY_CODE"], (r, known))
    holdings = []
    sectors = defaultdict(float)
    signal_sum = 0
    for _, code, name, weight in members:
        if code not in reports:
            continue
        r, known = reports[code]
        sector = r["BOARD_NAME"] or "其他"
        score = 0.6 * math.tanh(r["SJLTZ"] / 30) + 0.4 * math.tanh(r["YSTZ"] / 20)
        signal_sum += score * weight
        sectors[sector] += weight
        holdings.append(dict(code=code, name=name, sector=sector, weight_pct=weight,
                             revenue_yoy=round(r["YSTZ"], 2), profit_yoy=round(r["SJLTZ"], 2),
                             period=r["REPORTDATE"][:10], disclosed_at=r["NOTICE_DATE"][:10], known_on=known))
    coverage = sum(r["weight_pct"] for r in holdings)
    if not holdings or not 0 < coverage <= 100.1:
        raise ValueError("财报覆盖不足")
    sectors = sorted(sectors.items(), key=lambda s: -s[1])
    latest = max(stamp, max(r["known_on"] for r in holdings))
    leading = "、".join(f"{s} {w:.1f}%" for s, w in sectors[:3])
    return dict(category="fundamental", kind="fundamental", index_id=index_id, scope=index_id,
                published_at=latest + "T23:59:59+08:00", weights_date=stamp, weight_url=weights_url,
                title=f"权重股财报 · {len(holdings)} 家，覆盖指数 {coverage:.1f}%",
                summary=f"按 {stamp} 权重，从前 20 大样本匹配已披露财报。行业覆盖（占指数权重）：{leading}。"
                        f"样本内营收同比与归母净利润同比按 4:6 合成，覆盖率用于降低局部样本的影响。",
                source="国证指数 / 东方财富" if index_id.startswith("sz") else "中证指数 / 东方财富",
                url=url, coverage=round(coverage / 100, 4),
                confidence=round(min(1, coverage / sum(m[3] for m in members)), 4),
                signal=round(signal_sum / coverage, 4), holdings=holdings,
                sectors=[dict(name=s, weight_pct=round(w, 3)) for s, w in sectors],
                fetched_at=datetime.now(SHANGHAI).isoformat(timespec="seconds"))


def evidence(index_id):
    """Return a dated cache on upstream failure. Refresh at most once per six hours."""
    path = ROOT / "data" / "fundamentals" / (index_id + ".json")
    with _locks[index_id]:
        now = time.time()
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(saved["fetched_at"]).timestamp()
            if saved.get("index_id") != index_id or not saved.get("holdings") or fetched > now + 60:
                raise ValueError("无效的本地财报")
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            saved = None
        if sources.offline():
            return saved
        if saved and now - fetched < 21600:
            return saved
        if now < _refresh.get(index_id, 0):
            return saved
        try:
            result = _collect(index_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
            os.replace(handle.name, path)
            return result
        except (OSError, ValueError, ImportError, KeyError, TypeError, IndexError, RuntimeError,
                ElementTree.ParseError, BadZipFile):
            _refresh[index_id] = now + 300
            return saved


def sector_exposure(release, financial):
    """Map only directly comparable manufacturing subsectors from the covered sample."""
    groups = {
        "汽车制造业": {"乘用车", "商用车", "汽车零部件"},
        "计算机、通信和其他电子设备制造业": {"半导体", "通信设备", "消费电子", "计算机设备", "元件", "光学光电子"},
        "专用设备制造业": {"专用设备"},
        "通用设备制造业": {"通用设备"},
        "电气机械和器材制造业": {"电池", "白色家电"},
        "电力、热力生产和供应业": {"电力"},
        "酒、饮料和精制茶制造业": {"白酒Ⅱ", "饮料乳品"},
    }
    exposures = []
    for group, yoy in release.get("sector_yoy", {}).items():
        weight = sum(s["weight_pct"] for s in financial["sectors"] if s["name"] in groups.get(group, ()))
        if weight > 0:
            exposures.append((group, weight, yoy))
    coverage = sum(w for _, w, _ in exposures)
    if not coverage:
        return release
    contribution = sum(w * math.tanh(y / 10) for _, w, y in exposures) / coverage
    return {**release, "scope": financial["index_id"], "index_id": financial["index_id"],
            "signal": round(contribution, 4), "coverage": round(coverage / 100, 4), "confidence": .45,
            "weights_date": financial["weights_date"],
            "fetched_at": max(release.get("fetched_at", ""), financial["fetched_at"]),
            "summary": release["summary"] + f" 与权重股样本直接匹配的行业占指数 {coverage:.1f}%。",
            "basis": "按匹配行业的指数权重汇总产出同比，作为弱景气信号。产出增速与盈利和市场预期可能不同。"}
