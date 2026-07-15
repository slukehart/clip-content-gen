from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def utcnow_iso() -> str:
    """Current UTC time as ISO-8601 with trailing Z, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def et_month_bounds_utc(now: datetime | None = None) -> tuple[str, str]:
    """(start, next_start) as UTC ISO-8601 'Z' strings bounding the current
    ET calendar month. `now` is an aware datetime (defaults to real UTC now)."""
    now = now or datetime.now(timezone.utc)
    et = now.astimezone(_ET)
    start_et = et.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_et.month == 12:
        next_et = start_et.replace(year=start_et.year + 1, month=1)
    else:
        next_et = start_et.replace(month=start_et.month + 1)

    def _z(d: datetime) -> str:
        return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return _z(start_et), _z(next_et)
