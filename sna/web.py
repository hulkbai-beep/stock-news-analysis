"""Local web UI: a standard-library HTTP server on 127.0.0.1, its JSON API and the page.

    python -m sna serve [--port 8790] [--open]

One HTML file (ui/app.html) renders the macro home page (/), a ticker page (/t/NVDA) and the status page (/status).
Each card asks its own API endpoint, so a slow source only delays its own card. Keys stay in this process: responses
say only whether a key is set. Requests must name this server as their host (no DNS rebinding); the API is read-only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, config, macro, netio, news, ticker, timeutil
from .sources import LAST

DEFAULT_PORT = 8790
STATIC = {"app.js": "text/javascript; charset=utf-8", "app.css": "text/css; charset=utf-8"}
PAGE = re.compile(r"^/(?:|status|t/[A-Za-z0-9.\-]{1,12})$")
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
MACRO = {"market": macro.market, "fred": macro.fred_series, "calendar": macro.calendar, "fed": macro.fed,
         "cot": macro.cot, "news": news.macro_news}
TICKER = {"overview": ticker.overview, "insiders": ticker.insiders, "filings": ticker.filings,
          "analysts": ticker.analysts}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def symbol_of(raw: str) -> str:
    sym = urllib.parse.unquote(raw or "").strip().upper()
    if not SYMBOL.match(sym):
        raise ApiError(400, "代码格式不对：字母开头，最多 10 位，可含 . 和 -")
    return sym


def api_status() -> dict:
    keys = config.key_status()
    return {"version": __version__, "offline": config.offline(), "now": timeutil.iso(timeutil.now()),
            "keys": keys, "key_help": config.KEYS, "massive_key": keys["MASSIVE_API_KEY"] or keys["POLYGON_API_KEY"],
            "cache": netio.cache_stats(), "history": news.history_stats(),
            "sources": sorted(LAST.values(), key=lambda s: s["name"])}


def api_ticker_news(sym: str, q: dict, refresh: bool) -> dict:
    try:
        days = max(1, min(60, int(q.get("days", "14"))))
    except ValueError:
        raise ApiError(400, "days 必须是 1 到 60 的整数") from None
    return news.ticker_news(sym, days=days, refresh=refresh)


class Handler(BaseHTTPRequestHandler):
    server_version = "sna"

    def _hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _send(self, code: int, body, ctype: str) -> None:
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; "
                             "style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; "
                             "form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str), "application/json; charset=utf-8")

    def do_GET(self):
        if self.headers.get("Host") not in self._hosts():
            self._send(403, "Forbidden", "text/plain")
            return
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            self._get(url.path, q, q.get("refresh") == "1")
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except Exception as e:  # keep the server alive; the card shows the error
            traceback.print_exc()
            self._json(500, {"error": netio.scrub(f"{type(e).__name__}: {e}")})

    def do_POST(self):
        self._send(405, "Read-only", "text/plain")

    def _get(self, path: str, q: dict, refresh: bool) -> None:
        if PAGE.match(path):
            self._send(200, (config.UI_DIR / "app.html").read_bytes(), "text/html; charset=utf-8")
        elif path.startswith("/static/") and path[8:] in STATIC:
            self._send(200, (config.UI_DIR / path[8:]).read_bytes(), STATIC[path[8:]])
        elif path == "/api/status":
            self._json(200, api_status())
        elif m := re.fullmatch(r"/api/macro/([a-z]+)", path):
            fn = MACRO.get(m.group(1))
            if not fn:
                raise ApiError(404, "没有这个地址")
            self._json(200, fn(refresh=refresh))
        elif m := re.fullmatch(r"/api/ticker/([^/]+)/([a-z]+)", path):
            sym, part = symbol_of(m.group(1)), m.group(2)
            if part == "news":
                self._json(200, api_ticker_news(sym, q, refresh))
            elif part in TICKER:
                self._json(200, TICKER[part](sym, refresh=refresh))
            else:
                raise ApiError(404, "没有这个地址")
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            raise ApiError(404, "没有这个地址")

    def log_message(self, fmt, *args):
        sys.stderr.write("[sna] " + netio.scrub(fmt % args) + "\n")


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind the same port and take some of the requests: refuse it
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def make_server(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    config.load_user_env()
    return Server(("127.0.0.1", port), Handler)


def serve(port: int = DEFAULT_PORT, open_browser: bool = False) -> int:
    srv = make_server(port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Stock news UI: {url}  (Ctrl+C to stop)" + ("  [offline sample data]" if config.offline() else ""))
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
