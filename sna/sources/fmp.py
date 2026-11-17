"""Financial Modeling Prep, stable API: stock news, press releases, general news, quotes, profile, analyst grades,
price-target consensus and the economic calendar. Needs FMP_API_KEY (the free Basic plan allows 250 calls a day; what
each plan includes differs, and an endpoint outside the plan answers with an error that the page shows as is).

Times: FMP returns 'YYYY-MM-DD HH:MM:SS' without a zone. Checked live on 2026-11-07: news times are US Eastern (12
articles also in Massive, all exactly 5 hours behind Massive's UTC in EST) and calendar times are UTC (the 8:30 ET jobs
report listed at 13:30). `python -m sna doctor` re-measures both and saves what it finds in data/settings.json;
SNA_FMP_NEWS_TZ and SNA_FMP_CAL_TZ (UTC or ET) override."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from .. import config, netio, timeutil
from . import Skip, SourceError, news_item

BASE = "https://financialmodelingprep.com/stable"
LABEL = "FMP"


def _tz(env: str, setting: str, default: str) -> str:
    value = (os.environ.get(env) or config.settings().get(setting) or default).upper()
    return "ET" if value == "ET" else "UTC"


def news_tz() -> str:
    return _tz("SNA_FMP_NEWS_TZ", "fmp_news_tz", "ET")


def calendar_tz() -> str:
    return _tz("SNA_FMP_CAL_TZ", "fmp_calendar_tz", "UTC")


def fmp_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


def _key() -> str:
    key = config.key("FMP_API_KEY")
    if not key:
        raise Skip("未设置 FMP_API_KEY")
    return key


def _get(ctx, path: str, params: dict, ttl: float):
    try:
        resp = ctx.get(BASE + path, params={**params, "apikey": _key()}, secret=("apikey",), ttl=ttl)
    except netio.FetchError as e:
        if e.status == 402 or (e.status == 403 and "subscription" in str(e).lower()):
            raise Skip(f"你的 FMP 套餐不含这个接口（{path}，HTTP {e.status}）") from None
        raise
    data = resp.json()
    if isinstance(data, dict):
        message = data.get("Error Message") or data.get("error") or data.get("message")
        if message:
            raise SourceError(f"FMP：{str(message)[:200]}")
    return data


def _rows(data, what: str) -> list[dict]:
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        data = data["data"]
    if not isinstance(data, list):
        raise SourceError(f"FMP {what} 返回格式不对")
    return [d for d in data if isinstance(d, dict)]


def _news(ctx, path: str, params: dict, source: str, label: str, kind: str) -> list[dict]:
    items, tz = [], news_tz()
    for d in _rows(_get(ctx, path, params, ttl=900), "新闻"):
        symbol = d.get("symbol")
        item = news_item(source=source, label=label, title=d.get("title"), url=d.get("url") or d.get("link"),
                         published=d.get("publishedDate") or d.get("date"), summary=d.get("text") or d.get("content"),
                         publisher=d.get("publisher") or d.get("site"), tickers=[symbol] if symbol else None,
                         kind=kind, naive_tz=tz)
        if item:
            items.append(item)
    return items


def stock_news(ctx, symbol: str, limit: int = 100) -> list[dict]:
    return _news(ctx, "/news/stock", {"symbols": fmp_symbol(symbol), "limit": limit}, "fmp", "FMP", "news")


def press_releases(ctx, symbol: str, limit: int = 20) -> list[dict]:
    return _news(ctx, "/news/press-releases", {"symbols": fmp_symbol(symbol), "limit": limit},
                 "fmp_press", "FMP 新闻稿", "press")


def general_news(ctx, limit: int = 50) -> list[dict]:
    return _news(ctx, "/news/general-latest", {"page": 0, "limit": limit}, "fmp_general", "FMP", "news")


def _num(value):
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def _quote(d: dict) -> dict:
    pct = d.get("changePercentage", d.get("changesPercentage"))
    return {"symbol": d.get("symbol"), "name": d.get("name"), "price": _num(d.get("price")),
            "change": _num(d.get("change")), "change_pct": _num(pct), "volume": _num(d.get("volume")),
            "prev_close": _num(d.get("previousClose")), "day_low": _num(d.get("dayLow")),
            "day_high": _num(d.get("dayHigh")), "year_low": _num(d.get("yearLow")),
            "year_high": _num(d.get("yearHigh")), "avg50": _num(d.get("priceAvg50")),
            "avg200": _num(d.get("priceAvg200")), "market_cap": _num(d.get("marketCap")),
            "timestamp": d.get("timestamp")}


_batch_quote = {"ok": True}      # set to False once the plan refuses batch quotes, so later loads go straight to /quote


def quotes(ctx, symbols: list[str]) -> list[dict]:
    """One batch call when the plan allows it (checked 2026-11-07: Tim's plan answers 402), otherwise one call per
    symbol, cached for 5 minutes."""
    _key()
    wanted = [fmp_symbol(s) for s in symbols]
    if _batch_quote["ok"]:
        try:
            rows = _rows(_get(ctx, "/batch-quote", {"symbols": ",".join(wanted)}, ttl=300), "报价")
            if rows:
                return [_quote(d) for d in rows]
        except Skip:
            _batch_quote["ok"] = False
        except (netio.FetchError, SourceError):
            pass

    def one(sym):
        try:
            rows = _rows(_get(ctx, "/quote", {"symbol": sym}, ttl=300), "报价")
            return _quote(rows[0]) if rows else None
        except (netio.FetchError, SourceError):
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        found = [q for q in pool.map(one, wanted) if q]
    if not found:
        raise SourceError("FMP 报价一个都没取到（批量和单个都失败）")
    return found


def quote(ctx, symbol: str) -> dict | None:
    rows = _rows(_get(ctx, "/quote", {"symbol": fmp_symbol(symbol)}, ttl=120), "报价")
    return _quote(rows[0]) if rows else None


def profile(ctx, symbol: str) -> dict | None:
    rows = _rows(_get(ctx, "/profile", {"symbol": fmp_symbol(symbol)}, ttl=86400), "公司资料")
    if not rows:
        return None
    d = rows[0]
    return {"name": d.get("companyName"), "sector": d.get("sector"), "industry": d.get("industry"),
            "exchange": d.get("exchange") or d.get("exchangeShortName"), "country": d.get("country"),
            "market_cap": _num(d.get("marketCap", d.get("mktCap"))), "website": d.get("website"),
            "ceo": d.get("ceo"), "is_etf": d.get("isEtf"), "description": (d.get("description") or "")[:600]}


def grades(ctx, symbol: str, limit: int = 40) -> list[dict]:
    rows = _rows(_get(ctx, "/grades", {"symbol": fmp_symbol(symbol), "limit": limit}, ttl=3600), "评级")
    out = [{"date": d.get("date"), "firm": d.get("gradingCompany") or d.get("company"),
            "from": d.get("previousGrade"), "to": d.get("newGrade"), "action": d.get("action")} for d in rows]
    out.sort(key=lambda r: r["date"] or "", reverse=True)
    return out[:limit]


def price_target(ctx, symbol: str) -> dict | None:
    rows = _rows(_get(ctx, "/price-target-consensus", {"symbol": fmp_symbol(symbol)}, ttl=3600), "目标价")
    if not rows:
        return None
    d = rows[0]
    return {k: _num(d.get(k)) for k in ("targetHigh", "targetLow", "targetConsensus", "targetMedian")}


def economic_calendar(ctx, start: str, end: str) -> list[dict]:
    rows = _rows(_get(ctx, "/economic-calendar", {"from": start, "to": end}, ttl=1800), "经济日历")
    out, tz = [], calendar_tz()
    for d in rows:
        when = timeutil.parse_time(d.get("date"), tz)
        out.append({"time_utc": timeutil.iso(when), "country": d.get("country"), "event": d.get("event"),
                    "currency": d.get("currency"), "actual": d.get("actual"), "estimate": d.get("estimate"),
                    "previous": d.get("previous"), "change": d.get("change"),
                    "impact": d.get("impact"), "unit": d.get("unit")})
    out.sort(key=lambda r: r["time_utc"] or "")
    return out
