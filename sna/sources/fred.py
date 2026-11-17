"""FRED (St. Louis Fed) series. Without a key the public graph CSV is used (fredgraph.csv, free); with FRED_API_KEY
the official API. Both give (date, value) pairs; missing days ('.' or empty) are skipped."""
from __future__ import annotations

import csv
import datetime as dt
import io

from .. import config
from . import SourceError

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
API_URL = "https://api.stlouisfed.org/fred/series/observations"


def parse_csv(text: str) -> list[tuple[str, float]]:
    """fredgraph.csv: a header (DATE or observation_date, then the series id) and one row per date."""
    rows = []
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise SourceError("FRED CSV 没有表头")
    for row in reader:
        if len(row) < 2 or not row[0][:4].isdigit():
            continue
        value = row[1].strip()
        if value in ("", "."):
            continue
        try:
            rows.append((row[0][:10], float(value)))
        except ValueError:
            continue
    return rows


def observations(ctx, series_id: str, start: dt.date) -> list[tuple[str, float]]:
    key = None if config.offline() else config.key("FRED_API_KEY")
    if key:
        data = ctx.get(API_URL, params={"series_id": series_id, "observation_start": start.isoformat(),
                                        "api_key": key, "file_type": "json"}, secret=("api_key",), ttl=3 * 3600).json()
        out = []
        for o in (data or {}).get("observations") or []:
            try:
                out.append((o["date"], float(o["value"])))
            except (KeyError, TypeError, ValueError):
                continue
        return out
    resp = ctx.get(CSV_URL, params={"id": series_id, "cosd": start.isoformat()}, ttl=3 * 3600)
    text = resp.text()
    if text.lstrip().startswith("<"):
        raise SourceError(f"FRED 没有返回 CSV（{series_id}）")
    return parse_csv(text)
