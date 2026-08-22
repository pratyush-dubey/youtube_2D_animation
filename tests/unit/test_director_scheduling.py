from datetime import datetime
from zoneinfo import ZoneInfo

from app.director.scheduling import next_publish_slot


def test_next_publish_slot_uses_tuesday_thursday_saturday_at_7pm_ist():
    now = datetime(2026, 8, 22, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # Saturday after slot
    assert next_publish_slot(now).startswith("2026-08-25T19:00:00+05:30")
