"""Recurring activities: a routine is a rule; each occurrence becomes an ordinary FocusOS block.

Occurrences are booked at most a week ahead (the planner's Calendar window) through the
same request pipeline as any schedule, so they get the same free-time check, approval and
idempotent Calendar write. A date is claimed in the database before it is booked, so two
requests can never book the same occurrence twice. Booking happens when the routine is
created and whenever Home tops it up (once a day when you open FocusOS).
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from focusos_api.agent_tasks import _checkpoint, _rpc
from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.job_routes import access, call
from focusos_api.jobs import JobInput, enqueue_job
from focusos_api.planning_selection import PlanningSelection
from focusos_api.profiles import read_profile

router = APIRouter()
LOOKAHEAD_DAYS = 7
MAX_OCCURRENCES = 7    # one request books at most this many blocks (job step budget)
LEAD_MINUTES = 15      # an occurrence starting sooner than this is left alone


class RoutineIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title_quote: str = Field(min_length=1, max_length=120)
    request_quote: str = Field(min_length=1, max_length=1000)
    weekdays: list[Annotated[int, Field(ge=1, le=7)]] = Field(min_length=1, max_length=7)
    start_time: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    duration_minutes: int = Field(ge=15, le=240)
    ends_on: str | None


def minutes(value: str) -> int:
    hours, mins = value.split(":")
    return int(hours) * 60 + int(mins)


def clock(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def upcoming_dates(routine: dict, now: datetime, zone: ZoneInfo) -> list[date]:
    """Dates in the coming week on which this routine still starts in the future."""
    local = now.astimezone(zone)
    ends = date.fromisoformat(routine["ends_on"]) if routine.get("ends_on") else None
    found = []
    for offset in range(LOOKAHEAD_DAYS):
        day = local.date() + timedelta(days=offset)
        start = datetime.combine(day, time.min, zone) + timedelta(minutes=routine["start_minute"])
        if day.isoweekday() in routine["weekdays"] and (ends is None or day <= ends) and start > local + timedelta(minutes=LEAD_MINUTES):
            found.append(day)
    return found


def occurrence_schedule(routine: dict, day: date):
    """One occurrence as a schedule part. The quoted title keeps its words from becoming time limits."""
    from focusos_api.unified_commands import ScheduleIntent  # Avoids an import cycle.
    start, end = clock(routine["start_minute"]), clock(routine["start_minute"] + routine["duration_minutes"])
    selection = PlanningSelection(status="selected", task_refs=[], duration_minutes=routine["duration_minutes"], day="date",
                                  date=day.isoformat(), start_time=start, end_time=end if end != "24:00" else "23:59",
                                  evidence_refs=[], questions=[])
    return ScheduleIntent(target="activity", title_quote=routine["title"],
                          request_quote=f'"{routine["title"]}" on {day.isoformat()} from {start} to {end}',
                          selection=selection, occurrence=day.isoformat())


def save_routine(token: str, request_key: UUID, intent: RoutineIntent) -> dict:
    title = intent.title_quote.replace('"', "").strip()[:120]
    with scoped_client(token) as (_, client):
        row = client.rpc("focusos_save_routine", {"p_request_key": str(request_key), "p_title": title,
            "p_weekdays": sorted(set(intent.weekdays)), "p_start_minute": minutes(intent.start_time),
            "p_duration_minutes": intent.duration_minutes, "p_ends_on": intent.ends_on}).execute().data
    if not isinstance(row, dict): raise DatabaseUnavailable("Routine was not saved")
    return row


def claim(token: str, routine_id: str, dates: list[date], run_id: UUID) -> list[date]:
    if not dates: return []
    with scoped_client(token) as (_, client):
        rows = client.rpc("focusos_claim_routine_dates", {"p_routine_id": routine_id, "p_dates": [day.isoformat() for day in dates],
                                                           "p_run_id": str(run_id)}).execute().data
    return [date.fromisoformat(str(value)) for value in rows] if isinstance(rows, list) else []


def plan_occurrences(token: str, run_id: UUID, routines: list[dict], zone: ZoneInfo, now: datetime, offset: int) -> tuple[list, list[dict]]:
    """Schedule parts for the claimed dates, and which routine/date each part index books."""
    schedules, mapping = [], []
    for routine in routines:
        room = MAX_OCCURRENCES - len(schedules)
        if room <= 0: break
        for day in claim(token, str(routine["id"]), upcoming_dates(routine, now, zone)[:room], run_id):
            mapping.append({"routine_id": str(routine["id"]), "date": day.isoformat(), "index": offset + len(schedules)})
            schedules.append(occurrence_schedule(routine, day))
    return schedules, mapping


def finish_occurrences(token: str, run_id: UUID, mapping: list[dict], outcomes: list[dict]) -> None:
    """Mark each claimed date booked or failed from its schedule part's outcome. Best effort."""
    for item in mapping:
        outcome = outcomes[item["index"]] if item["index"] < len(outcomes) else None
        status = "booked" if outcome and outcome.get("status") == "scheduled" else "failed"
        try:
            with scoped_client(token) as (_, client):
                client.rpc("focusos_finish_routine_date", {"p_routine_id": item["routine_id"], "p_date": item["date"],
                                                           "p_run_id": str(run_id), "p_status": status}).execute()
        except DatabaseUnavailable:
            continue


def describe(routine: dict) -> str:
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = "every day" if len(routine["weekdays"]) == 7 else "weekdays" if sorted(routine["weekdays"]) == [1, 2, 3, 4, 5] \
        else ", ".join(names[day - 1] for day in sorted(routine["weekdays"]))
    return f'{routine["title"]}: {days}, {clock(routine["start_minute"])}–{clock(routine["start_minute"] + routine["duration_minutes"])}'


def list_routines(token: str) -> list[dict]:
    with scoped_client(token) as (owner, client):
        rows = (client.table("routines").select("id,title,weekdays,start_minute,duration_minutes,ends_on,active,created_at")
                .eq("user_id", owner).order("created_at").limit(50).execute().data)
        occurrences = (client.table("routine_occurrences").select("routine_id,occurs_on,status").eq("user_id", owner)
                       .gte("occurs_on", (date.today() - timedelta(days=1)).isoformat()).order("occurs_on").limit(200).execute().data)
    rows = rows if isinstance(rows, list) else []
    upcoming: dict[str, list[dict]] = {}
    for item in occurrences if isinstance(occurrences, list) else []:
        upcoming.setdefault(str(item["routine_id"]), []).append({"date": item["occurs_on"], "status": item["status"]})
    return [{**row, "summary": describe(row), "upcoming": upcoming.get(str(row["id"]), [])[:7]} for row in rows]


def set_active(token: str, routine_id: UUID, active: bool) -> dict:
    with scoped_client(token) as (_, client):
        changed = client.rpc("focusos_set_routine_active", {"p_id": str(routine_id), "p_active": active}).execute().data
    if changed is not True: raise HTTPException(404, "Routine not found")
    return {"active": active}


def start_top_up(token: str, request_key: UUID, now: datetime | None = None) -> dict:
    """Book this week's unbooked occurrences of every active routine in one prepared request."""
    from focusos_api.unified_commands import WorkIntent  # Avoids an import cycle.
    current = now or datetime.now(timezone.utc)
    profile = read_profile(token)
    zone = ZoneInfo(profile.timezone if profile else "UTC")
    routines = [row for row in list_routines(token) if row["active"]]
    booked = {(str(row["id"]), item["date"]) for row in routines for item in row["upcoming"]}
    pending = [row for row in routines if any((str(row["id"]), day.isoformat()) not in booked for day in upcoming_dates(row, current, zone))]
    if not pending:
        return {"booking": 0}
    command = "Book routines: " + "; ".join(f'"{row["title"]}"' for row in pending)
    initial = _rpc(token, "focusos_start_command_run", {"p_request_key": str(request_key), "p_command": command[:1000]})
    if not isinstance(initial, dict): raise DatabaseUnavailable("Could not save routine request")
    run_id = UUID(str(initial["id"]))
    count = None  # unknown on a replayed request; the job result reports it
    if initial["status"] == "pending":
        schedules, mapping = plan_occurrences(token, run_id, pending, zone, current, 0)
        if not schedules:
            _checkpoint(token, run_id, int(initial["version"]), "failed", "done", {"entrypoint": "unified"},
                        {"summary": "Every routine occurrence this week is already booked."}, 0, 0, "nothing_to_book")
            return {"booking": 0}
        intent = WorkIntent(capture=False, questions=[], schedules=schedules, clarification=None, explanation="Book routine occurrences.")
        checkpoint = {"entrypoint": "unified", "window_start": current.isoformat(), "work_plan": intent.model_dump(),
                      "intent_tasks": [], "task_override": [], "routine_occurrences": mapping}
        if not _checkpoint(token, run_id, int(initial["version"]), "waiting", "start", checkpoint, None, 0, 0):
            raise DatabaseUnavailable("Routine checkpoint changed")
        count = len(schedules)
    job = enqueue_job(token, JobInput(request_key=request_key, kind="planning", subject_id=run_id))
    return {"booking": count, "run_id": str(run_id), "background_job": job.model_dump(mode="json")}


class TopUpInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID


@router.get("/routines")
def routines(token: str = Depends(access)): return call(list_routines, token)
@router.post("/routines/top-up", status_code=202)
def top_up(request_input: TopUpInput, token: str = Depends(access)): return call(start_top_up, token, request_input.request_key)
@router.post("/routines/{routine_id}/pause")
def pause(routine_id: UUID, token: str = Depends(access)): return call(set_active, token, routine_id, False)
@router.post("/routines/{routine_id}/resume")
def resume(routine_id: UUID, token: str = Depends(access)): return call(set_active, token, routine_id, True)
