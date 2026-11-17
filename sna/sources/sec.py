"""SEC EDGAR: free and keyless, but SEC asks every client to send a User-Agent that names who it is with a contact
email (SEC_USER_AGENT) and to stay under 10 requests a second (netio paces www.sec.gov and data.sec.gov).

What is read: the ticker map, the company's recent filing list (submissions JSON), Form 4 XML for insider trades and
filing index pages for who filed a 13D/13G or Form 144. Filings never change once accepted, so documents are cached
for 30 days; the filing list for 30 minutes.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from .. import config, netio, timeutil
from . import Skip, SourceError

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{name}"
COMPANY_PAGE = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}&owner=include&count=40"
DOC_TTL = 30 * 86400
FIELDS = ("accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "items", "primaryDocument",
          "primaryDocDescription")

FORM_13DG = re.compile(r"^(SC 13[DG]|SCHEDULE 13[DG])(/A)?$")
TX_CODES = {
    "P": "公开市场买入", "S": "公开市场卖出", "A": "授予或奖励", "M": "行权或 RSU 转股", "F": "缴税扣股",
    "G": "赠与", "D": "处置给公司", "C": "衍生品转换", "X": "行使价内期权", "O": "行使价外期权",
    "J": "其他", "I": "自主交易", "W": "遗嘱或继承", "Z": "信托存取", "K": "股权互换", "V": "自愿提前申报",
    "L": "小额收购", "E": "短期衍生品到期", "H": "长期衍生品到期或注销", "U": "要约收购处置",
}
ITEMS_8K = {
    "1.01": "签订重大协议", "1.02": "终止重大协议", "1.03": "破产或接管", "1.04": "矿山安全", "1.05": "网络安全事件",
    "2.01": "完成收购或处置资产", "2.02": "经营业绩", "2.03": "新增重大债务", "2.04": "债务加速触发",
    "2.05": "退出或重组成本", "2.06": "重大减值", "3.01": "退市或不符合上市标准通知", "3.02": "未注册股份发行",
    "3.03": "股东权利变更", "4.01": "更换审计师", "4.02": "已发布财报不可再依赖", "5.01": "控制权变更",
    "5.02": "董事或高管变动", "5.03": "章程或财年变更", "5.04": "福利计划交易暂停", "5.05": "道德守则变更",
    "5.06": "空壳公司状态变更", "5.07": "股东投票结果", "5.08": "股东提名", "7.01": "Reg FD 披露",
    "8.01": "其他事项", "9.01": "财务报表和附件",
}
OTHER_FORMS = {
    "144": "拟出售受限股", "144/A": "拟出售受限股（修正）", "S-3": "储架注册（可能增发）", "S-3ASR": "储架注册（自动生效）",
    "S-1": "证券注册", "S-4": "并购相关注册", "424B1": "发行说明书", "424B2": "发行说明书", "424B3": "发行说明书",
    "424B4": "发行说明书", "424B5": "发行说明书（增发或发债）", "424B7": "发行说明书（股东出售）", "10-K": "年报",
    "10-Q": "季报", "10-K/A": "年报（修正）", "10-Q/A": "季报（修正）", "20-F": "外国公司年报", "6-K": "外国公司临时报告",
    "DEF 14A": "股东大会委托书", "DEFA14A": "委托书补充材料", "SC TO-T": "第三方要约收购", "SC TO-I": "公司回购要约",
    "SC 14D9": "对要约收购的回应", "425": "并购沟通材料", "NT 10-K": "年报延迟提交", "NT 10-Q": "季报延迟提交",
}

_map_lock = threading.Lock()
_ticker_map: tuple[float, dict] | None = None


def _headers() -> dict:
    ua = config.key("SEC_USER_AGENT")
    if not ua:
        raise Skip("未设置 SEC_USER_AGENT（SEC 要求写明身份和邮箱，例如 \"Tim Research tim@example.com\"）")
    return {"User-Agent": ua}


def sec_symbol(symbol: str) -> str:
    return symbol.upper().replace(".", "-")


def company(ctx, symbol: str) -> dict:
    """CIK and SEC name of a ticker, from SEC's ticker map (cached for a week)."""
    global _ticker_map
    resp = ctx.get(TICKERS_URL, headers=_headers(), ttl=7 * 86400)
    with _map_lock:
        if _ticker_map is None or _ticker_map[0] != resp.fetched_at:
            data = resp.json()
            rows = data.values() if isinstance(data, dict) else data
            mapping = {}
            for row in rows:
                if isinstance(row, dict) and row.get("ticker"):
                    mapping.setdefault(str(row["ticker"]).upper(), row)
            _ticker_map = (resp.fetched_at, mapping)
        row = _ticker_map[1].get(sec_symbol(symbol))
    if not row:
        raise SourceError(f"SEC 代码表里没有 {symbol}（ETF、基金和部分外国公司不在表里）")
    cik = int(row["cik_str"])
    return {"cik": cik, "name": row.get("title"), "ticker": row.get("ticker"),
            "url": COMPANY_PAGE.format(cik=cik)}


def filing_list(ctx, cik: int) -> list[dict]:
    """The company's recent filings (SEC keeps at least the last year or 1,000 filings here), newest first."""
    data = ctx.get(SUBMISSIONS_URL.format(cik=cik), headers=_headers(), ttl=1800).json()
    recent = ((data or {}).get("filings") or {}).get("recent") or {}
    columns = {k: recent.get(k) or [] for k in FIELDS}
    n = len(columns["accessionNumber"])
    rows = []
    for i in range(n):
        row = {k: (columns[k][i] if i < len(columns[k]) else None) for k in FIELDS}
        acc = row["accessionNumber"] or ""
        row["folder"] = acc.replace("-", "")
        row["index_url"] = ARCHIVE.format(cik=cik, folder=row["folder"], name=f"{acc}-index.htm")
        doc = (row.get("primaryDocument") or "").split("/")[-1]
        row["doc_url"] = ARCHIVE.format(cik=cik, folder=row["folder"], name=row["primaryDocument"]) if doc else None
        row["raw_doc"] = doc
        rows.append(row)
    rows.sort(key=lambda r: (r.get("acceptanceDateTime") or r.get("filingDate") or ""), reverse=True)
    return rows


def _since(rows: list[dict], days: int) -> list[dict]:
    cutoff = timeutil.today_et() - dt.timedelta(days=days)
    return [r for r in rows if (timeutil.parse_date(r.get("filingDate")) or dt.date.min) >= cutoff]


# ---------- Form 4 ----------

def _text(el, path: str):
    found = el.find(path) if el is not None else None
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value or None


def _flag(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "y", "yes")


def _float(value):
    try:
        return float(str(value).replace(",", "")) if value not in (None, "") else None
    except ValueError:
        return None


def parse_form4(xml_bytes: bytes) -> dict:
    """Owners, the 10b5-1 flag and the transactions of a Form 4 (or 4/A) ownershipDocument."""
    root = ET.fromstring(xml_bytes)
    if root.tag != "ownershipDocument":
        raise SourceError(f"不是 Form 4 文档（根节点 {root.tag}）")
    owners = []
    for o in root.findall("reportingOwner"):
        rel = o.find("reportingOwnerRelationship")
        roles = []
        if _flag(_text(rel, "isDirector")):
            roles.append("董事")
        if _flag(_text(rel, "isOfficer")):
            roles.append(_text(rel, "officerTitle") or "高管")
        if _flag(_text(rel, "isTenPercentOwner")):
            roles.append("10% 以上股东")
        if _flag(_text(rel, "isOther")):
            roles.append(_text(rel, "otherText") or "其他")
        owners.append({"name": _text(o, "reportingOwnerId/rptOwnerName"),
                       "cik": _text(o, "reportingOwnerId/rptOwnerCik"), "roles": roles})
    footnotes = " ".join((f.text or "") for f in root.iter("footnote"))
    plan = _flag(_text(root, "aff10b5One")) or bool(re.search(r"10b5-?1", footnotes, re.I))
    transactions = []
    for table, derivative in (("nonDerivativeTable/nonDerivativeTransaction", False),
                              ("derivativeTable/derivativeTransaction", True)):
        for tx in root.findall(table):
            shares = _float(_text(tx, "transactionAmounts/transactionShares/value"))
            price = _float(_text(tx, "transactionAmounts/transactionPricePerShare/value"))
            if derivative and price is None:
                price = _float(_text(tx, "conversionOrExercisePrice/value"))
            code = _text(tx, "transactionCoding/transactionCode")
            transactions.append({
                "security": _text(tx, "securityTitle/value"), "date": _text(tx, "transactionDate/value"),
                "code": code, "code_label": TX_CODES.get(code or "", code or ""), "shares": shares, "price": price,
                "value": round(shares * price, 2) if shares is not None and price else None,
                "acquired": _text(tx, "transactionAmounts/transactionAcquiredDisposedCode/value"),
                "after": _float(_text(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                "direct": _text(tx, "ownershipNature/directOrIndirectOwnership/value"), "derivative": derivative})
    return {"owners": owners, "plan_10b5_1": plan, "transactions": transactions,
            "symbol": _text(root, "issuer/issuerTradingSymbol")}


def _form4(ctx, cik: int, row: dict):
    if not row.get("raw_doc", "").lower().endswith(".xml"):
        return {"error": "主文件不是 XML"}
    url = ARCHIVE.format(cik=cik, folder=row["folder"], name=row["raw_doc"])
    try:
        return parse_form4(ctx.get(url, headers=_headers(), ttl=DOC_TTL).body)
    except (netio.FetchError, SourceError, ET.ParseError) as e:
        return {"error": str(e)}


def insiders(ctx, symbol: str, days: int = 90, max_filings: int = 40) -> dict:
    comp = company(ctx, symbol)
    picks = [r for r in _since(filing_list(ctx, comp["cik"]), days) if r.get("form") in ("4", "4/A")][:max_filings]
    with ThreadPoolExecutor(max_workers=4) as pool:
        docs = list(pool.map(lambda r: _form4(ctx, comp["cik"], r), picks))
    rows, failed = [], 0
    for filing, doc in zip(picks, docs):
        if not doc or doc.get("error"):
            failed += 1
            continue
        names = "; ".join(o["name"] for o in doc["owners"] if o.get("name")) or "未知"
        roles = sorted({r for o in doc["owners"] for r in o["roles"]})
        for tx in doc["transactions"]:
            rows.append({**tx, "owner": names, "roles": roles, "plan_10b5_1": doc["plan_10b5_1"],
                         "filed": filing.get("filingDate"), "form": filing.get("form"),
                         "url": filing["index_url"]})
    rows.sort(key=lambda r: (r.get("date") or "", r.get("filed") or ""), reverse=True)
    return {"company": comp, "window_days": days, "filings": len(picks), "failed": failed,
            "capped": len(picks) >= max_filings, "summary": summarize(rows), "transactions": rows,
            "count": len(rows)}


def summarize(rows: list[dict]) -> dict:
    """Open-market buys (P) and sells (S) over the window, with the part of sells made under a 10b5-1 plan."""
    out = {"buy": {"n": 0, "shares": 0.0, "value": 0.0, "people": set()},
           "sell": {"n": 0, "shares": 0.0, "value": 0.0, "people": set()},
           "sell_plan": {"n": 0, "value": 0.0}, "other": {}}
    for r in rows:
        if r.get("derivative"):
            continue
        code = r.get("code")
        side = "buy" if code == "P" else "sell" if code == "S" else None
        if side:
            s = out[side]
            s["n"] += 1
            s["shares"] += r.get("shares") or 0
            s["value"] += r.get("value") or 0
            s["people"].add(r.get("owner"))
            if side == "sell" and r.get("plan_10b5_1"):
                out["sell_plan"]["n"] += 1
                out["sell_plan"]["value"] += r.get("value") or 0
        elif code:
            out["other"][code] = out["other"].get(code, 0) + 1
    for side in ("buy", "sell"):
        out[side]["people"] = len(out[side]["people"])
    return out


# ---------- 13D / 13G, 8-K, other filings ----------

_COMPANY = re.compile(r'class="companyName">\s*([^<(]+?)\s*\(([^)<]{3,20})\)', re.I)


def filers(ctx, cik: int, row: dict) -> list[dict]:
    """Names and roles on a filing's index page, e.g. [{"name": "VANGUARD GROUP INC", "role": "Filed by"}]."""
    try:
        page = ctx.get(row["index_url"], headers=_headers(), ttl=DOC_TTL).text()
    except netio.FetchError:
        return []
    return [{"name": html.unescape(name).strip(), "role": role.strip()} for name, role in _COMPANY.findall(page)]


def _not_subject(people: list[dict]) -> list[str]:
    return [p["name"] for p in people if p["role"].lower() not in ("subject", "issuer")]


def holders_13dg(ctx, cik: int, rows: list[dict], days: int = 730, limit: int = 20) -> list[dict]:
    picks = [r for r in _since(rows, days) if FORM_13DG.match(r.get("form") or "")][:limit]
    with ThreadPoolExecutor(max_workers=4) as pool:
        people = list(pool.map(lambda r: filers(ctx, cik, r), picks))
    out = []
    for r, found in zip(picks, people):
        form = r.get("form") or ""
        out.append({"date": r.get("filingDate"), "form": form, "active": "13D" in form,
                    "amendment": form.endswith("/A"), "filers": _not_subject(found), "url": r["index_url"]})
    return out


def events_8k(rows: list[dict], days: int = 180, limit: int = 30) -> list[dict]:
    out = []
    for r in _since(rows, days):
        if r.get("form") not in ("8-K", "8-K/A"):
            continue
        codes = [c.strip() for c in (r.get("items") or "").split(",") if c.strip()]
        out.append({"date": r.get("filingDate"), "accepted": r.get("acceptanceDateTime"), "form": r.get("form"),
                    "items": [{"code": c, "label": ITEMS_8K.get(c, c)} for c in codes],
                    "description": r.get("primaryDocDescription"), "url": r.get("doc_url") or r["index_url"],
                    "index_url": r["index_url"]})
    return out[:limit]


def other_filings(ctx, cik: int, rows: list[dict], days: int = 180, limit: int = 30) -> list[dict]:
    picks = [r for r in _since(rows, days) if r.get("form") in OTHER_FORMS or (r.get("form") or "").startswith("424B")]
    picks = picks[:limit]
    need_names = [r for r in picks if (r.get("form") or "").startswith("144")][:10]
    with ThreadPoolExecutor(max_workers=4) as pool:
        names = dict(zip((r["accessionNumber"] for r in need_names),
                         pool.map(lambda r: _not_subject(filers(ctx, cik, r)), need_names)))
    return [{"date": r.get("filingDate"), "form": r.get("form"),
             "label": OTHER_FORMS.get(r.get("form") or "", "发行说明书"),
             "description": r.get("primaryDocDescription"), "filers": names.get(r["accessionNumber"], []),
             "url": r.get("doc_url") or r["index_url"], "index_url": r["index_url"]} for r in picks]


def filings_overview(ctx, symbol: str) -> dict:
    comp = company(ctx, symbol)
    rows = filing_list(ctx, comp["cik"])
    q_end, due = timeutil.next_13f_deadline(timeutil.today_et())
    holders = holders_13dg(ctx, comp["cik"], rows)
    events = events_8k(rows)
    other = other_filings(ctx, comp["cik"], rows)
    return {"company": comp, "holders": holders, "events": events, "other": other,
            "oldest_listed": rows[-1].get("filingDate") if rows else None,
            "next_13f": {"quarter_end": q_end.isoformat(), "due": due.isoformat()},
            "count": len(holders) + len(events) + len(other)}
