"""Source adapters. Each adapter turns one provider's response into plain dicts; nothing here judges the content.

A source call runs inside collect(), which turns its outcome into a status line for the page: ok with a count,
skipped (no key: a setup hint, not an error), or failed with a key-free message. Fetches go through a Ctx so the
status can say when a stale cached copy was shown.
"""
from __future__ import annotations

import threading
import time
import traceback

from .. import netio, textutil, timeutil


class Skip(Exception):
    """The source is not set up (usually a missing key); the page shows the hint instead of an error."""


class SourceError(Exception):
    """The source answered, but not with what we expected."""


class Ctx:
    """Fetch context of one page request: passes refresh through and remembers stale copies and fetch times."""

    def __init__(self, refresh: bool = False):
        self.refresh = refresh
        self.stale: list[str] = []
        self.oldest: float | None = None
        self._lock = threading.Lock()

    def get(self, url: str, **kw) -> netio.Response:
        resp = netio.get(url, refresh=self.refresh, **kw)
        with self._lock:
            if resp.stale:
                self.stale.append(resp.error or "旧缓存")
            if self.oldest is None or resp.fetched_at < self.oldest:
                self.oldest = resp.fetched_at
        return resp


_log_lock = threading.Lock()
LAST: dict[str, dict] = {}      # source name -> last outcome since the server started (for the status page)


def collect(name: str, label: str, fn, *args, refresh: bool = False, empty=list, **kw):
    """Run fn(ctx, *args, **kw), which returns a list or a dict (a dict may carry its own "count").
    Returns (result, status); on failure the result is empty() and the status says why."""
    ctx = Ctx(refresh)
    status = {"name": name, "label": label, "ok": False, "count": 0, "error": None, "skipped": None,
              "stale": False, "fetched_at": None}
    items = empty()
    started = time.time()
    try:
        result = fn(ctx, *args, **kw)
        items = result if result is not None else empty()
        status["ok"] = True
        status["count"] = len(items) if isinstance(items, list) else int(items.get("count", 1) or 0)
    except Skip as e:
        status["skipped"] = str(e)
    except (netio.FetchError, SourceError) as e:
        status["error"] = netio.scrub(str(e))
    except Exception as e:  # a parser bug must not take the page down; the status line shows it
        traceback.print_exc()
        status["error"] = netio.scrub(f"解析出错 {type(e).__name__}: {e}")
    if ctx.stale:
        status["stale"] = True
        status["error"] = status["error"] or f"刷新失败，显示的是缓存：{ctx.stale[0]}"
    if ctx.oldest:
        status["fetched_at"] = timeutil.iso(timeutil.parse_time(ctx.oldest))
    status["ms"] = int((time.time() - started) * 1000)
    with _log_lock:
        LAST[name] = {**status, "at": timeutil.iso(timeutil.now())}
    return items, status


def news_item(*, source: str, label: str, title, url, published, summary=None, publisher=None, tickers=None,
              kind: str = "news", sentiment=None, item_id=None, lang: str = "en", naive_tz: str = "UTC") -> dict | None:
    """One news row in the shared shape. Returns None when the row has no title or no usable link."""
    title = textutil.strip_html(title, 300)
    link = textutil.safe_url(url)
    if not title or not link:
        return None
    when = timeutil.parse_time(published, naive_tz)
    return {
        "id": f"{source}:{item_id or textutil.canonical_url(link)}",
        "source": source,
        "source_label": label,
        "publisher": textutil.strip_html(publisher, 80) or label,
        "kind": kind,
        "title": title,
        "summary": textutil.strip_html(summary, 700),
        "url": link,
        "published_utc": timeutil.iso(when),
        "tickers": sorted({str(t).upper() for t in (tickers or []) if t})[:12],
        "sentiment": sentiment,
        "lang": lang,
    }
