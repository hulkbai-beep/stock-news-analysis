"""Merging news from several sources into one table: duplicates (same article, or the same headline within two days)
collapse into one row that lists the other sources, and every row's first-seen time is kept in SQLite so later work
can ask what was known at a given moment."""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from . import config, textutil, timeutil
from .sources import collect, fmp, massive, other_news, rss, sec

# lower wins when two sources carry the same article: Massive has the sentiment, Benzinga via Alpaca the full text
PRIORITY = {"massive": 0, "alpaca": 1, "fmp": 2, "fmp_press": 2, "finnhub": 3, "seekingalpha": 4, "nasdaq": 4,
            "marketwatch": 4, "zerohedge": 4, "fmp_general": 4, "wallstcn": 5, "gdelt": 6}
WINDOW = dt.timedelta(hours=48)
_store_lock = threading.Lock()
_store_ready = False


def _same_story(a: frozenset, b: frozenset) -> bool:
    if min(len(a), len(b)) < 5:
        return a == b
    return textutil.similarity(a, b) >= 0.75


def dedupe(items: list[dict]) -> list[dict]:
    ordered = sorted(items, key=lambda i: (PRIORITY.get(i["source"], 9), i.get("published_utc") or ""))
    kept: list[dict] = []
    by_url: dict[str, dict] = {}
    meta: dict[int, tuple] = {}
    for item in ordered:
        key = textutil.canonical_url(item["url"])
        target = by_url.get(key)
        tokens = textutil.title_tokens(item["title"])
        when = timeutil.parse_time(item.get("published_utc"))
        if target is None:
            for other in kept:
                o_tokens, o_when, o_lang = meta[id(other)]
                if o_lang != item.get("lang") or not _same_story(tokens, o_tokens):
                    continue
                if when and o_when and abs(when - o_when) > WINDOW:
                    continue
                target = other
                break
        if target is None:
            row = {**item, "also": []}
            kept.append(row)
            meta[id(row)] = (tokens, when, item.get("lang"))
            by_url[key] = row
            continue
        by_url.setdefault(key, target)
        if item["source"] != target["source"] or item["url"] != target["url"]:
            target["also"].append({"source": item["source"], "label": item["source_label"],
                                   "publisher": item["publisher"], "url": item["url"]})
        if not target.get("sentiment") and item.get("sentiment"):
            target["sentiment"] = item["sentiment"]
        if not target.get("summary") and item.get("summary"):
            target["summary"] = item["summary"]
        target["tickers"] = sorted(set(target.get("tickers") or []) | set(item.get("tickers") or []))[:12]
    kept.sort(key=lambda i: i.get("published_utc") or "", reverse=True)
    return kept


# ---------- first-seen history ----------

def _connect() -> sqlite3.Connection:
    global _store_ready
    d = config.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / "news.sqlite"), timeout=15)
    if not _store_ready:
        with _store_lock:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("""CREATE TABLE IF NOT EXISTS articles (
                scope TEXT NOT NULL, url_key TEXT NOT NULL, source TEXT, publisher TEXT, title TEXT, url TEXT,
                published_utc TEXT, first_seen_utc TEXT NOT NULL, sentiment TEXT, PRIMARY KEY (scope, url_key))""")
            con.commit()
            _store_ready = True
    return con


def remember(scope: str, items: list[dict]) -> None:
    """Record each row once per scope (a ticker, or "macro") with the time it was first fetched; then copy that
    first-seen time onto the rows. Offline sample data is not recorded."""
    if config.offline() or not items:
        return
    now = timeutil.iso(timeutil.now())
    rows = [(scope, textutil.canonical_url(i["url"]), i["source"], i["publisher"], i["title"], i["url"],
             i.get("published_utc"), now, (i.get("sentiment") or {}).get("label")) for i in items]
    try:
        with closing(_connect()) as con:
            con.executemany("INSERT OR IGNORE INTO articles VALUES (?,?,?,?,?,?,?,?,?)", rows)
            con.commit()
            keys = [r[1] for r in rows]
            seen = {}
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                q = f"SELECT url_key, first_seen_utc FROM articles WHERE scope=? AND url_key IN ({','.join('?' * len(chunk))})"
                seen.update(dict(con.execute(q, [scope, *chunk]).fetchall()))
        for item, key in zip(items, keys):
            item["first_seen_utc"] = seen.get(key)
    except sqlite3.Error as e:   # history is a convenience; the page still shows the news
        print(f"[sna] could not record news history: {e}")


def history_stats() -> dict:
    try:
        with closing(_connect()) as con:
            n, scopes = con.execute("SELECT COUNT(*), COUNT(DISTINCT scope) FROM articles").fetchone()
        return {"articles": n, "scopes": scopes, "path": "data/news.sqlite"}
    except sqlite3.Error as e:
        return {"error": str(e)}


# ---------- ticker and macro news ----------

def _run(tasks: list[tuple], refresh: bool):
    """tasks: (name, label, fn, args); runs them in parallel and returns (all items, statuses in task order)."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(collect, name, label, fn, *args, refresh=refresh) for name, label, fn, args in tasks]
        results = [f.result() for f in futures]
    items = [i for found, _ in results for i in found]
    return items, [status for _, status in results]


def company_name(symbol: str, refresh: bool = False) -> str | None:
    """The company's name from SEC's ticker map, or from FMP's profile when SEC is not set up."""
    found, status = collect("sec_company", "SEC 代码表", sec.company, symbol, refresh=refresh, empty=dict)
    if status["ok"] and found.get("name"):
        return found["name"]
    found, status = collect("fmp_profile", "FMP 公司资料", fmp.profile, symbol, refresh=refresh, empty=dict)
    return found.get("name") if status["ok"] else None


def title_matcher(symbol: str, name: str | None):
    """A test for "the headline names this stock": the ticker in capitals (3 letters or more, or in parentheses
    like "(GE)"), or the company name without Inc/Corp, in any case."""
    parts = [rf"\({re.escape(symbol)}\)"]
    if len(symbol) >= 3:
        parts.append(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])")
    by_ticker = re.compile("|".join(parts))
    words = other_news.company_words(name, "") if name else ""
    by_name = re.compile(rf"(?<![A-Za-z0-9]){re.escape(words)}(?![A-Za-z0-9])", re.I) if len(words) >= 3 else None
    return lambda title: bool(by_ticker.search(title) or (by_name and by_name.search(title)))


def ticker_news(symbol: str, days: int = 14, refresh: bool = False) -> dict:
    feeds = config.feeds()
    name = company_name(symbol)
    tasks = [("massive", "Massive", massive.ticker_news, (symbol, days)),
             ("fmp", "FMP 新闻", fmp.stock_news, (symbol,)),
             ("fmp_press", "FMP 新闻稿", fmp.press_releases, (symbol,))]
    tasks += [(f["id"], f["label"], rss.fetch, (f, symbol)) for f in feeds.get("ticker_feeds", [])]
    tasks += [("finnhub", "Finnhub", other_news.finnhub, (symbol, days)),
              ("alpaca", "Alpaca", other_news.alpaca, (symbol, days)),
              ("gdelt", "GDELT", other_news.gdelt, (symbol, name, min(days, 7)))]
    items, statuses = _run(tasks, refresh)
    cutoff = timeutil.iso(timeutil.now() - dt.timedelta(days=days))
    items = [i for i in items if not i.get("published_utc") or i["published_utc"] >= cutoff]
    merged = dedupe(items)
    names_it = title_matcher(symbol, name)
    for item in merged:
        item["focus"] = names_it(item["title"])
    remember(symbol, merged)
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for i in merged:
        label = (i.get("sentiment") or {}).get("label")
        if label in counts:
            counts[label] += 1
    return {"symbol": symbol, "company": name, "days": days, "items": merged, "sources": statuses,
            "massive_sentiment": counts, "raw_count": len(items)}


def macro_news(refresh: bool = False, limit: int = 200) -> dict:
    feeds = config.feeds()
    tasks = [(f["id"], f["label"], rss.fetch, (f,)) for f in feeds.get("macro_news", [])]
    tasks += [("wallstcn", "华尔街见闻", other_news.wallstcn, ()),
              ("fmp_general", "FMP 综合新闻", fmp.general_news, ())]
    items, statuses = _run(tasks, refresh)
    merged = dedupe(items)[:limit]
    remember("macro", merged)
    return {"items": merged, "sources": statuses}

