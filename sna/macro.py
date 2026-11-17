"""The macro home page: market and sector quotes, FRED series, the economic calendar, Federal Reserve releases and
CFTC positioning. Every block is fetched on its own so one slow source never holds up the others."""
from __future__ import annotations

import datetime as dt
import statistics
from concurrent.futures import ThreadPoolExecutor

from . import config, netio, timeutil
from .sources import SourceError, collect, cftc, fmp, fred, rss


# ---------- quotes ----------

def market(refresh: bool = False) -> dict:
    feeds = config.feeds()
    wanted = feeds["market_quotes"] + feeds["sector_quotes"]
    found, status = collect("fmp_quotes", "FMP 市场报价", fmp.quotes, [q["symbol"] for q in wanted], refresh=refresh)
    by = {str(q.get("symbol", "")).upper(): q for q in found}

    def rows(group):
        return [{**by.get(q["symbol"], {"symbol": q["symbol"]}), "label": q["label"]} for q in group]

    sectors = rows(feeds["sector_quotes"])
    sectors.sort(key=lambda q: q.get("change_pct") if q.get("change_pct") is not None else -1e9, reverse=True)
    return {"market": rows(feeds["market_quotes"]), "sectors": sectors, "sources": [status]}


# ---------- FRED ----------

def _frequency(obs: list[tuple[str, float]]) -> str:
    dates = [timeutil.parse_date(d) for d, _ in obs[-12:]]
    gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if a and b]
    gap = statistics.median(gaps) if gaps else 1
    return "daily" if gap <= 3 else "weekly" if gap <= 8 else "monthly"


def _transform(obs, how: str | None):
    if how == "yoy":
        by_month = {d[:7]: v for d, v in obs}
        out = []
        for d, v in obs:
            prior = by_month.get(f"{int(d[:4]) - 1}{d[4:7]}")
            if prior:
                out.append((d, round((v / prior - 1) * 100, 2)))
        return out
    if how == "diff":
        return [(d, round(v - pv, 3)) for (d, v), (_, pv) in zip(obs[1:], obs)]
    return obs


def _value_on_or_before(obs, day: dt.date):
    for d, v in reversed(obs):
        parsed = timeutil.parse_date(d)
        if parsed and parsed <= day:
            return v
    return None


def _change(now, then, how: str):
    if now is None or then is None:
        return None
    if how == "bp":
        return round((now - then) * 100, 1)
    if how == "pct":
        return round((now / then - 1) * 100, 2) if then else None
    return round(now - then, 3)


def describe(spec: dict, raw: list[tuple[str, float]]) -> dict:
    obs = _transform(raw, spec.get("transform"))
    row = {"id": spec["id"], "label": spec["label"], "unit": spec.get("unit", ""), "change_unit": spec.get("change"),
           "note": spec.get("note"), "found": bool(obs)}
    if not obs:
        return row
    freq = _frequency(obs)
    last_date, last = obs[-1]
    day = timeutil.parse_date(last_date)
    how = spec.get("change", "abs")
    prev = obs[-2][1] if len(obs) > 1 else None
    keep = {"daily": 260, "weekly": 104, "monthly": 36}[freq]
    spark = [v for _, v in obs[-keep:]]
    step = max(1, len(spark) // 130)
    row.update({"date": last_date, "value": last, "freq": freq,
                "change_prev": _change(last, prev, how),
                "change_1m": _change(last, _value_on_or_before(obs, day - dt.timedelta(days=30)), how),
                "change_1y": _change(last, _value_on_or_before(obs, day - dt.timedelta(days=365)), how),
                "spark": spark[::-1][::step][::-1],
                "url": f"https://fred.stlouisfed.org/series/{spec['id']}"})
    if freq != "monthly":
        row["change_1w"] = _change(last, _value_on_or_before(obs, day - dt.timedelta(days=7)), how)
    return row


def _fred_fetch(ctx, specs: list[dict], start: dt.date) -> dict:
    def one(spec):
        try:
            return spec["id"], fred.observations(ctx, spec["id"], start), None
        except (netio.FetchError, SourceError) as e:
            return spec["id"], [], str(e)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, specs))
    failed = {sid: err for sid, _, err in results if err}
    if failed and len(failed) == len(specs):
        raise SourceError(f"FRED 全部失败：{next(iter(failed.values()))}")
    return {"series": {sid: obs for sid, obs, err in results if not err}, "failed": failed,
            "count": len(specs) - len(failed)}


def fred_series(refresh: bool = False) -> dict:
    groups = config.feeds()["fred_groups"]
    specs = [s for g in groups for s in g["series"]]
    start = timeutil.today_et() - dt.timedelta(days=800)
    data, status = collect("fred", "FRED", _fred_fetch, specs, start, refresh=refresh, empty=dict)
    series = data.get("series", {})
    out = []
    for g in groups:
        rows = [describe(s, series.get(s["id"], [])) for s in g["series"]]
        for r in rows:
            if r["id"] in data.get("failed", {}):
                r["error"] = data["failed"][r["id"]]
        if any(s["id"] == "VXVCLS" for s in g["series"]):
            ratio = vix_ratio(series.get("VIXCLS", []), series.get("VXVCLS", []))
            if ratio:
                rows.append(ratio)
        out.append({"title": g["title"], "rows": rows})
    if data.get("failed"):
        status["error"] = status["error"] or f"{len(data['failed'])} 个序列没取到：{', '.join(data['failed'])}"
    return {"groups": out, "sources": [status]}


def vix_ratio(vix, vix3m) -> dict | None:
    """VIX divided by VIX3M on each common date; above 1 means the curve is inverted (near-term stress)."""
    other = dict(vix3m)
    obs = [(d, round(v / other[d], 3)) for d, v in vix if other.get(d)]
    if not obs:
        return None
    row = describe({"id": "VIXCLS/VXVCLS", "label": "VIX ÷ VIX3M（大于 1 为期限结构倒挂）", "change": "abs"}, obs)
    row["url"] = "https://fred.stlouisfed.org/series/VXVCLS"
    return row


# ---------- calendar, Fed, CFTC ----------

def calendar(refresh: bool = False) -> dict:
    today = timeutil.today_et()
    start, end = today - dt.timedelta(days=3), today + dt.timedelta(days=10)
    events, status = collect("fmp_calendar", "FMP 经济日历", fmp.economic_calendar, start.isoformat(), end.isoformat(),
                             refresh=refresh)
    return {"events": events, "from": start.isoformat(), "to": end.isoformat(), "sources": [status],
            "time_basis": fmp.calendar_tz(), "time_basis_measured": "fmp_calendar_tz" in config.settings()}


def fed(refresh: bool = False) -> dict:
    feeds = config.feeds().get("fed", [])
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda f: collect(f["id"], f"美联储{f['label']}", rss.fetch, f, ttl=1800,
                                                  refresh=refresh), feeds))
    return {"feeds": [{"id": f["id"], "label": f["label"], "items": items[:12]} for f, (items, _) in zip(feeds, results)],
            "sources": [status for _, status in results]}


def cot(refresh: bool = False) -> dict:
    markets, status = collect("cftc", "CFTC 持仓报告", cftc.fetch, config.feeds()["cot_markets"], refresh=refresh)
    return {"markets": markets, "sources": [status],
            "release": "持仓截至每周二，周五 15:30（美东）发布；只有指数和利率期货，没有个股"}
