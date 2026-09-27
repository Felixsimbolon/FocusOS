"""Fresh owner, grant, task and Calendar checks before any external mutation."""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError

from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.calendar_fetch import CalendarFetchError, CalendarWindow, fetch_calendar_window
from focusos_api.calendar_free_time import CalendarPlanningError, calculate_free_time
from focusos_api.connections import read_google_connection
from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.google_calendar import CALENDAR_READ_SCOPE, CalendarReconnectRequired
from focusos_api.google_oauth import GOOGLE_CALENDAR_WRITE_SCOPE
from focusos_api.profiles import read_profile


class ApprovalStale(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ApprovalPreflightUnavailable(Exception):
    pass


@dataclass(frozen=True)
class PreflightResult:
    checked_at: datetime
    calendar_fetched_at: datetime
    busy_event_count: int


def load_approval(access_token: str, approval_id: UUID) -> ApprovalRecord:
    with scoped_client(access_token) as (user_id, client):
        rows = (client.table("approval_requests")
                .select("id,run_id,block_index,task_id,connection_id,calendar_id,event_id,payload,payload_hash,status,authorization_mode,status_version,expires_at,lease_until,provider_event_id,provider_link,safe_code,created_at,decided_at,updated_at")
                .eq("id", str(approval_id)).eq("user_id", user_id).limit(1).execute().data)
    if not isinstance(rows, list) or len(rows) != 1:
        raise ApprovalStale("approval_missing")
    try:
        return ApprovalRecord.model_validate(rows[0])
    except ValidationError as exc:
        raise ApprovalStale("approval_invalid") from exc


def _load_current_task(access_token: str, task_id: UUID) -> dict:
    with scoped_client(access_token) as (user_id, client):
        rows = (client.table("tasks")
                .select("id,title,status,version,due_kind,due_date,due_at,source_id")
                .eq("id", str(task_id)).eq("user_id", user_id).limit(1).execute().data)
    if not isinstance(rows, list) or len(rows) != 1:
        raise ApprovalStale("task_missing")
    return rows[0]


def check_approval_preflight(access_token: str, approval: ApprovalRecord,
                             *, now: datetime | None = None) -> PreflightResult:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ApprovalStale("invalid_clock")
    current = current.astimezone(timezone.utc)
    action = approval.payload
    if approval.status not in ("approved", "executing") or approval.expires_at <= current:
        raise ApprovalStale("approval_expired_or_not_approved")
    if (action.run_id != approval.run_id or action.block_index != approval.block_index
        or action.task_id != approval.task_id or action.connection_id != approval.connection_id
        or action.calendar_id != approval.calendar_id or action.event_id != approval.event_id):
        raise ApprovalStale("payload_mismatch")
    if action.start <= current or action.end <= action.start or (action.end-current).total_seconds()>14*86400:
        raise ApprovalStale("slot_expired")
    task = _load_current_task(access_token, approval.task_id)
    if (task.get("status") != "open" or task.get("version") != action.task_version
        or task.get("title") != action.title
        or task.get("source_id") != (str(action.source_id) if action.source_id else None)):
        raise ApprovalStale("task_changed")
    if task.get("due_kind") == "date":
        raise ApprovalStale("date_only_deadline")
    deadline = None
    if task.get("due_at"):
        try:
            deadline = datetime.fromisoformat(task["due_at"])
        except (TypeError, ValueError) as exc:
            raise ApprovalStale("task_deadline_invalid") from exc
        if deadline.tzinfo is None or action.end > deadline:
            raise ApprovalStale("task_deadline_changed")
    connection = read_google_connection(access_token)
    if (connection is None or connection.id != approval.connection_id or connection.status != "connected"
        or CALENDAR_READ_SCOPE not in connection.granted_scopes
        or GOOGLE_CALENDAR_WRITE_SCOPE not in connection.granted_scopes):
        raise ApprovalStale("calendar_grant_changed")
    profile = read_profile(access_token)
    if profile is None or profile.timezone != action.timezone:
        raise ApprovalStale("profile_changed")
    try:
        window = fetch_calendar_window(access_token, current, action.end)
        if not window.complete or window.fetched_at < current:
            raise ApprovalPreflightUnavailable("Calendar snapshot is incomplete")
        minutes = int((action.end-action.start).total_seconds()/60)
        free = calculate_free_time(window, timezone_name=profile.timezone,
            working_hours=profile.working_hours, duration_minutes=minutes,
            deadline=deadline)
    except CalendarReconnectRequired as exc:
        raise ApprovalStale("calendar_reconnect_required") from exc
    except (CalendarFetchError, CalendarPlanningError, DatabaseUnavailable) as exc:
        raise ApprovalPreflightUnavailable("Calendar preflight unavailable") from exc
    if not any(slot.start<=action.start and slot.end>=action.end for slot in free.free_intervals):
        raise ApprovalStale("slot_conflict")
    return PreflightResult(current, window.fetched_at, len(window.events))
