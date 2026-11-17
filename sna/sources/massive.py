"""Massive (formerly Polygon) news, GET /v2/reference/news. Every Stocks plan includes it; the free Basic plan has two
years of history and 5 requests a minute. Massive attaches its own per-ticker sentiment to each article (`insights`,
since 2024-07-02); it is shown as fetched, nothing here re-scores it."""
from __future__ import annotations

import datetime as dt
import os

from .. import config, timeutil
from . import Skip, SourceError, news_item

LABEL = "Massive"


def base_url() -> str:
    return (os.environ.get("MASSIVE_BASE_URL") or "https://api.massive.com").rstrip("/")


def ticker_news(ctx, symbol: str, days: int = 14, limit: int = 1000) -> list[dict]:
    """One call, newest first; 1000 is the API's maximum (a busy ticker such as NVDA had 168 articles in 7 days)."""
    key = config.massive_key()
    if not key:
        raise Skip("未设置 MASSIVE_API_KEY")
    since = (timeutil.now() - dt.timedelta(days=days)).date().isoformat()   # whole days keep the cache key stable
    resp = ctx.get(base_url() + "/v2/reference/news",
                   params={"ticker": symbol, "published_utc.gte": since, "order": "desc", "sort": "published_utc",
                           "limit": limit},
                   headers={"Authorization": f"Bearer {key}"}, ttl=900)
    data = resp.json()
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        message = data.get("error") or data.get("message") if isinstance(data, dict) else None
        raise SourceError(f"Massive：{message or '返回格式不对'}")
    items = []
    for a in data["results"]:
        if not isinstance(a, dict):
            continue
        insight = next((i for i in a.get("insights") or [] if isinstance(i, dict)
                        and str(i.get("ticker", "")).upper() == symbol.upper()), None)
        sentiment = None
        if insight and insight.get("sentiment"):
            sentiment = {"label": str(insight["sentiment"]).lower(), "reasoning": insight.get("sentiment_reasoning"),
                         "by": "Massive"}
        item = news_item(source="massive", label=LABEL, title=a.get("title"), url=a.get("article_url"),
                         published=a.get("published_utc"), summary=a.get("description"),
                         publisher=(a.get("publisher") or {}).get("name"), tickers=a.get("tickers"),
                         sentiment=sentiment, item_id=a.get("id"))
        if item:
            item["keywords"] = [str(k) for k in (a.get("keywords") or [])][:8]
            items.append(item)
    return items
