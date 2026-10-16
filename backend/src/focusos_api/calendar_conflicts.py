"""Find FocusOS blocks that something else now overlaps, and move one to the next free time.

Detection runs when the user looks (no webhook or background session): one Calendar
read covering upcoming FocusOS blocks. Only timed, busy events count; all-day events
such as holidays are ignored, and FocusOS's own events never conflict with themselves.

Moving a block reuses the unified request pipeline with a prepared plan, so it needs
no model call: the new block is created first and the old one is removed only after
the new one exists. A failure therefore never leaves the user with neither block.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from focusos_api.agent_tasks import _checkpoint, _rpc
from focusos_api.calendar_fetch import fetch_calendar_window
from focusos_api.calendar_normalize import normalize_window, occurrence_interval
from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.jobs import JobInput, enqueue_job
from focusos_api.planning_selection import PlanningSelection

LOOKAHEAD_DAYS = 7


class RescheduleUnavailable(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _upcoming(token: str, now: datetime) -> list[dict]:
    with scoped_client(token) as (owner, client):
        rows = (client.table("approval_requests").select("id,task_id,event_id,provider_event_id,payload,status,cancellation_status")
                .eq("user_id", owner).eq("status", "succeeded").order("created_at", desc=True).limit(100).execute().data)
    upcoming = []
    for row in rows if isinstance(rows, list) else []:
        payload = row.get("payload") if isinstance(row, dict) else None
        if not isinstance(payload, dict) or row.get("cancellation_status") == "cancelled":
            continue
        try:
            start, end = datetime.fromisoformat(payload["start"]), datetime.fromisoformat(payload["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if now < start <= now + timedelta(days=LOOKAHEAD_DAYS):
            upcoming.append({**row, "start": start, "end": end})
    return upcoming


def overlaps(blocks: list[dict], occurrences, own_ids: set[str]) -> list[dict]:
    found = []
    for block in blocks:
        clashes = []
        for occurrence in occurrences:
            if occurrence.kind != "timed" or occurrence.provider_id in own_ids:
                continue
            start, end = occurrence_interval(occurrence)
            if start < block["end"] and end > block["start"]:
                clashes.append({"start": start.isoformat(), "end": end.isoformat()})
        if clashes:
            payload = block["payload"]
            found.append({"id": block["id"], "title": payload.get("title"), "start": payload["start"], "end": payload["end"],
                          "timezone": payload.get("timezone"), "conflicts": clashes[:3]})
    return found


def find_conflicts(token: str, now: datetime | None = None) -> list[dict]:
    current = now or datetime.now(timezone.utc)
    blocks = _upcoming(token, current)
    if not blocks:
        return []
    window = fetch_calendar_window(token, current, max(block["end"] for block in blocks))
    own = {str(value) for row in blocks for value in (row.get("event_id"), row.get("provider_event_id")) if value}
    return overlaps(blocks, normalize_window(window), own)


def _task(token: str, task_id: str) -> dict | None:
    with scoped_client(token) as (owner, client):
        rows = (client.table("tasks").select("id,title,status,priority,due_kind,due_date,due_at,estimate_minutes,source_id,project_id")
                .eq("user_id", owner).eq("id", task_id).limit(1).execute().data)
    row = rows[0] if isinstance(rows, list) and rows else None
    if not row or row.get("status") != "open":
        return None
    return {key: row.get(key) for key in ("id", "title", "due_kind", "due_date", "due_at", "estimate_minutes", "source_id", "priority", "project_id")}


def start_reschedule(token: str, approval_id: UUID, request_key: UUID, now: datetime | None = None) -> dict:
    """Start a prepared request that books the same work elsewhere, then removes the old block."""
    from focusos_api.unified_commands import ScheduleIntent, WorkIntent  # Avoids an import cycle.
    current = now or datetime.now(timezone.utc)
    block = next((row for row in _upcoming(token, current) if str(row["id"]) == str(approval_id)), None)
    if block is None:
        raise RescheduleUnavailable("Only an upcoming FocusOS block can be moved.")
    minutes = int((block["end"] - block["start"]).total_seconds() // 60)
    if not 15 <= minutes <= 480:
        raise RescheduleUnavailable("This block is too short or too long to move automatically.")
    title = str(block["payload"].get("title") or "Focus block").strip()[:200]
    task = _task(token, str(block["task_id"])) if block.get("task_id") else None
    command = f"Move {title} ({minutes} minutes) to the next free time."
    selection = PlanningSelection(status="selected", task_refs=["task-1"] if task else [], duration_minutes=minutes, day="any",
                                  date=None, start_time=None, end_time=None, evidence_refs=[], questions=[])
    schedule = ScheduleIntent(target="existing" if task else "activity", title_quote=None if task else title,
                              request_quote=command, selection=selection)
    intent = WorkIntent(capture=False, questions=[], schedules=[schedule], clarification=None, explanation="Move a conflicting block.")
    tasks = [task] if task else []
    initial = _rpc(token, "focusos_start_command_run", {"p_request_key": str(request_key), "p_command": command})
    if not isinstance(initial, dict): raise DatabaseUnavailable("Could not save reschedule request")
    run_id = UUID(str(initial["id"]))
    if initial["status"] == "pending":
        checkpoint = {"entrypoint": "unified", "window_start": current.isoformat(), "work_plan": intent.model_dump(),
                      "intent_tasks": tasks, "task_override": tasks, "replaces_approval_id": str(approval_id),
                      # Only the duration binds the new block; words in the title are not time limits.
                      "constraint_override": f"{minutes} minutes"}
        if not _checkpoint(token, run_id, int(initial["version"]), "waiting", "start", checkpoint, None, 0, 0):
            raise DatabaseUnavailable("Reschedule checkpoint changed")
    job = enqueue_job(token, JobInput(request_key=request_key, kind="planning", subject_id=run_id))
    return {"run_id": str(run_id), "background_job": job.model_dump(mode="json")}
