"""Command line.

    python -m sna serve [--port 8790] [--open] [--offline]   the local page
    python -m sna doctor [--symbol NVDA]                    live check of every source, and FMP's time basis
    python -m sna news NVDA [--days 7] [--json]             the merged news table in the terminal (or as JSON)
    python -m sna status                                    which keys are set (yes/no), cache size
    python -m sna clear-cache                               drop cached responses (news history is kept)
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import statistics
import sys

from . import __version__, config, netio, news, textutil, timeutil


def _out(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:      # a Windows console without UTF-8
        print(text.encode(sys.stdout.encoding or "ascii", errors="replace").decode(sys.stdout.encoding or "ascii"))


def _status_line(s: dict) -> str:
    if s.get("skipped"):
        state = f"SKIP  {s['skipped']}"
    elif s.get("ok"):
        state = f"OK    {s['count']} 条" + (f"  ({s['error']})" if s.get("error") else "")
    else:
        state = f"FAIL  {s.get('error')}"
    return f"  {s['label']:<18} {state}  [{s.get('ms', 0)} ms]"


def cmd_status(_args) -> int:
    config.load_user_env()
    _out(f"stock-news-analysis {__version__}")
    for name, is_set in config.key_status().items():
        _out(f"  {name:<20} {'set' if is_set else 'not set'}   {config.KEYS[name]}")
    _out(f"  cache: {netio.cache_stats()}")
    _out(f"  news history: {news.history_stats()}")
    _out(f"  measured settings: {config.settings() or '{}'}")
    return 0


@contextlib.contextmanager
def _env(name: str, value: str):
    """Set an environment variable for the duration of a measurement, then put back what was there."""
    before = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = before


def _fmp_news_offset(symbol: str) -> list[float]:
    """Hours between FMP's news time read as UTC and Massive's UTC time for the same article."""
    from .sources import Ctx, fmp, massive
    with _env("SNA_FMP_NEWS_TZ", "UTC"):
        ctx = Ctx(refresh=True)
        ours, theirs = massive.ticker_news(ctx, symbol, days=7), fmp.stock_news(ctx, symbol, limit=100)
    by_url = {textutil.canonical_url(i["url"]): i for i in ours}
    by_title = {textutil.norm_title(i["title"]): i for i in ours}
    diffs = []
    for item in theirs:
        match = by_url.get(textutil.canonical_url(item["url"])) or by_title.get(textutil.norm_title(item["title"]))
        a, b = timeutil.parse_time(item["published_utc"]), timeutil.parse_time((match or {}).get("published_utc"))
        if a and b:
            diffs.append((a - b).total_seconds() / 3600)
    return diffs


def _fmp_calendar_basis() -> tuple[str | None, list[str]]:
    """US releases at 8:30 ET (payrolls, CPI, claims): their raw hour tells whether FMP's calendar is ET or UTC."""
    from .sources import Ctx, fmp
    today = timeutil.today_et()
    with _env("SNA_FMP_CAL_TZ", "UTC"):
        rows = fmp.economic_calendar(Ctx(refresh=True), (today - dt.timedelta(days=21)).isoformat(), today.isoformat())
    seen, votes = [], {"ET": 0, "UTC": 0}
    for r in rows:
        name = (r.get("event") or "").lower()
        if r.get("country") != "US" or not any(k in name for k in ("nonfarm", "initial jobless", "cpi")):
            continue
        when = timeutil.parse_time(r.get("time_utc"))
        if not when:
            continue
        hhmm = when.strftime("%H:%M")
        seen.append(f"{r['event']} {when:%Y-%m-%d} {hhmm}")
        expected_utc = timeutil.et_to_utc(dt.datetime.combine(when.date(), dt.time(8, 30)))
        if hhmm == "08:30":
            votes["ET"] += 1
        elif when == expected_utc:
            votes["UTC"] += 1
    if max(votes.values()) >= 2 and min(votes.values()) == 0:
        return max(votes, key=votes.get), seen
    return None, seen


def cmd_doctor(args) -> int:
    config.load_user_env()
    from . import macro, ticker
    sym = args.symbol.upper()
    _out(f"Live check, {timeutil.iso(timeutil.now())}, symbol {sym}. Keys are never printed.\n")
    failures = 0
    checks = [("宏观", lambda: [s for f in (macro.market, macro.fred_series, macro.calendar, macro.fed, macro.cot,
                                             news.macro_news) for s in f(refresh=True)["sources"]]),
              ("个股", lambda: news.ticker_news(sym, days=7, refresh=True)["sources"]
               + ticker.overview(sym, refresh=True)["sources"] + ticker.insiders(sym, refresh=True)["sources"]
               + ticker.filings(sym, refresh=True)["sources"] + ticker.analysts(sym, refresh=True)["sources"])]
    for title, run in checks:
        _out(title)
        for s in run():
            _out(_status_line(s))
            failures += 0 if (s.get("ok") or s.get("skipped")) else 1
    _out("\nFMP 时间基准")
    if config.massive_key() and config.key("FMP_API_KEY"):
        try:
            diffs = _fmp_news_offset(sym)
            if len(diffs) >= 3:
                median = statistics.median(diffs)
                basis = "UTC" if abs(median) < 1 else "ET" if 3.5 <= -median <= 5.5 else None
                _out(f"  新闻：{len(diffs)} 篇同时出现在 Massive，FMP 按 UTC 读时差中位数 {median:+.1f} 小时 -> "
                     f"{basis or '无法判断'}")
                if basis:
                    config.save_setting("fmp_news_tz", basis)
            else:
                _out(f"  新闻：只匹配到 {len(diffs)} 篇，样本太少，沿用 {config.settings().get('fmp_news_tz', 'ET')}")
        except Exception as e:  # a check, not a feature
            _out(f"  新闻：没测成 {netio.scrub(str(e))}")
    else:
        _out("  新闻：需要同时有 Massive 和 FMP 的 key 才能测")
    if config.key("FMP_API_KEY"):
        try:
            basis, seen = _fmp_calendar_basis()
            _out(f"  经济日历：{'; '.join(seen[:4]) or '近 3 周没有找到非农/CPI/初请'} -> {basis or '无法判断'}")
            if basis:
                config.save_setting("fmp_calendar_tz", basis)
        except Exception as e:  # a check, not a feature
            _out(f"  经济日历：没测成 {netio.scrub(str(e))}")
    _out(f"\n{'全部正常或已跳过' if not failures else f'{failures} 个来源失败（见上）'}；测到的时间基准存在 data/settings.json")
    return 1 if failures else 0


def cmd_news(args) -> int:
    config.load_user_env()
    data = news.ticker_news(args.symbol.upper(), days=args.days)
    if args.json:
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
        return 0
    for s in data["sources"]:
        _out(_status_line(s))
    _out(f"\n{len(data['items'])} 条（合并前 {data['raw_count']}），时间为美东")
    for i in data["items"]:
        when = timeutil.parse_time(i.get("published_utc"))
        stamp = timeutil.to_et(when).strftime("%m-%d %H:%M") if when else "--"
        mark = {"positive": "+", "negative": "-", "neutral": "="}.get((i.get("sentiment") or {}).get("label"), " ")
        also = f" (+{len(i['also'])})" if i.get("also") else ""
        _out(f"{stamp}  {mark} {i['source_label'][:12]:<12} {i['title'][:110]}{also}")
    return 0


def cmd_clear(_args) -> int:
    _out(f"cleared {netio.cache_clear()} cached responses")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m sna", description="Free macro data, news and filings for one ticker")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the local page")
    s.add_argument("--port", type=int, default=8790)
    s.add_argument("--open", action="store_true", help="open the browser")
    s.add_argument("--offline", action="store_true", help="sample data from tests/fixtures, no network")
    d = sub.add_parser("doctor", help="live check of every source")
    d.add_argument("--symbol", default="NVDA")
    n = sub.add_parser("news", help="merged news of one ticker in the terminal")
    n.add_argument("symbol")
    n.add_argument("--days", type=int, default=7)
    n.add_argument("--json", action="store_true", help="print the merged rows as JSON (for scripts and Claude)")
    sub.add_parser("status", help="keys set or not, cache size")
    sub.add_parser("clear-cache", help="drop cached responses")
    args = p.parse_args(argv)
    if args.cmd == "serve":
        if args.offline:
            os.environ["SNA_OFFLINE"] = "1"
        from .web import serve
        return serve(args.port, args.open)
    return {"doctor": cmd_doctor, "news": cmd_news, "status": cmd_status, "clear-cache": cmd_clear}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
