"""HTTP GET with a SQLite cache, per-host pacing and key-free error text.

Every fetch goes through get(). A fresh cached copy is returned without a request; when a refresh fails and an older
copy exists, the older copy comes back marked stale together with the error, so a page keeps its data when a source
has a bad minute. Keys travel in headers where the API allows it; query-string keys are named in `secret` and replaced
by *** in the cache key, the stored URL and any error text. In offline mode (SNA_OFFLINE=1) responses come from
tests/fixtures and nothing leaves the machine.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from contextlib import closing
from dataclasses import dataclass

from . import __version__, config

USER_AGENT = f"stock-news-analysis/{__version__} (personal research tool; Python urllib)"
MAX_BYTES = 25_000_000
# minimum seconds between two requests to one host: SEC allows 10 per second, GDELT asks for one every 5 seconds
PACING = {"www.sec.gov": 0.13, "data.sec.gov": 0.13, "api.gdeltproject.org": 5.0}

_db_lock = threading.Lock()
_db_ready: set[str] = set()
_pace_lock = threading.Lock()
_next_slot: dict[str, float] = {}


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(scrub(message))
        self.status = status


@dataclass
class Response:
    url: str                     # redacted
    status: int
    body: bytes
    content_type: str
    fetched_at: float
    from_cache: bool = False
    stale: bool = False
    error: str | None = None     # why a stale copy was served

    def text(self) -> str:
        charset = "utf-8"
        for part in self.content_type.split(";"):
            part = part.strip()
            if part.lower().startswith("charset="):
                charset = part[8:].strip("\"' ") or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8-sig", errors="replace"))
        except json.JSONDecodeError:
            snippet = self.text()[:120].replace("\n", " ")
            raise FetchError(f"返回的不是 JSON：{snippet}") from None


def scrub(text: str) -> str:
    """Error text without any key value that is set in the environment."""
    text = str(text)
    for value in config.secret_values():
        text = text.replace(value, "***")
    return text


def build_url(url: str, params: dict | None) -> str:
    if not params:
        return url
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, safe=",:$'()")
    return url + ("&" if "?" in url else "?") + query


def redact(url: str, secret: tuple = ()) -> str:
    if not secret:
        return url
    parts = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = urllib.parse.urlencode([(k, "***" if k in secret else v) for k, v in pairs], safe=",:$'()*")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


# ---------- cache ----------

def _db_path() -> str:
    d = config.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return str(d / "cache.sqlite")


def _connect() -> sqlite3.Connection:
    path = _db_path()
    con = sqlite3.connect(path, timeout=15)
    if path not in _db_ready:
        with _db_lock:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("""CREATE TABLE IF NOT EXISTS http_cache (
                key TEXT PRIMARY KEY, url TEXT NOT NULL, status INTEGER, content_type TEXT, body BLOB,
                fetched_at REAL NOT NULL)""")
            con.commit()
            _db_ready.add(path)
    return con


def _cache_get(key: str):
    with closing(_connect()) as con:
        return con.execute("SELECT status, content_type, body, fetched_at FROM http_cache WHERE key=?",
                           (key,)).fetchone()


def _cache_put(key: str, url: str, status: int, ctype: str, body: bytes, fetched_at: float) -> None:
    with closing(_connect()) as con:
        con.execute("INSERT OR REPLACE INTO http_cache VALUES (?,?,?,?,?,?)",
                    (key, url, status, ctype, body, fetched_at))
        con.commit()


def cache_stats() -> dict:
    try:
        with closing(_connect()) as con:
            n, size = con.execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(body)),0) FROM http_cache").fetchone()
        return {"entries": n, "bytes": size, "path": "data/cache.sqlite"}
    except sqlite3.Error as e:
        return {"error": str(e)}


def cache_clear() -> int:
    with closing(_connect()) as con:
        n = con.execute("DELETE FROM http_cache").rowcount
        con.commit()
    return n


# ---------- fetching ----------

def _pace(host: str) -> None:
    interval = PACING.get(host)
    if not interval:
        return
    with _pace_lock:
        now = time.monotonic()
        slot = max(now, _next_slot.get(host, 0.0))
        _next_slot[host] = slot + interval
    if slot > now:
        time.sleep(slot - now)


def _decode(raw: bytes, encoding: str) -> bytes:
    encoding = (encoding or "").lower()
    if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def _error_detail(e: urllib.error.HTTPError) -> str:
    try:
        raw = _decode(e.read(4000), e.headers.get("Content-Encoding", ""))
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # the body of an error is only a hint
        return ""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for k in ("Error Message", "error", "message", "msg", "detail"):
                if data.get(k):
                    return str(data[k])[:200]
    except json.JSONDecodeError:
        pass
    return " ".join(text.split())[:160]


def _live(url: str, headers: dict, timeout: float) -> tuple[int, str, bytes]:
    if config.offline():
        from . import fixtures
        return fixtures.lookup(url)
    host = urllib.parse.urlsplit(url).hostname or ""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip",
                                               "Accept": "*/*", **headers})
    last = None
    for attempt in range(2):
        _pace(host)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise FetchError(f"{host} 返回内容超过 {MAX_BYTES // 1_000_000} MB，已放弃")
                body = _decode(raw, resp.headers.get("Content-Encoding", ""))
                return resp.status, resp.headers.get("Content-Type", ""), body
        except urllib.error.HTTPError as e:
            detail = _error_detail(e)
            message = f"{host} 返回 HTTP {e.code}" + (f"：{detail}" if detail else "")
            if e.code == 429:
                raise FetchError(message + "（请求太频繁，稍后再试）", e.code) from None
            if e.code < 500 or attempt:
                raise FetchError(message, e.code) from None
            last = FetchError(message, e.code)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            last = FetchError(f"连不上 {host}：{reason}")
        except (OSError, EOFError, zlib.error) as e:
            last = FetchError(f"读取 {host} 失败：{type(e).__name__}: {e}")
        if attempt == 0:
            time.sleep(1.5)
    raise last


def get(url: str, *, params: dict | None = None, headers: dict | None = None, ttl: float = 600,
        secret: tuple = (), refresh: bool = False, timeout: float = 20, accept_status=(200,)) -> Response:
    """GET a URL through the cache. ttl is how long a stored copy counts as fresh (seconds); refresh=True skips
    a fresh copy but still falls back to a stored one when the request fails."""
    full = build_url(url, params)
    shown = redact(full, secret)
    key = hashlib.sha256(shown.encode("utf-8")).hexdigest()
    offline = config.offline()
    row = None if offline else _cache_get(key)
    if row and not refresh and time.time() - row[3] < ttl:
        return Response(shown, row[0], row[2], row[1] or "", row[3], from_cache=True)
    try:
        status, ctype, body = _live(full, headers or {}, timeout)
        if status not in accept_status:
            raise FetchError(f"{urllib.parse.urlsplit(full).hostname} 返回 HTTP {status}", status)
    except FetchError as e:
        if row:
            return Response(shown, row[0], row[2], row[1] or "", row[3], from_cache=True, stale=True, error=str(e))
        raise
    fetched = time.time()
    if not offline:
        _cache_put(key, shown, status, ctype, body, fetched)
    return Response(shown, status, body, ctype, fetched)
