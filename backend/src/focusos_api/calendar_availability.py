"""Read-only Today schedule and deterministic availability preview."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from focusos_api.calendar_fetch import CalendarFetchError, CalendarWindow, fetch_calendar_window
from focusos_api.calendar_free_time import (CalendarPlanningError, FreeTimeResult,
                                             _local_boundary, calculate_free_time)
from focusos_api.calendar_normalize import normalize_window, occurrence_interval
from focusos_api.profiles import read_profile


class CalendarProfileRequired(ValueError):
    """Scheduling preferences must be saved first."""


class BusyEventPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    kind: str
    start: datetime
    end: datetime
    recurring: bool


class AvailabilityPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calendar: str
    timezone: str
    window_start: datetime
    window_end: datetime
    fetched_at: datetime
    complete: bool
    event_count: int
    busy_events: list[BusyEventPreview]
    free_time: FreeTimeResult


def build_availability_preview(access_token: str, *, days: int = 1,
                               duration_minutes: int = 60, allow_split: bool = False,
                               deadline_at: datetime | None = None,
                               now: datetime | None = None,
                               calendar_window: CalendarWindow | None = None) -> AvailabilityPreview:
    if days < 1 or days > 7:
        raise CalendarPlanningError("Preview window must be 1 to 7 local days")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise CalendarPlanningError("Preview time requires timezone")
    profile = read_profile(access_token)
    if profile is None:
        raise CalendarProfileRequired("Save timezone and working hours first")
    zone = ZoneInfo(profile.timezone)
    start = current.astimezone(timezone.utc)
    last_local_day = current.astimezone(zone).date() + timedelta(days=days)
    end = _local_boundary(last_local_day, 0, zone)
    if end <= start:
        raise CalendarPlanningError("Preview window has ended")
    if deadline_at is not None and deadline_at.tzinfo is None:
        raise CalendarPlanningError("Deadline needs a timezone offset")
    window = calendar_window or fetch_calendar_window(access_token, start, end)
    if not window.complete or window.start != start or window.end != end:
        raise CalendarFetchError("Calendar window is incomplete or mismatched")
    occurrences = normalize_window(window)
    busy_events = []
    for occurrence in occurrences:
        event_start, event_end = occurrence_interval(occurrence)
        if event_end <= start or event_start >= end:
            continue
        busy_events.append(BusyEventPreview(
            title=occurrence.title, kind=occurrence.kind,
            start=max(event_start, start), end=min(event_end, end),
            recurring=occurrence.recurring_event_id is not None,
        ))
    busy_events.sort(key=lambda event: event.start)
    free_time = calculate_free_time(window, timezone_name=profile.timezone,
        working_hours=profile.working_hours, duration_minutes=duration_minutes,
        allow_split=allow_split, deadline=deadline_at)
    return AvailabilityPreview(calendar=window.calendar_id, timezone=profile.timezone,
        window_start=window.start, window_end=window.end, fetched_at=window.fetched_at,
        complete=True, event_count=len(window.events), busy_events=busy_events,
        free_time=free_time)
