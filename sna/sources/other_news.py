"""Other free news APIs: 华尔街见闻 live feed (no key), GDELT DOC 2.0 (no key, one request per 5 seconds),
Finnhub company news (free key) and Alpaca news (free account, Benzinga articles)."""
from __future__ import annotations

import datetime as dt
import re

from .. import config, timeutil
from . import Skip, SourceError, news_item

WALLSTCN_URL = "https://api-one.wallstcn.com/apiv1/content/lives"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
FINNHUB_URL = "https://finnhub.io/api/v1/company-news"
ALPACA_URL = "https://data.alpaca.markets/v1beta1/news"
_SUFFIX = re.compile(r"\b(INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|HOLDINGS?|GROUP|SA|NV|AG|SE|LLC|LP|"
                     r"CLASS [A-Z]|THE|N\.?V\.?|S\.?A\.?|/[A-Z]{2}/?)\b\.?", re.I)


def wallstcn(ctx, channel: str = "global-channel", limit: int = 50) -> list[dict]:
    """华尔街见闻 7x24 live news. Many items have no title; the first sentence of the text stands in for it."""
    data = ctx.get(WALLSTCN_URL, params={"channel": channel, "limit": limit}, ttl=300).json()
    if not isinstance(data, dict) or data.get("code") not in (20000, "20000"):
        raise SourceError(f"华尔街见闻返回 {data.get('code') if isinstance(data, dict) else '格式不对'}")
    items = []
    for d in ((data.get("data") or {}).get("items") or []):
        if not isinstance(d, dict):
            continue
        text = (d.get("content_text") or "").strip()
        title = (d.get("title") or "").strip() or re.split(r"(?<=[。！？])", text, maxsplit=1)[0][:90]
        item = news_item(source="wallstcn", label="华尔街见闻", title=title, url=d.get("uri"),
                         published=d.get("display_time"), summary=text if text != title else "",
                         publisher="华尔街见闻", kind="news", lang="zh", item_id=d.get("id"),
                         tickers=[s.get("key") or s.get("symbol") for s in d.get("symbols") or [] if isinstance(s, dict)])
        if item:
            items.append(item)
    return items


def company_words(name: str | None, symbol: str) -> str:
    """'NVIDIA CORP' -> 'NVIDIA'; used for the GDELT keyword query."""
    cleaned = _SUFFIX.sub(" ", name or "").replace(",", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned or symbol


def gdelt(ctx, symbol: str, company_name: str | None, days: int = 7, limit: int = 75) -> list[dict]:
    words = company_words(company_name, symbol)
    query = f'"{words}" sourcelang:english' if " " in words else f"{words} sourcelang:english"
    resp = ctx.get(GDELT_URL, params={"query": query, "mode": "artlist", "maxrecords": limit, "format": "json",
                                      "timespan": f"{days}d", "sort": "datedesc"}, ttl=1800, timeout=25)
    text = resp.text().strip()
    if not text.startswith("{"):
        raise SourceError(f"GDELT：{text[:120] or '空响应'}")
    data = resp.json()
    items = []
    for a in data.get("articles") or []:
        item = news_item(source="gdelt", label="GDELT", title=a.get("title"), url=a.get("url"),
                         published=a.get("seendate"), publisher=a.get("domain"), kind="news",
                         lang="en", tickers=[symbol])
        if item:
            item["country"] = a.get("sourcecountry")
            items.append(item)
    return items


def finnhub(ctx, symbol: str, days: int = 14) -> list[dict]:
    key = config.key("FINNHUB_API_KEY")
    if not key:
        raise Skip("可选：设置 FINNHUB_API_KEY（免费注册）后启用")
    end = timeutil.today_et()
    data = ctx.get(FINNHUB_URL, params={"symbol": symbol, "from": (end - dt.timedelta(days=days)).isoformat(),
                                        "to": end.isoformat()},
                   headers={"X-Finnhub-Token": key}, ttl=900).json()
    if isinstance(data, dict):
        raise SourceError(f"Finnhub：{data.get('error') or '返回格式不对'}")
    items = []
    for a in data or []:
        item = news_item(source="finnhub", label="Finnhub", title=a.get("headline"), url=a.get("url"),
                         published=a.get("datetime"), summary=a.get("summary"), publisher=a.get("source"),
                         tickers=(a.get("related") or symbol).split(","), item_id=a.get("id"))
        if item:
            items.append(item)
    return items


def alpaca(ctx, symbol: str, days: int = 14, limit: int = 50) -> list[dict]:
    key_id, secret = config.key("APCA_API_KEY_ID"), config.key("APCA_API_SECRET_KEY")
    if not (key_id and secret):
        raise Skip("可选：设置 APCA_API_KEY_ID 和 APCA_API_SECRET_KEY（免费账户）后启用")
    start = (timeutil.now() - dt.timedelta(days=days)).date().isoformat()
    data = ctx.get(ALPACA_URL, params={"symbols": symbol, "start": start, "limit": limit, "sort": "desc"},
                   headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}, ttl=900).json()
    if not isinstance(data, dict) or not isinstance(data.get("news"), list):
        raise SourceError(f"Alpaca：{(data or {}).get('message') if isinstance(data, dict) else '返回格式不对'}")
    items = []
    for a in data["news"]:
        item = news_item(source="alpaca", label="Alpaca", title=a.get("headline"), url=a.get("url"),
                         published=a.get("created_at"), summary=a.get("summary"),
                         publisher=(a.get("source") or "Benzinga").capitalize(), tickers=a.get("symbols"),
                         item_id=a.get("id"))
        if item:
            items.append(item)
    return items
