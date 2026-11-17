"""RSS 2.0 and Atom feeds (MarketWatch, ZeroHedge, the Federal Reserve, Seeking Alpha, Nasdaq ...). Elements are
matched by local name, so namespaced extras like dc:creator, sa:author_name or nasdaq:tickers need no namespace map.
Only the headline, a short summary and the link are kept."""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET

from . import SourceError, news_item

_BAD_AMP = re.compile(rb"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el, *names):
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def parse_feed(body: bytes) -> list[dict]:
    """Entries as dicts: title, link, published, summary, author, tickers, categories."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        try:   # feeds with HTML entities such as &nbsp; are not well-formed XML
            root = ET.fromstring(_BAD_AMP.sub(b"&amp;", body))
        except ET.ParseError as e:
            raise SourceError(f"不是有效的 RSS/XML：{e}") from None
    entries = []
    for el in root.iter():
        name = _local(el.tag)
        if name not in ("item", "entry"):
            continue
        link = ""
        link_el = _child(el, "link")
        if link_el is not None:
            link = (link_el.get("href") or _text(link_el)).strip()
            for alt in _children(el, "link"):          # Atom: prefer rel="alternate"
                if alt.get("rel") in (None, "alternate") and alt.get("href"):
                    link = alt.get("href").strip()
                    break
        if not link:
            guid = _child(el, "guid", "id")
            if guid is not None and _text(guid).startswith("http"):
                link = _text(guid)
        tickers = []
        for t in el.iter():
            local = _local(t.tag)
            if local == "tickers" and t.text:
                tickers += [x.split(":")[-1].strip() for x in t.text.split(",") if x.strip()]
            elif local == "symbol" and t.text:
                tickers.append(t.text.strip())
        author = _child(el, "creator", "author_name", "author")
        if author is not None and _child(author, "name") is not None:
            author = _child(author, "name")
        entries.append({
            "title": _text(_child(el, "title")),
            "link": link,
            "published": _text(_child(el, "pubDate", "published", "updated", "date")),
            "summary": _text(_child(el, "description", "summary", "encoded", "content")),
            "author": _text(author),
            "tickers": tickers,
            "categories": [_text(c) for c in _children(el, "category") if _text(c)],
            "guid": _text(_child(el, "guid", "id")),
        })
    return entries


def feed_url(template: str, symbol: str | None = None) -> str:
    return template.replace("{symbol}", urllib.parse.quote(symbol or "", safe=".-"))


def fetch(ctx, feed: dict, symbol: str | None = None, ttl: float = 900, limit: int = 60) -> list[dict]:
    """News rows of one configured feed ({"id", "label", "url", "lang", "kind"})."""
    resp = ctx.get(feed_url(feed["url"], symbol), ttl=ttl, headers={"Accept": "application/rss+xml, application/xml, text/xml, */*"})
    items = []
    for e in parse_feed(resp.body)[:limit]:
        item = news_item(source=feed["id"], label=feed["label"], title=e["title"], url=e["link"],
                         published=e["published"], summary=e["summary"],
                         publisher=feed.get("publisher") or feed["label"],
                         tickers=e["tickers"] or ([symbol] if symbol else None), kind=feed.get("kind", "news"),
                         lang=feed.get("lang", "en"), item_id=e["guid"] or None)
        if item:
            if e["author"]:
                item["author"] = e["author"][:80]
            if e["categories"]:
                item["categories"] = e["categories"][:5]
            items.append(item)
    return items
