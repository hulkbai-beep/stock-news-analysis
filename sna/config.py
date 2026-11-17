"""Paths, the feed list and keys. Keys come only from environment variables (on Windows also from the user environment
in the registry, so a key added after this terminal opened still works). No key is read from or written to a file,
and nothing here prints a key."""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
FEEDS_FILE = PROJECT / "config" / "feeds.json"
UI_DIR = PROJECT / "ui"
FIXTURES_DIR = PROJECT / "tests" / "fixtures"

# Every variable this tool reads. Massive keeps accepting the old Polygon name.
KEYS = {
    "MASSIVE_API_KEY": "Massive (原 Polygon) 新闻，带 Massive 自己的情绪标签；免费 Basic 档可用",
    "POLYGON_API_KEY": "MASSIVE_API_KEY 的旧名字，二选一",
    "FMP_API_KEY": "FMP 个股新闻、新闻稿、评级、报价、经济日历",
    "SEC_USER_AGENT": "SEC 要求写明身份，例如 \"Tim Research tim@example.com\"；不设就不抓 SEC",
    "FINNHUB_API_KEY": "可选：Finnhub 公司新闻（免费注册）",
    "APCA_API_KEY_ID": "可选：Alpaca 新闻（Benzinga 源，免费账户）",
    "APCA_API_SECRET_KEY": "可选：和 APCA_API_KEY_ID 配对",
    "FRED_API_KEY": "可选：不设时用 FRED 公开 CSV，也是免费的",
}
OFFLINE_VALUE = "offline-fixture"


def data_dir() -> Path:
    """data/ in the project (cache and fetched-news history); SNA_DATA_DIR overrides it."""
    return Path(os.environ.get("SNA_DATA_DIR") or PROJECT / "data")


def offline() -> bool:
    """SNA_OFFLINE=1 serves every request from tests/fixtures (sample data for tests and screenshots)."""
    return os.environ.get("SNA_OFFLINE") == "1"


def load_user_env(names=tuple(KEYS)) -> None:
    """Fill missing variables from the Windows user environment. Values only go into this process's environment."""
    if os.name != "nt":
        return
    import winreg
    for name in names:
        if os.environ.get(name):
            continue
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                value = winreg.QueryValueEx(k, name)[0]
        except OSError:
            continue
        if value:
            os.environ[name] = str(value)


def key(name: str) -> str | None:
    if offline():
        return OFFLINE_VALUE
    value = (os.environ.get(name) or "").strip()
    return value or None


def massive_key() -> str | None:
    return key("MASSIVE_API_KEY") or key("POLYGON_API_KEY")


def secret_values() -> list[str]:
    """The key values currently set, so error text can be scrubbed of them before it is shown or logged."""
    return [v for v in ((os.environ.get(n) or "").strip() for n in KEYS if n != "SEC_USER_AGENT") if len(v) >= 6]


def key_status() -> dict:
    """Which variables are set (true/false only, never the value)."""
    return {name: bool((os.environ.get(name) or "").strip()) for name in KEYS}


def settings() -> dict:
    """data/settings.json: facts `python -m sna doctor` measured (for example FMP's time basis); never keys."""
    try:
        return json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_setting(name: str, value) -> None:
    current = settings()
    current[name] = value
    path = data_dir() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


_feeds: dict | None = None


def feeds() -> dict:
    global _feeds
    if _feeds is None:
        _feeds = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    return _feeds
