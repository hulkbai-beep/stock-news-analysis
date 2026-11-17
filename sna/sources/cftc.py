"""CFTC Commitments of Traders, Traders in Financial Futures (futures only), from the free Socrata API
(publicreporting.cftc.gov, dataset gpe5-46if, no key). Positions as of Tuesday, published Friday 3:30 pm ET.
Index and rate futures only; there is no single-stock COT."""
from __future__ import annotations

from . import SourceError

URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
COLUMNS = ("report_date_as_yyyy_mm_dd", "market_and_exchange_names", "cftc_contract_market_code", "open_interest_all",
           "dealer_positions_long_all", "dealer_positions_short_all", "asset_mgr_positions_long",
           "asset_mgr_positions_short", "lev_money_positions_long", "lev_money_positions_short")
GROUPS = {"asset_mgr": ("asset_mgr_positions_long", "asset_mgr_positions_short"),
          "lev_money": ("lev_money_positions_long", "lev_money_positions_short"),
          "dealer": ("dealer_positions_long_all", "dealer_positions_short_all")}


def _int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def fetch(ctx, markets: list[dict], weeks: int = 156) -> list[dict]:
    codes = ",".join("'" + m["code"].replace("'", "") + "'" for m in markets)
    data = ctx.get(URL, params={"$select": ",".join(COLUMNS), "$where": f"cftc_contract_market_code in({codes})",
                                "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": weeks * len(markets) + 20},
                   ttl=6 * 3600, timeout=30).json()
    if not isinstance(data, list):
        raise SourceError(f"CFTC：{(data or {}).get('message') if isinstance(data, dict) else '返回格式不对'}")
    by_code: dict[str, list[dict]] = {}
    for row in data:
        if isinstance(row, dict):
            by_code.setdefault(str(row.get("cftc_contract_market_code", "")).strip(), []).append(row)
    out = []
    for m in markets:
        rows = sorted(by_code.get(m["code"], []), key=lambda r: r.get("report_date_as_yyyy_mm_dd", ""), reverse=True)
        out.append(summarize(m, rows[:weeks]))
    return out


def percentile(latest: float, history: list[float]) -> float | None:
    """Share of the history at or below the latest value, 0 to 100."""
    if len(history) < 10:
        return None
    return round(100.0 * sum(1 for v in history if v <= latest) / len(history))


def summarize(market: dict, rows: list[dict]) -> dict:
    base = {"code": market["code"], "label": market["label"], "found": bool(rows)}
    if not rows:
        return base
    latest = rows[0]
    oi = _int(latest.get("open_interest_all"))
    groups = {}
    for name, (long_col, short_col) in GROUPS.items():
        nets = [_int(r.get(long_col)) - _int(r.get(short_col)) for r in rows]
        groups[name] = {"long": _int(latest.get(long_col)), "short": _int(latest.get(short_col)), "net": nets[0],
                        "change_1w": nets[0] - nets[1] if len(nets) > 1 else None,
                        "change_4w": nets[0] - nets[4] if len(nets) > 4 else None,
                        "net_pct_oi": round(100.0 * nets[0] / oi, 1) if oi else None,
                        "pctile_3y": percentile(nets[0], nets),
                        "spark": list(reversed(nets[:52]))}
    return {**base, "name": latest.get("market_and_exchange_names"),
            "date": str(latest.get("report_date_as_yyyy_mm_dd", ""))[:10], "open_interest": oi,
            "weeks": len(rows), **groups}
