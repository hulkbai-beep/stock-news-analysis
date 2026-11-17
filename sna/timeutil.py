"""Time parsing for every format the sources use, and US Eastern time without tzdata (Windows Python has no zone
database unless the tzdata package is installed, and this tool uses the standard library only)."""
from __future__ import annotations

import datetime as dt
import email.utils
import re

UTC = dt.timezone.utc
_GDELT = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$")
_DIGITS = re.compile(r"^\d{9,13}(?:\.\d+)?$")


def now() -> dt.datetime:
    return dt.datetime.now(UTC)


def _nth_sunday(year: int, month: int, n: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def et_offset(moment: dt.datetime) -> dt.timedelta:
    """UTC offset of US Eastern time at an aware moment: EDT from the second Sunday of March 2:00 EST (7:00 UTC) to
    the first Sunday of November 2:00 EDT (6:00 UTC), EST otherwise."""
    u = moment.astimezone(UTC)
    start = dt.datetime.combine(_nth_sunday(u.year, 3, 2), dt.time(7), UTC)
    end = dt.datetime.combine(_nth_sunday(u.year, 11, 1), dt.time(6), UTC)
    return dt.timedelta(hours=-4) if start <= u < end else dt.timedelta(hours=-5)


def to_et(moment: dt.datetime) -> dt.datetime:
    """An aware moment as US Eastern wall time (aware, with the fixed offset in force at that moment)."""
    return moment.astimezone(dt.timezone(et_offset(moment)))


def et_to_utc(naive: dt.datetime) -> dt.datetime:
    """A naive US Eastern wall time as aware UTC (an ambiguous hour in November resolves to EDT)."""
    for hours in (4, 5):
        candidate = (naive + dt.timedelta(hours=hours)).replace(tzinfo=UTC)
        if et_offset(candidate) == dt.timedelta(hours=-hours):
            return candidate
    return (naive + dt.timedelta(hours=5)).replace(tzinfo=UTC)   # the skipped March hour


def today_et() -> dt.date:
    return to_et(now()).date()


def parse_time(value, naive_tz: str = "UTC") -> dt.datetime | None:
    """ISO 8601, RFC 822 (RSS, lenient about day padding), Unix seconds or milliseconds, GDELT's 20261106T153000Z and
    'YYYY-MM-DD HH:MM:SS'. A value without a zone is read as UTC, or as US Eastern when naive_tz is "ET".
    Returns an aware UTC datetime, or None when the value cannot be read."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        moment = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and _DIGITS.match(value.strip())):
        number = float(value)
        if number > 1e12:
            number /= 1000.0
        return dt.datetime.fromtimestamp(number, UTC)
    elif isinstance(value, str):
        text = value.strip()
        m = _GDELT.match(text)
        if m:
            return dt.datetime(*map(int, m.groups()), tzinfo=UTC)
        moment = None
        try:
            moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00").replace(" UTC", "+00:00"))
        except ValueError:
            try:
                moment = email.utils.parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError):
                return None
        if moment is None:
            return None
    else:
        return None
    if moment.tzinfo is None:
        return et_to_utc(moment) if naive_tz == "ET" else moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def iso(moment: dt.datetime | None) -> str | None:
    """Aware datetime as '2026-11-06T13:54:53Z'."""
    if moment is None:
        return None
    return moment.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def add_business_days(day: dt.date, n: int) -> dt.date:
    """Weekdays only (US federal holidays are not counted here)."""
    while n > 0:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            n -= 1
    return day


def next_13f_deadline(today: dt.date) -> tuple[dt.date, dt.date]:
    """The quarter end whose 13F is due next and its deadline: 45 days after the quarter ends, moved to the next
    weekday when it falls on a weekend."""
    quarter_ends = [dt.date(today.year - 1, 12, 31)] + [dt.date(today.year, m, d) for m, d in
                                                         ((3, 31), (6, 30), (9, 30), (12, 31))]
    for q_end in quarter_ends:
        due = q_end + dt.timedelta(days=45)
        while due.weekday() >= 5:
            due += dt.timedelta(days=1)
        if due >= today:
            return q_end, due
    q_end = dt.date(today.year + 1, 3, 31)
    return q_end, q_end + dt.timedelta(days=45)
