"""One month of the user's whole Google Calendar, for the month view on Home.

Google reads are limited to 14-day windows (calendar_fetch), so a month is read in up to
three windows and merged. Events FocusOS booked are marked so the view can colour them.
Read-only: nothing here writes to Calendar.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from focusos_api.calendar_fetch import fetch_calendar_window
from focusos_api.calendar_normalize import normalize_window
from focusos_api.database import scoped_client
from focusos_api.profiles import read_profile

WINDOW = timedelta(days=14)
MAX_EVENTS = 600
MONTHS_AROUND = 24  # how far back or ahead the view may go


class MonthOutOfRange(ValueError):
    pass


def month_bounds(month: str, zone: ZoneInfo, today: date) -> tuple[datetime, datetime]:
    try:
        first = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise MonthOutOfRange("Invalid month") from exc
    if abs((first.year - today.year) * 12 + first.month - today.month) > MONTHS_AROUND:
        raise MonthOutOfRange("Month out of range")
    following = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return datetime.combine(first, time.min, zone), datetime.combine(following, time.min, zone)


def windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    parts, cursor = [], start
    while cursor < end:
        parts.append((cursor, min(end, cursor + WINDOW)))
        cursor = parts[-1][1]
    return parts


def _focusos_event_ids(token: str) -> set[str]:
    with scoped_client(token) as (owner, client):
        rows = (client.table("approval_requests").select("event_id,provider_event_id,cancellation_status")
                .eq("user_id", owner).eq("status", "succeeded").order("created_at", desc=True).limit(300).execute().data)
    return {str(value) for row in rows if isinstance(row, dict) and row.get("cancellation_status") != "cancelled"
            for value in (row.get("event_id"), row.get("provider_event_id")) if value} if isinstance(rows, list) else set()


def month_events(token: str, month: str, now: datetime | None = None) -> dict:
    profile = read_profile(token)
    zone_name = profile.timezone if profile else "UTC"
    zone = ZoneInfo(zone_name)
    current = (now or datetime.now(timezone.utc)).astimezone(zone)
    start, end = month_bounds(month, zone, current.date())
    seen, events = set(), []
    for low, high in windows(start, end):
        for item in normalize_window(fetch_calendar_window(token, low, high)):
            key = (item.provider_id, item.start_at or item.start_date)
            if key in seen: continue
            seen.add(key)
            if item.kind == "timed":
                events.append({"id": item.provider_id, "title": item.title[:120], "all_day": False,
                               "start": item.start_at.astimezone(zone).isoformat(), "end": item.end_at.astimezone(zone).isoformat()})
            else:
                events.append({"id": item.provider_id, "title": item.title[:120], "all_day": True,
                               "start": item.start_date.isoformat(), "end": item.end_date_exclusive.isoformat()})
    own = _focusos_event_ids(token)
    for event in events:
        event["focusos"] = event["id"] in own
    events.sort(key=lambda event: (event["start"][:10], not event["all_day"], event["start"]))
    return {"month": month, "timezone": zone_name, "events": events[:MAX_EVENTS], "truncated": len(events) > MAX_EVENTS}
