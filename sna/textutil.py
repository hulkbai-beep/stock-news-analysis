"""Text helpers: plain text from feed HTML, canonical article URLs and title similarity for de-duplication."""
from __future__ import annotations

import html
import re
import unicodedata
import urllib.parse

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
# query keys that only track the click; anything else in a query is kept (some sites use ?id= for the article)
_TRACKING = {"mod", "source", "ref", "refsrc", "ref_src", "cmpid", "ncid", "guccounter", "guce_referrer",
             "guce_referrer_sig", "tsrc", "yptr", "siteid", "ito", "fbclid", "gclid", "ocid", "cid", "src", "sref",
             "feed", "rss", "soc_src", "soc_trk", "taid", "xid", "cmp", "campaign", "partner", "traffic_source",
             "dicbo", "mc_cid", "mc_eid", "rpc", "sh", "smid", "st", "ns_campaign", "ns_mchannel", "ns_source",
             "ns_linkname", "ns_fee", "originalreferrer", "utm"}
_HOST_PREFIXES = ("www.", "m.", "amp.", "mobile.")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[㐀-鿿]")
_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "as", "at", "by", "with", "from",
         "its", "it", "be", "this", "that", "after", "s"}


def strip_html(text, limit: int | None = None) -> str:
    """Tags removed, entities decoded, whitespace collapsed; cut to `limit` characters with an ellipsis."""
    if not text:
        return ""
    plain = html.unescape(_TAG.sub(" ", _SCRIPT.sub(" ", str(text))))
    plain = _SPACE.sub(" ", plain).strip()
    if limit and len(plain) > limit:
        plain = plain[: limit - 1].rstrip() + "…"
    return plain


def safe_url(url) -> str | None:
    """The URL when it is http(s), otherwise None (the page never links anything else)."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    return url if urllib.parse.urlparse(url).scheme in ("http", "https") else None


def canonical_url(url) -> str:
    """Scheme, leading www./m./amp., tracking parameters, fragments, trailing slashes and AMP suffixes removed."""
    if not url:
        return ""
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (p.hostname or "").lower()
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    path = re.sub(r"(/amp|\.amp|/amp\.html)$", "", p.path or "", flags=re.I).rstrip("/")
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=False)
             if k.lower() not in _TRACKING and not k.lower().startswith(("utm_", "mc_", "ga_"))]
    q = urllib.parse.urlencode(sorted(query))
    return f"{host}{path}" + (f"?{q}" if q else "")


def norm_title(title) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(str(title or ""))).lower()
    text = text.replace("’", "'").replace("‘", "'")
    return " ".join(_WORD.findall(text))


def title_tokens(title) -> frozenset:
    """Words of the normalised title without stop words; Chinese titles count each character."""
    return frozenset(w for w in _WORD.findall(norm_title(title)) if w not in _STOP)


def similarity(a: frozenset, b: frozenset) -> float:
    """Jaccard overlap of two token sets (0 when either is empty)."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
