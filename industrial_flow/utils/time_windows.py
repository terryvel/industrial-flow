from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = ZoneInfo("America/Sao_Paulo")

def local_now(tz=DEFAULT_TIMEZONE) -> datetime:
    return datetime.now(tz)


def parse_datetime(value: str, tz=DEFAULT_TIMEZONE) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def floor_to_interval(dt: datetime, seconds: int) -> datetime:
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % seconds)
    return datetime.fromtimestamp(floored, tz=dt.tzinfo)


def build_historical_windows(start: datetime, end: datetime, window_seconds: int):
    current = start
    delta = timedelta(seconds=window_seconds)
    while current < end:
        next_end = min(current + delta, end)
        yield current, next_end
        current = next_end
