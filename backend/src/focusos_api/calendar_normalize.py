"""Pure Google Calendar occurrence normalization and busy filtering."""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from focusos_api.calendar_domain import CalendarEventError, CalendarOccurrence
from focusos_api.calendar_fetch import CalendarWindow


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CalendarEventError("Invalid Calendar timezone") from exc


def _date(value: object) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise CalendarEventError("Invalid Calendar date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CalendarEventError("Invalid Calendar date") from exc


def _timestamp(value: object, zone_name: str | None) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise CalendarEventError("Invalid Calendar timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CalendarEventError("Invalid Calendar timestamp") from exc
    if parsed.tzinfo is not None:
        if zone_name:
            local = parsed.astimezone(_zone(zone_name))
            if local.replace(tzinfo=None) != parsed.replace(tzinfo=None):
                raise CalendarEventError("Calendar timestamp does not match its timezone")
        return parsed
    if not zone_name:
        raise CalendarEventError("Calendar timestamp requires offset or timezone")
    zone = _zone(zone_name)
    early = parsed.replace(tzinfo=zone, fold=0)
    late = parsed.replace(tzinfo=zone, fold=1)
    if early.utcoffset() != late.utcoffset():
        raise CalendarEventError("Ambiguous or nonexistent local Calendar time")
    roundtrip = early.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
    if roundtrip != parsed:
        raise CalendarEventError("Nonexistent local Calendar time")
    return early


def normalize_event(event: dict, *, calendar_timezone: str,
                    observed_at: datetime) -> CalendarOccurrence | None:
    status = event.get("status", "confirmed")
    if status == "cancelled":
        return None
    if status not in ("confirmed", "tentative"):
        raise CalendarEventError("Invalid Calendar status")
    transparency = event.get("transparency", "opaque")
    if transparency == "transparent":
        return None
    if transparency != "opaque":
        raise CalendarEventError("Invalid Calendar transparency")
    attendees = event.get("attendees", [])
    if not isinstance(attendees, list):
        raise CalendarEventError("Invalid Calendar attendees")
    own = [entry for entry in attendees if isinstance(entry, dict) and entry.get("self") is True]
    if any(entry.get("responseStatus") == "declined" for entry in own):
        return None
    response = own[0].get("responseStatus") if own else None
    if response not in (None, "accepted", "tentative", "needsAction", "declined"):
        raise CalendarEventError("Invalid self invitation status")
    start, end = event.get("start"), event.get("end")
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise CalendarEventError("Calendar event missing bounds")
    if "date" in start or "date" in end:
        if "date" not in start or "date" not in end or "dateTime" in start or "dateTime" in end:
            raise CalendarEventError("Mixed Calendar event bounds")
        shape = dict(kind="all_day", start_date=_date(start["date"]),
                     end_date_exclusive=_date(end["date"]), timezone=calendar_timezone)
    else:
        shape = dict(kind="timed",
                     start_at=_timestamp(start.get("dateTime"), start.get("timeZone")),
                     end_at=_timestamp(end.get("dateTime"), end.get("timeZone")),
                     timezone=start.get("timeZone") or end.get("timeZone"))
    original = event.get("originalStartTime")
    if original is not None and not isinstance(original, dict):
        raise CalendarEventError("Invalid recurrence reference")
    original_start = (original.get("dateTime") or original.get("date")) if original else None
    if original_start is not None and not isinstance(original_start, str):
        raise CalendarEventError("Invalid recurrence reference")
    title = event.get("summary") or "Busy"
    if not isinstance(title, str):
        raise CalendarEventError("Invalid Calendar title")
    try:
        return CalendarOccurrence(
            provider_id=event.get("id"), title=title,
            calendar_id="primary", status=status, transparency=transparency,
            self_response=response,
            recurring_event_id=event.get("recurringEventId"),
            original_start=original_start, observed_at=observed_at, **shape,
        )
    except ValidationError as exc:
        raise CalendarEventError("Invalid Calendar occurrence") from exc


def normalize_window(window: CalendarWindow) -> tuple[CalendarOccurrence, ...]:
    return tuple(occurrence for raw in window.events
                 if (occurrence := normalize_event(raw, calendar_timezone=window.calendar_timezone,
                                                   observed_at=window.fetched_at)) is not None)


def occurrence_interval(occurrence: CalendarOccurrence) -> tuple[datetime, datetime]:
    if occurrence.kind == "timed":
        assert occurrence.start_at is not None and occurrence.end_at is not None
        return occurrence.start_at.astimezone(timezone.utc), occurrence.end_at.astimezone(timezone.utc)
    assert occurrence.start_date is not None and occurrence.end_date_exclusive is not None
    assert occurrence.timezone is not None
    zone = _zone(occurrence.timezone)
    start = datetime.combine(occurrence.start_date, time.min, tzinfo=zone)
    end = datetime.combine(occurrence.end_date_exclusive, time.min, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
