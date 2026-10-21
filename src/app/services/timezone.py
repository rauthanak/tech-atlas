"""The time zone of the person acting. Every write from the portal carries the
browser's zone (header X-Time-Zone); it is stored beside the time, and screens
show the time in that zone, never UTC. A missing or unknown zone falls back to
the radar's default (settings `radar.default_time_zone`)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Request

from app.services.settings_store import radar_settings


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def valid_tz(tz: str | None) -> str:
    """`tz` when it names a real zone, else the radar's default."""
    if tz:
        try:
            ZoneInfo(tz)
            return tz
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return radar_settings()["default_time_zone"]


def request_tz(request: Request) -> str:
    """FastAPI dependency: the acting person's zone, from X-Time-Zone."""
    return valid_tz(request.headers.get("x-time-zone"))
