"""Offline sample data (SNA_OFFLINE=1 or `serve --offline`): every request is answered from tests/fixtures/http, in
the raw format of the real source, so the parsers and the page can be tested without network or keys.

The sample company is the made-up ticker DEMO (Demo Robotics Inc), so no real company is shown with invented news
or insider trades. Dates in the templates are relative ({{date:-3}}, {{iso:-5h}} ...) and filled in at request time,
so time windows keep working. Numeric series (FRED, CFTC, quotes) are generated from a fixed seed: they look like
data but are not data.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import json
import math
import random
import re
import urllib.parse

from . import config, timeutil

HTTP = config.FIXTURES_DIR / "http"
SAMPLE_SYMBOL = "DEMO"
SAMPLE_CIK = "0009999901"
_PLACEHOLDER = re.compile(r"\{\{(date|iso|rfc|unix|fmp|gdelt):([+-]?\d+)([hdm]?)\}\}")
# (pattern on the URL, fixture file); first match wins
ROUTES = [
    (r"/v2/reference/news", "massive_news.json"),
    (r"financialmodelingprep\.com/stable/news/stock", "fmp_news_stock.json"),
    (r"financialmodelingprep\.com/stable/news/press-releases", "fmp_press.json"),
    (r"financialmodelingprep\.com/stable/news/general-latest", "fmp_general.json"),
    (r"financialmodelingprep\.com/stable/profile", "fmp_profile.json"),
    (r"financialmodelingprep\.com/stable/grades", "fmp_grades.json"),
    (r"financialmodelingprep\.com/stable/price-target-consensus", "fmp_target.json"),
    (r"financialmodelingprep\.com/stable/economic-calendar", "fmp_calendar.json"),
    (r"seekingalpha\.com/api/sa/combined/", "seekingalpha.xml"),
    (r"nasdaq\.com/feed/rssoutbound", "nasdaq.xml"),
    (r"feeds\.content\.dowjones\.io", "marketwatch.xml"),
    (r"zerohedge", "zerohedge.xml"),
    (r"federalreserve\.gov/feeds/press_monetary", "fed_monetary.xml"),
    (r"federalreserve\.gov/feeds/speeches", "fed_speeches.xml"),
    (r"api-one\.wallstcn\.com", "wallstcn.json"),
    (r"api\.gdeltproject\.org", "gdelt.json"),
    (r"finnhub\.io", "finnhub.json"),
    (r"data\.alpaca\.markets", "alpaca.json"),
    (r"sec\.gov/files/company_tickers\.json", "sec_tickers.json"),
    (rf"data\.sec\.gov/submissions/CIK{SAMPLE_CIK}\.json", "sec_submissions.json"),
]
TICKER_PARAMS = ("ticker", "symbols", "symbol")


def _offset(n: int, unit: str, default: str) -> dt.timedelta:
    unit = unit or default
    return {"m": dt.timedelta(minutes=n), "h": dt.timedelta(hours=n), "d": dt.timedelta(days=n)}[unit]


def render(text: str, now: dt.datetime | None = None) -> str:
    """Fill the relative-time placeholders of a template."""
    now = (now or timeutil.now()).replace(second=0, microsecond=0)

    def fill(m):
        kind, n, unit = m.group(1), int(m.group(2)), m.group(3)
        if kind == "date":
            return (timeutil.to_et(now).date() + _offset(n, unit, "d")).isoformat()
        moment = now + _offset(n, unit, "h")
        if kind == "iso":
            return timeutil.iso(moment)
        if kind == "rfc":
            return email.utils.format_datetime(moment)
        if kind == "unix":
            return str(int(moment.timestamp()))
        if kind == "fmp":
            return timeutil.to_et(moment).strftime("%Y-%m-%d %H:%M:%S")
        return moment.strftime("%Y%m%dT%H%M%SZ")

    return _PLACEHOLDER.sub(fill, text)


def _file(name: str) -> bytes:
    return render((HTTP / name).read_text(encoding="utf-8")).encode("utf-8")


def _ctype(name: str) -> str:
    return {"json": "application/json", "xml": "application/xml", "htm": "text/html", "csv": "text/csv"}[
        name.rsplit(".", 1)[-1]] + "; charset=utf-8"


def _not_found(what: str):
    return 404, "text/plain; charset=utf-8", f"offline sample data has no {what}".encode()


def lookup(url: str) -> tuple[int, str, bytes]:
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    host_path = (parts.hostname or "") + parts.path
    if "financialmodelingprep.com/stable/" in host_path and parts.path.endswith(("/quote", "/batch-quote")):
        return 200, "application/json", json.dumps(quotes(query.get("symbols") or query.get("symbol") or "")).encode()
    if "fred.stlouisfed.org" in host_path:
        return 200, "text/csv; charset=utf-8", fred_csv(query.get("id", ""), query.get("cosd")).encode()
    if "publicreporting.cftc.gov" in host_path:
        return 200, "application/json", json.dumps(cftc_rows(query.get("$where", ""))).encode()
    for key in TICKER_PARAMS:
        value = query.get(key)
        if value and value.upper().split(",")[0] != SAMPLE_SYMBOL:
            return _not_found(f"ticker {value} (only {SAMPLE_SYMBOL})")
    if "gdeltproject.org" in host_path and "demo" not in query.get("query", "").lower():
        return _not_found("GDELT results for this company")
    if "seekingalpha.com" in host_path and not parts.path.endswith(f"/{SAMPLE_SYMBOL}.xml"):
        return _not_found("ticker in this feed")
    m = re.search(r"/Archives/edgar/data/\d+/\d+/([^/]+)$", parts.path)
    if m:
        name = m.group(1)
        path = HTTP / "sec" / name
        return (200, _ctype(name), _file(f"sec/{name}")) if path.exists() else _not_found(f"filing {name}")
    for pattern, name in ROUTES:
        if re.search(pattern, url):
            return 200, _ctype(name), _file(name)
    return _not_found(host_path)


# ---------- generated numbers ----------

def _rng(*seed) -> random.Random:
    return random.Random(int(hashlib.sha256(repr(seed).encode()).hexdigest()[:12], 16))


QUOTE_BASE = {"SPY": 672.0, "QQQ": 604.0, "DIA": 471.0, "IWM": 241.0, "TLT": 89.5, "HYG": 80.6, "GLD": 368.0,
              "USO": 72.4, "UUP": 27.1, "XLK": 286.0, "XLC": 114.0, "XLY": 236.0, "XLF": 53.1, "XLV": 142.0,
              "XLI": 151.0, "XLE": 88.2, "XLB": 89.9, "XLP": 78.4, "XLU": 86.0, "XLRE": 41.9, "SMH": 342.0,
              "DEMO": 158.42}


def quotes(symbols: str) -> list[dict]:
    out = []
    for sym in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
        if sym not in QUOTE_BASE:
            continue
        r = _rng("quote", sym, timeutil.today_et().isoformat())
        pct = 3.1 if sym == SAMPLE_SYMBOL else round(r.uniform(-2.2, 2.2), 2)
        price = QUOTE_BASE[sym]
        prev = price / (1 + pct / 100)
        out.append({"symbol": sym, "name": f"{sym} (sample)", "price": price, "changePercentage": pct,
                    "change": round(price - prev, 2), "volume": int(r.uniform(2e6, 9e7)),
                    "dayLow": round(min(price, prev) * 0.993, 2), "dayHigh": round(max(price, prev) * 1.006, 2),
                    "yearHigh": round(price * 1.12, 2), "yearLow": round(price * 0.71, 2),
                    "marketCap": 48_200_000_000 if sym == SAMPLE_SYMBOL else None, "priceAvg50": round(price * 0.97, 2),
                    "priceAvg200": round(price * 0.9, 2), "exchange": "NASDAQ", "open": round(prev * 1.002, 2),
                    "previousClose": round(prev, 2), "timestamp": int(timeutil.now().timestamp())})
    return out


# id -> (frequency, last value, daily volatility, monthly growth for price indexes)
FRED_SHAPES = {
    "DFF": ("d", 3.88, 0.002, None), "DGS2": ("d", 3.56, 0.03, None), "DGS10": ("d", 4.13, 0.035, None),
    "T10YIE": ("d", 2.31, 0.015, None), "BAMLH0A0HYM2": ("d", 3.05, 0.04, None),
    "BAMLC0A0CM": ("d", 0.82, 0.01, None), "NFCI": ("w", -0.52, 0.02, None), "VIXCLS": ("d", 18.4, 0.9, None),
    "VXVCLS": ("d", 20.6, 0.6, None), "DTWEXBGS": ("d", 121.3, 0.25, None), "DCOILWTICO": ("d", 61.2, 1.0, None),
    "CPIAUCSL": ("m", 328.4, None, 0.0025), "CPILFESL": ("m", 334.9, None, 0.0026),
    "PCEPILFE": ("m", 128.6, None, 0.0024), "UNRATE": ("m", 4.3, 0.08, None), "PAYEMS": ("m", 160_350, 60, None),
    "ICSA": ("w", 224_000, 7000, None), "SP500": ("d", 6745.0, 45.0, None), "NASDAQCOM": ("d", 22880.0, 190.0, None),
    "DJIA": ("d", 47120.0, 260.0, None),
}


def _dates(freq: str, start: dt.date, end: dt.date) -> list[dt.date]:
    out, day = [], start
    while day <= end:
        if freq == "d" and day.weekday() < 5:
            out.append(day)
        elif freq == "w" and day.weekday() == 4:
            out.append(day)
        elif freq == "m" and day.day == 1:
            out.append(day)
        day += dt.timedelta(days=1)
    return out


def _walk(series_id: str, start: dt.date) -> list[tuple[dt.date, float]]:
    freq, last, vol, growth = FRED_SHAPES[series_id]
    today = timeutil.today_et()
    end = today - dt.timedelta(days={"d": 1, "w": 7, "m": 40}[freq])
    dates = _dates(freq, start, end)
    r = _rng("fred", series_id)
    values = [last]
    for _ in dates[1:]:
        if growth:
            values.append(values[-1] / (1 + growth + r.gauss(0, 0.001)))
        else:
            values.append(values[-1] - r.gauss(0, vol))
    values.reverse()
    return list(zip(dates, values))


def fred_csv(series_id: str, cosd: str | None) -> str:
    start = timeutil.parse_date(cosd) or timeutil.today_et() - dt.timedelta(days=800)
    if series_id in ("T10Y2Y", "T10Y3M"):
        ten = dict(_walk("DGS10", start))
        other = dict(_walk("DGS2", start)) if series_id == "T10Y2Y" else {d: 3.83 + 0.1 * math.sin(d.toordinal() / 40)
                                                                            for d in ten}
        rows = [(d, ten[d] - other[d]) for d in sorted(ten) if d in other]
    elif series_id in FRED_SHAPES:
        rows = _walk(series_id, start)
    else:
        return "observation_date,UNKNOWN\n"
    digits = 0 if series_id in ("PAYEMS", "ICSA") else 3 if series_id.startswith(("CPI", "PCE")) else 2
    lines = [f"observation_date,{series_id}"]
    for i, (d, v) in enumerate(rows):
        lines.append(f"{d.isoformat()},{'' if i % 97 == 50 else f'{v:.{digits}f}'}")   # FRED leaves holidays empty
    return "\n".join(lines) + "\n"


COT_SHAPES = {  # code -> name, open interest, (asset manager net, leveraged funds net, dealer net) as share of OI
    "13874A": ("E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE", 1_986_532, (0.467, -0.187, -0.347)),
    "209742": ("NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE", 268_000, (0.21, -0.12, -0.05)),
    "239742": ("RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE", 452_000, (0.05, -0.11, 0.09)),
    "124603": ("DJIA x $5 - CHICAGO BOARD OF TRADE", 88_000, (0.12, -0.08, -0.02)),
    "042601": ("UST 2Y NOTE - CHICAGO BOARD OF TRADE", 4_310_000, (0.30, -0.38, 0.05)),
    "043602": ("UST 10Y NOTE - CHICAGO BOARD OF TRADE", 5_020_000, (0.36, -0.22, -0.11)),
    "020601": ("UST BOND - CHICAGO BOARD OF TRADE", 1_890_000, (0.33, -0.06, -0.14)),
    "1170E1": ("VIX FUTURES - CBOE FUTURES EXCHANGE", 395_000, (-0.04, -0.21, 0.19)),
    "098662": ("USD INDEX - ICE FUTURES U.S.", 36_500, (0.02, 0.18, -0.12)),
}


def cftc_rows(where: str) -> list[dict]:
    codes = re.findall(r"'([^']+)'", where) or list(COT_SHAPES)
    last_tuesday = timeutil.today_et() - dt.timedelta(days=(timeutil.today_et().weekday() - 1) % 7 or 7)
    out = []
    for code in codes:
        if code not in COT_SHAPES:
            continue
        name, oi, shares = COT_SHAPES[code]
        r = _rng("cot", code)
        nets = [s * oi for s in shares]
        for week in range(156):
            day = last_tuesday - dt.timedelta(weeks=week)
            open_interest = int(oi * (1 + 0.08 * math.sin(week / 9) + r.gauss(0, 0.01)))
            row = {"report_date_as_yyyy_mm_dd": f"{day.isoformat()}T00:00:00.000", "market_and_exchange_names": name,
                   "cftc_contract_market_code": code, "open_interest_all": str(open_interest)}
            for (long_col, short_col), net in zip((("asset_mgr_positions_long", "asset_mgr_positions_short"),
                                                   ("lev_money_positions_long", "lev_money_positions_short"),
                                                   ("dealer_positions_long_all", "dealer_positions_short_all")), nets):
                gross = open_interest * 0.25
                row[long_col] = str(max(0, int(gross + net / 2)))
                row[short_col] = str(max(0, int(gross - net / 2)))
            out.append(row)
            nets = [n - r.gauss(0, oi * 0.012) for n in nets]
    out.sort(key=lambda r: r["report_date_as_yyyy_mm_dd"], reverse=True)
    return out
