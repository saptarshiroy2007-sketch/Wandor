"""Time helpers. The database stores NAIVE UTC datetimes; people read local time.

Everything that turns a stored instant into text a human reads (WhatsApp/SMS bodies)
goes through fmt_local(), so a class a teacher scheduled for 4:00 PM IST is announced as
4:00 PM, not 10:30 AM. The zone is DISPLAY_TIMEZONE (default Asia/Kolkata)."""
from datetime import datetime, timedelta, timezone

from .database import settings

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(settings.display_timezone)
except Exception:  # tzdata missing (e.g. slim Windows Python): India has no DST, so a fixed offset is exact
    _TZ = timezone(timedelta(hours=5, minutes=30))


def utcnow() -> datetime:
    """Naive UTC 'now' - same convention as every DateTime column."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_TZ)


def fmt_local(dt: datetime, fmt: str = "%d %b, %I:%M %p") -> str:
    return to_local(dt).strftime(fmt)


def month_start_utc(now: datetime) -> datetime:
    """Start of the calendar month containing `now` in the display zone, as naive UTC."""
    local = to_local(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).replace(tzinfo=None)
