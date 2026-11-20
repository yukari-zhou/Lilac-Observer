"""Dated issuer financials and matched industry releases for an A-share stock."""
from datetime import date, datetime, timedelta
import json
from math import isfinite, tanh
import re
from urllib.parse import urlencode

from fundamentals import REPORTS, SHANGHAI, _read
import sources


# Published by the issuer. The earnings PDF applies only to this original filing.
UNITREE_Q3 = "https://static.cninfo.com.cn/finalpage/2026-10-29/1225637442.PDF"
UNITREE_LISTING = "https://static.cninfo.com.cn/finalpage/2026-08-18/1225478658.PDF"
SECTORS = {
    "乘用车": "汽车制造业", "商用车": "汽车制造业", "汽车零部件": "汽车制造业",
    "半导体": "计算机、通信和其他电子设备制造业", "通信设备": "计算机、通信和其他电子设备制造业",
    "计算机设备": "计算机、通信和其他电子设备制造业", "消费电子": "计算机、通信和其他电子设备制造业",
    "专用设备": "专用设备制造业", "通用设备": "通用设备制造业",
    "白色家电": "电气机械和器材制造业", "电池": "电气机械和器材制造业",
    "白酒Ⅱ": "酒、饮料和精制茶制造业", "饮料乳品": "酒、饮料和精制茶制造业",
    "电力": "电力、热力生产和供应业",
}


def _number(value):
    if isinstance(value, (float, int)) and isfinite(value):
        return value
    return None


def _disclosed_report(rows, security, today):
    eligible = []
    for row in rows:
        if row.get("SECUCODE") != security:
            continue
        try:
            period = date.fromisoformat(row["REPORTDATE"][:10])
            notice = date.fromisoformat(row["NOTICE_DATE"][:10])
            updated = date.fromisoformat((row.get("UPDATE_DATE") or row["NOTICE_DATE"])[:10])
        except (KeyError, ValueError, TypeError):
            continue
        known = max(notice, updated)
        # Only a date is supplied. Even a same-day report may be an after-close filing.
        if today - timedelta(days=210) <= period <= notice <= known < today:
            eligible.append((period, known, notice, row))
    if not eligible:
        raise ValueError("无已披露的有效个股财报")
    period, known, notice, chosen = max(eligible, key=lambda r: (r[0], r[1]))
    return dict(code=chosen["SECURITY_CODE"], name=chosen["SECURITY_NAME_ABBR"],
                sector=chosen.get("BOARD_NAME") or "", period=period.isoformat(),
                disclosed_at=notice.isoformat(), known_on=known.isoformat(),
                revenue_yoy=_number(chosen.get("YSTZ")), profit_yoy=_number(chosen.get("SJLTZ")),
                revenue=_number(chosen.get("TOTAL_OPERATE_INCOME")), net_profit=_number(chosen.get("PARENT_NETPROFIT")))


def _collect(info):
    symbol = info["id"]
    code = info["code"]
    security = f"{code}.{info['exchange'].upper()}"
    params = dict(reportName="RPT_LICO_FN_CPD", filter=f'(SECUCODE="{security}")',
                  columns="SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,BOARD_NAME,REPORTDATE,NOTICE_DATE,UPDATE_DATE,"
                          "YSTZ,SJLTZ,TOTAL_OPERATE_INCOME,PARENT_NETPROFIT",
                  sortColumns="REPORTDATE", sortTypes="-1", pageSize=8)
    url = REPORTS + urlencode(params)
    rows = json.loads(_read(url))["result"]["data"]
    today = datetime.now(SHANGHAI).date()
    report = _disclosed_report(rows, security, today)
    terms, summary = [], []
    for name, amount, growth, weight, scale in (
        ("营收", report["revenue"], report["revenue_yoy"], .4, 20),
        ("归母净利润", report["net_profit"], report["profit_yoy"], .6, 30),
    ):
        item = name
        if amount is not None:
            item += f" {amount / 1e8:,.2f} 亿元"
        if growth is not None:
            item += f"（同比 {growth:+.2f}%）"
            terms.append((weight, tanh(growth / scale)))
        if amount is not None or growth is not None:
            summary.append(item)
    if not summary:
        raise ValueError("有效财务指标不足")
    total_weight = sum(w for w, _ in terms)
    # Loss-making issuers can report extreme growth off very small or negative bases.
    confidence = total_weight * (.45 if (report["net_profit"] or 0) <= 0 else .85)
    item = dict(scope=symbol, index_id=symbol, kind="fundamental", category="fundamental",
                title=f"{report['name']} · 截至 {report['period']} 的累计业绩",
                summary="年初至报告期末，" + "，".join(summary) + f"。披露日 {report['disclosed_at']}。"
                        + (f" 数据商行业分类为{report['sector']}。" if report["sector"] else ""),
                published_at=report["known_on"] + "T23:59:59+08:00",
                source="东方财富 · 上市公司定期报告", url=url, report=report,
                confidence=round(confidence, 4),
                signal=round(sum(w * v for w, v in terms)/total_weight, 4) if total_weight else None,
                fetched_at=datetime.now(SHANGHAI).isoformat(timespec="seconds"))
    if (symbol == "sh688836" and report["period"] == "2026-09-30"
            and report["known_on"] == report["disclosed_at"] == "2026-10-29"):
        item["publication_url"] = UNITREE_Q3
    return item


def evidence(info):
    """Fetch this issuer's latest eligible statement, reusing the market feed cache."""
    if not isinstance(info, dict) or not re.fullmatch(r"(?:sh|sz|bj)\d{6}", str(info.get("id", ""))):
        return None
    symbol = info["id"]
    if symbol != str(info.get("exchange", "")).lower() + str(info.get("code", "")):
        return None
    data, state, _ = sources._load("stock-fin-" + symbol, 21600, lambda: _collect(info))
    if not isinstance(data, dict) or data.get("index_id") != symbol:
        return None
    return {**data, "data_status": state}


def sector_exposure(release, financial):
    """Use aggregate production growth only when this issuer's sector can be matched."""
    report = financial["report"]
    sector = report["sector"]
    group = SECTORS.get(sector)
    classification = f"财报数据行业分类为{sector}"
    link = financial["url"]
    if financial["index_id"] == "sh688836" and sector == "自动化设备":
        group = "通用设备制造业"
        classification = "公司上市公告书披露行业为 C34 通用设备制造业"
        link = UNITREE_LISTING
    growth = _number(release.get("sector_yoy", {}).get(group))
    if growth is None:
        return release
    return {**release, "scope": financial["index_id"], "index_id": financial["index_id"],
            "confidence": .35, "signal": round(tanh(growth / 10), 4), "classification_url": link,
            "title": f"{group}景气 · {release['title']}",
            "summary": f"{classification}。本次发布中，{group}工业增加值同比 {growth:+.1f}%。"
                       "该指标衡量行业产出，个股订单与盈利还取决于产品结构、价格和成本。",
            "fetched_at": max(release.get("fetched_at", ""), financial["fetched_at"])}
