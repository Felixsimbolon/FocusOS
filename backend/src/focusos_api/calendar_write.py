"""One fixed-shape primary Calendar insert with stable-ID reconciliation."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.google_calendar import CALENDAR_EVENTS_API


class CalendarWriteConflict(Exception):
    pass


class CalendarWriteUnknown(Exception):
    pass


class CalendarWriteDeferred(Exception):
    pass


class CalendarWriteReconnect(Exception):
    pass


class CalendarWriteRejected(Exception):
    pass


@dataclass(frozen=True)
class CalendarWriteResult:
    event_id: str
    link: str | None
    reconciled: bool


def _event_url(event_id: str) -> str:
    return CALENDAR_EVENTS_API + "/" + event_id


def _safe_link(value: object) -> str | None:
    if not isinstance(value, str) or len(value)>2048:
        return None
    return value if value.startswith("https://calendar.google.com/") or value.startswith("https://www.google.com/calendar/") else None


def _verify_event(data: Any, approval: ApprovalRecord, *, reconciled: bool) -> CalendarWriteResult:
    action = approval.payload
    if not isinstance(data, dict) or data.get("id") != action.event_id or data.get("status") == "cancelled":
        raise CalendarWriteConflict("Provider event identity changed")
    extended = data.get("extendedProperties")
    marker = extended.get("private") if isinstance(extended, dict) else None
    if not isinstance(marker, dict) or marker.get("focusos_payload_hash") != approval.payload_hash:
        raise CalendarWriteConflict("Provider event marker differs")
    if data.get("summary") != action.title or data.get("attendees"):
        raise CalendarWriteConflict("Provider event content differs")
    try:
        start = datetime.fromisoformat(data["start"]["dateTime"])
        end = datetime.fromisoformat(data["end"]["dateTime"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CalendarWriteConflict("Provider event time missing") from exc
    if (start.tzinfo is None or end.tzinfo is None
        or start.astimezone(timezone.utc) != action.start.astimezone(timezone.utc)
        or end.astimezone(timezone.utc) != action.end.astimezone(timezone.utc)):
        raise CalendarWriteConflict("Provider event time differs")
    return CalendarWriteResult(action.event_id, _safe_link(data.get("htmlLink")), reconciled)


def _get_existing(client: httpx.Client, bearer: str, approval: ApprovalRecord) -> CalendarWriteResult | None:
    try:
        response = client.get(_event_url(approval.event_id),
            headers={"Authorization": "Bearer " + bearer},
            params={"fields":"id,summary,status,start,end,attendees,extendedProperties,htmlLink"},
            timeout=8.0)
    except httpx.HTTPError as exc:
        raise CalendarWriteUnknown("Calendar reconciliation unavailable") from exc
    if response.status_code == 404:
        return None
    if response.status_code in (401,403):
        raise CalendarWriteReconnect("Calendar grant unavailable")
    if response.status_code == 429:
        raise CalendarWriteDeferred("Calendar rate limited")
    if response.status_code != 200 or len(response.content)>32768:
        raise CalendarWriteUnknown("Calendar reconciliation unavailable")
    try:
        return _verify_event(response.json(),approval,reconciled=True)
    except ValueError as exc:
        raise CalendarWriteUnknown("Calendar response invalid") from exc


def insert_or_reconcile(approval: ApprovalRecord, bearer: str,
                        *, http_client: httpx.Client | None = None) -> CalendarWriteResult:
    if approval.payload.calendar_id != "primary" or approval.payload.guests or approval.payload.send_updates != "none":
        raise CalendarWriteConflict("Forbidden Calendar action")
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=10.0,follow_redirects=False)
    try:
        existing = _get_existing(client,bearer,approval)
        if existing:
            return existing
        action = approval.payload
        body = {
            "id": action.event_id,
            "summary": action.title,
            "start": {"dateTime": action.start.isoformat(),"timeZone":action.timezone},
            "end": {"dateTime": action.end.isoformat(),"timeZone":action.timezone},
            "reminders": {"useDefault": False},
            "extendedProperties": {"private": {"focusos_payload_hash":approval.payload_hash,
                                               "focusos_action_version":"1"}},
        }
        try:
            response = client.post(CALENDAR_EVENTS_API,
                params={"sendUpdates":"none","fields":"id,summary,status,start,end,attendees,extendedProperties,htmlLink"},
                headers={"Authorization":"Bearer " + bearer},json=body,timeout=10.0)
        except httpx.HTTPError:
            return _get_existing(client,bearer,approval) or _raise_unknown()
        if response.status_code in (401,403):
            raise CalendarWriteReconnect("Calendar grant unavailable")
        if response.status_code == 429:
            raise CalendarWriteDeferred("Calendar rate limited")
        if response.status_code == 409 or response.status_code >= 500:
            return _get_existing(client,bearer,approval) or _raise_unknown()
        if 400 <= response.status_code < 500:
            raise CalendarWriteRejected("Calendar rejected event")
        if response.status_code not in (200,201) or len(response.content)>32768:
            raise CalendarWriteUnknown("Calendar insert outcome unknown")
        try:
            return _verify_event(response.json(),approval,reconciled=False)
        except ValueError as exc:
            raise CalendarWriteUnknown("Calendar insert response invalid") from exc
    finally:
        if own_client:
            client.close()


def _raise_unknown() -> None:
    raise CalendarWriteUnknown("Calendar insert outcome unknown")
