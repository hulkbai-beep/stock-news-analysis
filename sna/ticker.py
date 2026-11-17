"""One ticker's page apart from its news: the header (quote and profile), insider trades, filings that show what
large holders and the company did, and analyst grade changes."""
from __future__ import annotations

import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from .sources import collect, fmp, sec


def links(symbol: str, cik: int | None) -> list[dict]:
    s = urllib.parse.quote(symbol)
    out = [{"label": "Seeking Alpha", "url": f"https://seekingalpha.com/symbol/{s}"},
           {"label": "Nasdaq", "url": f"https://www.nasdaq.com/market-activity/stocks/{s.lower()}"},
           {"label": "Finviz", "url": f"https://finviz.com/quote.ashx?t={s}"},
           {"label": "WhaleWisdom（13F）", "url": f"https://whalewisdom.com/stock/{s.lower()}"}]
    if cik:
        out.insert(0, {"label": "SEC 全部文件", "url": sec.COMPANY_PAGE.format(cik=cik)})
    return out


def overview(symbol: str, refresh: bool = False) -> dict:
    with ThreadPoolExecutor(max_workers=3) as pool:
        q = pool.submit(collect, "fmp_quote", "FMP 个股报价", fmp.quote, symbol, refresh=refresh, empty=dict)
        p = pool.submit(collect, "fmp_profile", "FMP 公司资料", fmp.profile, symbol, refresh=refresh, empty=dict)
        c = pool.submit(collect, "sec_company", "SEC 代码表", sec.company, symbol, refresh=refresh, empty=dict)
        (quote, s1), (profile, s2), (company, s3) = q.result(), p.result(), c.result()
    name = (profile or {}).get("name") or (company or {}).get("name")
    return {"symbol": symbol, "name": name, "quote": quote or None, "profile": profile or None,
            "company": company or None, "links": links(symbol, (company or {}).get("cik")),
            "sources": [s1, s2, s3]}


def insiders(symbol: str, refresh: bool = False) -> dict:
    data, status = collect("sec_form4", "SEC Form 4", sec.insiders, symbol, refresh=refresh, empty=dict)
    return {**data, "sources": [status]}


def filings(symbol: str, refresh: bool = False) -> dict:
    data, status = collect("sec_filings", "SEC 文件", sec.filings_overview, symbol, refresh=refresh, empty=dict)
    return {**data, "sources": [status]}


def analysts(symbol: str, refresh: bool = False) -> dict:
    with ThreadPoolExecutor(max_workers=2) as pool:
        g = pool.submit(collect, "fmp_grades", "FMP 评级变动", fmp.grades, symbol, refresh=refresh)
        t = pool.submit(collect, "fmp_target", "FMP 目标价", fmp.price_target, symbol, refresh=refresh, empty=dict)
        (grades, s1), (target, s2) = g.result(), t.result()
    return {"grades": grades, "target": target or None, "sources": [s1, s2]}
