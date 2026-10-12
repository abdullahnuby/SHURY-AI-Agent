from __future__ import annotations

import os
from datetime import datetime, timedelta, tzinfo, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = os.getenv("AGENT_TIMEZONE", "Africa/Cairo")


def _last_weekday(year: int, month: int, weekday: int) -> datetime:
    """Return the last requested weekday at midnight for a given month."""
    if month == 12:
        first_next = datetime(year + 1, 1, 1)
    else:
        first_next = datetime(year, month + 1, 1)
    last = first_next - timedelta(days=1)
    delta = (last.weekday() - weekday) % 7
    return last - timedelta(days=delta)


class _CairoFallbackTZ(tzinfo):
    """Small fallback for Windows when IANA tzdata is unavailable.

    tzdata remains the authoritative source when installed. This fallback covers the
    current Egyptian rule used by the agent's default Cairo timezone: UTC+2 standard
    time and UTC+3 daylight time, with DST running from the last Friday of April
    through the last Friday of October. It is intentionally limited to 2023+; for
    older dates we use standard UTC+2 rather than pretending to reproduce historical
    Egypt transitions.
    """

    key = "Africa/Cairo"
    _STD = timedelta(hours=2)
    _DST = timedelta(hours=3)

    def _is_dst(self, dt: datetime | None) -> bool:
        if dt is None or dt.year < 2023:
            return False
        start = _last_weekday(dt.year, 4, 4)  # Friday
        end = _last_weekday(dt.year, 10, 4)   # Friday
        naive = dt.replace(tzinfo=None)
        return start <= naive < end

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return self._DST if self._is_dst(dt) else self._STD

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=1) if self._is_dst(dt) else timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "EEST" if self._is_dst(dt) else "EET"


def get_timezone(name: str | None = None) -> tzinfo:
    requested = name or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(requested)
    except ZoneInfoNotFoundError:
        if requested == "Africa/Cairo":
            return _CairoFallbackTZ()
        local = datetime.now().astimezone().tzinfo
        return local or timezone.utc


def now_in_timezone(name: str | None = None) -> datetime:
    return datetime.now(get_timezone(name))


def attach_timezone(value: datetime, name: str | None = None) -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=get_timezone(name))
