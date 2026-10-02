"""Deterministic work-window subtraction and slot selection."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from focusos_api.calendar_fetch import CalendarWindow
from focusos_api.calendar_normalize import normalize_window, occurrence_interval
from focusos_api.profiles import WorkingHours


class CalendarPlanningError(ValueError):
    """Availability cannot be calculated safely."""


class Interval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: datetime
    end: datetime


class FreeTimeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str
    requested_minutes: int
    available_minutes: int
    allocated_minutes: int
    shortfall_minutes: int
    allow_split: bool
    slots: list[Interval]
    free_intervals: list[Interval]


def _merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = merged[-1][0], max(end, merged[-1][1])
        else:
            merged.append((start, end))
    return merged


def _local_boundary(day: date, minute: int, zone: ZoneInfo) -> datetime:
    naive = datetime.combine(day, time.min) + timedelta(minutes=minute)
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise CalendarPlanningError("Working-hour boundary is ambiguous at DST change")
    if first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != naive:
        raise CalendarPlanningError("Working-hour boundary is nonexistent at DST change")
    return first.astimezone(timezone.utc)


def _work_intervals(start: datetime, end: datetime, zone: ZoneInfo,
                    hours: WorkingHours) -> list[tuple[datetime, datetime]]:
    first_day = start.astimezone(zone).date()
    last_day = end.astimezone(zone).date()
    day = first_day
    result = []
    while day <= last_day:
        if day.isoweekday() in hours.days:
            local_start = _local_boundary(day, hours.start_minute, zone)
            local_end = _local_boundary(day, hours.end_minute, zone)
            clipped_start, clipped_end = max(local_start, start), min(local_end, end)
            if clipped_end > clipped_start:
                result.append((clipped_start, clipped_end))
        day += timedelta(days=1)
    return result


def _subtract(work: list[tuple[datetime, datetime]],
              busy: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    free = []
    for start, end in work:
        cursor = start
        for busy_start, busy_end in busy:
            if busy_end <= cursor:
                continue
            if busy_start >= end:
                break
            if busy_start > cursor:
                free.append((cursor, min(busy_start, end)))
            cursor = max(cursor, min(busy_end, end))
            if cursor >= end:
                break
        if cursor < end:
            free.append((cursor, end))
    return free


def calculate_free_time(window: CalendarWindow, *, timezone_name: str,
                        working_hours: WorkingHours, duration_minutes: int,
                        allow_split: bool = False,
                        deadline: datetime | date | None = None,
                        minimum_block_minutes: int = 1) -> FreeTimeResult:
    if not window.complete:
        raise CalendarPlanningError("Calendar window is incomplete")
    if duration_minutes < 1 or duration_minutes > 1440:
        raise CalendarPlanningError("Requested duration must be 1 to 1440 minutes")
    if not 1 <= minimum_block_minutes <= duration_minutes:
        raise CalendarPlanningError("Minimum block must fit the requested duration")
    if isinstance(deadline, date) and not isinstance(deadline, datetime):
        raise CalendarPlanningError("Date-only deadline needs a time clarification")
    if isinstance(deadline, datetime) and deadline.tzinfo is None:
        raise CalendarPlanningError("Deadline requires an offset")
    start, end = window.start, window.end
    if deadline is not None:
        end = min(end, deadline.astimezone(timezone.utc))
    if end <= start:
        return FreeTimeResult(timezone=timezone_name, requested_minutes=duration_minutes,
            available_minutes=0, allocated_minutes=0, shortfall_minutes=duration_minutes,
            allow_split=allow_split, slots=[], free_intervals=[])
    zone = ZoneInfo(timezone_name)
    work = _work_intervals(start, end, zone, working_hours)
    busy = _merge([(max(a, start), min(b, end)) for occurrence in normalize_window(window)
                   for a, b in [occurrence_interval(occurrence)] if b > start and a < end])
    free = _subtract(work, busy)
    durations = [int((b-a).total_seconds() // 60) for a, b in free]
    available = sum(durations)
    slots: list[Interval] = []
    if allow_split:
        remaining = duration_minutes
        for (a, _), minutes in zip(free, durations):
            if remaining <= 0:
                break
            selected = min(remaining, minutes)
            if 0 < remaining - selected < minimum_block_minutes:
                selected = remaining - minimum_block_minutes
            if selected >= minimum_block_minutes:
                slots.append(Interval(start=a, end=a + timedelta(minutes=selected)))
                remaining -= selected
        allocated = duration_minutes - remaining
    else:
        chosen = next(((a, b) for (a, b), minutes in zip(free, durations)
                       if minutes >= duration_minutes), None)
        if chosen:
            slots.append(Interval(start=chosen[0], end=chosen[0] + timedelta(minutes=duration_minutes)))
            allocated = duration_minutes
        else:
            allocated = 0
    shortfall = max(0, duration_minutes - allocated)
    return FreeTimeResult(timezone=timezone_name, requested_minutes=duration_minutes,
        available_minutes=available, allocated_minutes=allocated, shortfall_minutes=shortfall,
        allow_split=allow_split, slots=slots,
        free_intervals=[Interval(start=a, end=b) for a, b in free])
