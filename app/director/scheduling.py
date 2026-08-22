"""Publishing-slot selection for approved Director projects."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def next_publish_slot(
    now: datetime | None = None,
    weekdays: tuple[int, ...] = (1, 3, 5),  # Tuesday, Thursday, Saturday
    hour: int = 19,
    timezone_name: str = "Asia/Kolkata",
) -> str:
    zone = ZoneInfo(timezone_name)
    current = (now or datetime.now(zone)).astimezone(zone)
    for offset in range(0, 15):
        day = (current + timedelta(days=offset)).date()
        candidate = datetime.combine(day, time(hour=hour), tzinfo=zone)
        if candidate.weekday() in weekdays and candidate > current:
            return candidate.isoformat()
    raise RuntimeError("No publishing slot is configured")
