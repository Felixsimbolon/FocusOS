"""One deterministic read-tool stage per request with persisted checkpoints."""

from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from focusos_api.agent_tasks import CommandInput, _checkpoint, _log, _rpc
from focusos_api.calendar_domain import CalendarEventError
from focusos_api.calendar_fetch import CalendarFetchError, CalendarWindow, fetch_calendar_window
from focusos_api.calendar_free_time import CalendarPlanningError, _local_boundary, calculate_free_time
from focusos_api.google_calendar import CalendarReconnectRequired
from focusos_api.calendar_normalize import normalize_window, occurrence_interval
from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.profiles import read_profile
from focusos_api.memory_search import MemorySearchInput, search_memories
from focusos_api.agent_planner import PlanningModelError, select_planning_intent
from focusos_api.planning_compiler import compile_plan
from focusos_api.planning_selection import SessionSelection
from focusos_api.planning_contract import PlanningValidationError
from focusos_api.tasks import list_tasks

MAX_CHECKPOINT_EVENTS = 80
logger = logging.getLogger(__name__)


class CommandRunNotFound(DatabaseUnavailable):
    pass


class CommandRequestConflict(ValueError):
    pass


class AgentRunInput(CommandInput):
    duration_minutes: int | None = Field(default=None, strict=True, ge=15, le=480)
    allow_split: bool = Field(default=False, strict=True)
    auto_calendar: bool = Field(default=False, strict=True)


class AgentRunState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    command: str
    status: str
    stage: str
    version: int
    model_turns: int
    tool_calls_count: int
    checkpoint: dict
    result: dict | None = None
    safe_error: str | None = None
    expires_at: datetime
    updated_at: datetime


def load_command_run(access_token: str, run_id: UUID) -> AgentRunState:
    with scoped_client(access_token) as (user_id, client):
        rows = (client.table("command_runs")
                .select("id,command,status,stage,version,model_turns,tool_calls_count,checkpoint,result,safe_error,expires_at,updated_at")
                .eq("id", str(run_id)).eq("user_id", user_id).limit(1).execute().data)
    if not isinstance(rows, list) or len(rows) != 1:
        raise CommandRunNotFound("Command run not found")
    run = AgentRunState.model_validate(rows[0])
    if run.status not in ("succeeded", "clarify", "failed") and run.expires_at <= datetime.now(timezone.utc):
        # SQL deliberately rejects writes to expired runs. Derive expiry from the saved timestamp.
        return run.model_copy(update={"status": "failed", "stage": "done", "result": None, "safe_error": "run_expired"})
    return run


def start_staged_run(access_token: str, request: AgentRunInput) -> AgentRunState:
    profile = read_profile(access_token)
    if profile is None:
        raise CalendarPlanningError("Save scheduling preferences first")
    window_start = datetime.now(timezone.utc).isoformat()
    initial = _rpc(access_token, "focusos_start_command_run", {
        "p_request_key": str(request.request_key), "p_command": request.command.strip(),
    })
    if not isinstance(initial, dict):
        raise DatabaseUnavailable("Unexpected command run")
    run_id = UUID(str(initial["id"]))
    options = {"duration_minutes": request.duration_minutes, "allow_split": request.allow_split,
               "auto_calendar": request.auto_calendar}
    if initial["status"] == "pending":
        _checkpoint(access_token, run_id, int(initial["version"]), "waiting", "start",
            {"duration_minutes": request.duration_minutes, "allow_split": request.allow_split,
             "auto_calendar": request.auto_calendar, "request_options": options,
             "window_start": window_start, "timezone": profile.timezone},
            None, 0, 0)
    saved = load_command_run(access_token, run_id)
    if saved.checkpoint.get("request_options", options) != options:
        raise CommandRequestConflict("request_options_changed")
    return saved


def _task_step(access_token: str, run: AgentRunState) -> tuple[dict, int]:
    args = {"status": "open", "limit": 20}
    _log(access_token, run.id, "tasks.list", args, "requested")
    page = list_tasks(access_token, status="open", limit=20)
    tasks = [
        {"id": str(task.id), "title": task.title,
         "due_kind": task.due_kind,
         "due_date": task.due_date.isoformat() if task.due_date else None,
         "due_at": task.due_at.isoformat() if task.due_at else None,
         "estimate_minutes": task.estimate_minutes,
         "source_id": str(task.source_id) if task.source_id else None}
        for task in page.tasks
    ]
    if "task_override" in run.checkpoint:
        tasks = run.checkpoint["task_override"]
    _log(access_token, run.id, "tasks.list", args, "succeeded")
    return {**run.checkpoint, "tasks": tasks, "tasks_truncated": page.truncated}, 1


def _calendar_step(access_token: str, run: AgentRunState) -> tuple[dict, int]:
    profile = read_profile(access_token)
    if profile is None:
        raise CalendarPlanningError("Scheduling profile required")
    if profile.timezone != run.checkpoint.get("timezone"):
        raise CalendarPlanningError("Scheduling timezone changed")
    current = datetime.fromisoformat(run.checkpoint["window_start"])
    zone = ZoneInfo(profile.timezone)
    end = _local_boundary(current.astimezone(zone).date() + timedelta(days=7), 0, zone)
    sessions = run.checkpoint.get("planning_selection", {}).get("sessions")
    if sessions:
        request = SessionSelection.model_validate(sessions)
        first = datetime.fromisoformat(request.date_start).date()
        last = datetime.fromisoformat(request.date_end).date()
        reference_day = current.astimezone(zone).date()
        if last < reference_day or last > reference_day + timedelta(days=13):
            raise CalendarPlanningError("Session dates must be within the next fourteen days")
        current = max(current, _local_boundary(first, 0, zone))
        end = _local_boundary(last + timedelta(days=1), 0, zone)
    args = {"calendar": "primary", "start": current.isoformat(), "end": end.isoformat()}
    _log(access_token, run.id, "calendar.get_events", args, "requested", ordinal=2)
    window = fetch_calendar_window(access_token, current, end)
    normalized = normalize_window(window)
    if len(normalized) > MAX_CHECKPOINT_EVENTS:
        raise CalendarPlanningError("Calendar context exceeds safe checkpoint size")
    events = []
    for item in normalized:
        start, finish = occurrence_interval(item)
        if finish <= window.start or start >= window.end:
            continue
        events.append({ "id": item.provider_id, "title": "Busy",
                       "start": start.isoformat(), "end": finish.isoformat()})
    if len(events) > MAX_CHECKPOINT_EVENTS:
        raise CalendarPlanningError("Calendar context exceeds safe checkpoint size")
    _log(access_token, run.id, "calendar.get_events", args, "succeeded", ordinal=2)
    return {**run.checkpoint, "calendar": {
        "timezone": profile.timezone, "start": window.start.isoformat(),
        "end": window.end.isoformat(), "fetched_at": window.fetched_at.isoformat(),
        "event_count": len(window.events), "events": events, "complete": True,
    }}, 2


def _free_step(access_token: str, run: AgentRunState) -> tuple[dict, int]:
    snapshot = run.checkpoint.get("calendar")
    if not isinstance(snapshot, dict) or snapshot.get("complete") is not True:
        raise CalendarPlanningError("Calendar snapshot is incomplete")
    profile = read_profile(access_token)
    if profile is None or profile.timezone != snapshot.get("timezone"):
        raise CalendarPlanningError("Scheduling profile changed")
    # Inventory only; the requested duration is resolved in the planning stage.
    args = {"duration_minutes": run.checkpoint.get("duration_minutes") or 15,
            "allow_split": run.checkpoint["allow_split"],
            "calendar_fetched_at": snapshot["fetched_at"]}
    _log(access_token, run.id, "calendar.find_free_time", args, "requested", ordinal=3)
    events = tuple({
        "id": item["id"], "summary": item["title"],
        "start": {"dateTime": item["start"]}, "end": {"dateTime": item["end"]},
    } for item in snapshot["events"])
    window = CalendarWindow(
        datetime.fromisoformat(snapshot["start"]),
        datetime.fromisoformat(snapshot["end"]),
        datetime.fromisoformat(snapshot["fetched_at"]),
        "primary", profile.timezone, events, complete=True,
    )
    result = calculate_free_time(window, timezone_name=profile.timezone,
        working_hours=profile.working_hours,
        duration_minutes=int(args["duration_minutes"]), allow_split=bool(args["allow_split"]))
    _log(access_token, run.id, "calendar.find_free_time", args, "succeeded", ordinal=3)
    return {**run.checkpoint, "free_time": result.model_dump(mode="json")}, 3


def _memory_step(access_token: str, run: AgentRunState) -> tuple[dict, int]:
    args = {"query": run.command[:1000], "limit": 5}
    _log(access_token, run.id, "memory.search", args, "requested", ordinal=4)
    result = search_memories(access_token, MemorySearchInput(query=args["query"], limit=5))
    _log(access_token, run.id, "memory.search", args, "succeeded", ordinal=4)
    return {**run.checkpoint, "memory_search": result.model_dump(mode="json")}, 4


def _planning_step(access_token: str, run: AgentRunState) -> AgentRunState:
    # A CAS lease prevents simultaneous model calls; an expired lease can be retried.
    now = datetime.now(timezone.utc)
    if run.status == "running" and run.updated_at + timedelta(seconds=35) > now:
        return run
    if run.status not in ("waiting", "running"):
        raise DatabaseUnavailable("Planning run unavailable")
    if not _checkpoint(access_token, run.id, run.version, "running", "planning",
                       run.checkpoint, None, run.model_turns, run.tool_calls_count):
        return load_command_run(access_token, run.id)
    leased = load_command_run(access_token, run.id)
    try:
        tasks = leased.checkpoint["tasks"]
        memories = leased.checkpoint.get("memory_search", {"mode": "none", "matches": []})
        profile = read_profile(access_token)
        if profile is None:
            raise PlanningValidationError("Scheduling profile missing", code="profile_required")
        if "planning_selection" in leased.checkpoint:
            raw = leased.checkpoint["planning_selection"]
        elif tasks:
            raw = select_planning_intent(leased.command, tasks, memories,
                reference_time=leased.checkpoint["window_start"], timezone_name=profile.timezone,
                duration_minutes=leased.checkpoint.get("duration_minutes"),
                allow_split=leased.checkpoint.get("allow_split", False))
        else:
            raw = {"status": "selected", "task_refs": [], "duration_minutes": None,
                   "day": "any", "date": None, "start_time": None, "end_time": None,
                   "evidence_refs": [], "questions": []}
        result, free = compile_plan(raw, tasks, leased.checkpoint, profile, command=leased.command)
        checkpoint = {**leased.checkpoint, "free_time": free.model_dump(mode="json"),
                      "resolved_duration_minutes": free.requested_minutes}
        status, error = ("succeeded" if result["status"] == "proposed" else "clarify"), None
    except (PlanningModelError, PlanningValidationError, CalendarPlanningError, KeyError, ValueError) as exc:
        result, status, checkpoint = None, "failed", leased.checkpoint
        error = exc.code if isinstance(exc, (PlanningModelError, PlanningValidationError)) else "invalid_time_constraint"
        logger.warning("Planning failed: code=%s", error)
    if not _checkpoint(access_token, leased.id, leased.version, status, "done",
                       checkpoint, result, leased.model_turns + (1 if leased.checkpoint.get("tasks") and "planning_selection" not in leased.checkpoint else 0),
                       leased.tool_calls_count, error):
        raise DatabaseUnavailable("Planning checkpoint lost")
    return load_command_run(access_token, leased.id)


def continue_staged_run(access_token: str, run_id: UUID) -> AgentRunState:
    run = load_command_run(access_token, run_id)
    if run.status in ("succeeded", "clarify", "failed"):
        return run
    if run.expires_at <= datetime.now(timezone.utc):
        return run.model_copy(update={"status": "failed", "stage": "done", "result": None, "safe_error": "run_expired"})
    if run.stage == "planning":
        return _planning_step(access_token, run)
    if run.status != "waiting" or run.expires_at <= datetime.now(timezone.utc):
        raise DatabaseUnavailable("Command run unavailable or expired")
    if run.tool_calls_count >= 8:
        raise DatabaseUnavailable("Tool budget exhausted")
    try:
        if run.stage == "start":
            checkpoint, count = _task_step(access_token, run)
            next_stage = "tasks"
        elif run.stage == "tasks":
            checkpoint, count = _calendar_step(access_token, run)
            next_stage = "calendar"
        elif run.stage == "calendar":
            checkpoint, count = _free_step(access_token, run)
            next_stage = "memory"
        elif run.stage == "memory":
            checkpoint, count = _memory_step(access_token, run)
            next_stage = "planning"
        else:
            raise DatabaseUnavailable("Invalid command stage")
    except (CalendarPlanningError, CalendarFetchError, CalendarEventError, CalendarReconnectRequired, DatabaseUnavailable):
        _checkpoint(access_token, run.id, run.version, "failed", "done",
                    run.checkpoint, None, run.model_turns, run.tool_calls_count,
                    "read_unavailable")
        raise
    if not _checkpoint(access_token, run.id, run.version, "waiting", next_stage,
                       checkpoint, None, run.model_turns, count):
        raise DatabaseUnavailable("Run checkpoint was updated elsewhere")
    return load_command_run(access_token, run.id)


def list_run_tools(access_token: str, run_id: UUID) -> list[dict]:
    # The run lookup enforces owner visibility even when its ledger is empty.
    load_command_run(access_token, run_id)
    with scoped_client(access_token) as (user_id, client):
        rows = (client.table("agent_tool_calls")
                .select("ordinal,name,status,safe_code,created_at")
                .eq("user_id", user_id).eq("run_id", str(run_id))
                .order("ordinal").limit(8).execute().data)
    if not isinstance(rows, list):
        raise DatabaseUnavailable("Tool history unavailable")
    return rows
