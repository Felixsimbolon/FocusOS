"""Compile a validated model selection into deterministic, source-owned work blocks."""
from datetime import date, datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from focusos_api.calendar_fetch import CalendarWindow
from focusos_api.calendar_free_time import FreeTimeResult, _local_boundary, calculate_free_time
from focusos_api.planning_contract import PlanningValidationError, task_handles, validate_planning_response
from focusos_api.planning_selection import PlanningSelection
from focusos_api.planning_request import explicit_constraints
from focusos_api.profiles import ProfileRecord

START_BUFFER_MINUTES = 5


def _empty_free(timezone_name: str, duration: int, allow_split: bool) -> FreeTimeResult:
    return FreeTimeResult(timezone=timezone_name, requested_minutes=duration, available_minutes=0,
        allocated_minutes=0, shortfall_minutes=duration, allow_split=allow_split, slots=[], free_intervals=[])


def _unavailable(status: str, code: str, message: str, free: FreeTimeResult,
                 task_refs: list[str] | None = None) -> tuple[dict, FreeTimeResult]:
    free = free.model_copy(update={"slots": [], "allocated_minutes": 0,
                                  "shortfall_minutes": free.requested_minutes})
    return {"schema_version": "1", "status": status, "safe_code": code,
            "task_refs": task_refs or [], "blocks": [], "requested_minutes": free.requested_minutes,
            "scheduled_minutes": 0, "shortfall_minutes": free.requested_minutes,
            "assumptions": [], "questions": [message] if status == "needs_clarification" else [],
            "summary": message, "actionable": False}, free


def _clock(value: str | None, fallback: int) -> int:
    if value is None:
        return fallback
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise PlanningValidationError("Invalid scheduling clock", code="invalid_time_constraint")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def compile_plan(raw: object, tasks: list[dict], checkpoint: dict, profile: ProfileRecord,
                 *, now: datetime | None = None, command: str | None = None) -> tuple[dict, FreeTimeResult]:
    try:
        intent = PlanningSelection.model_validate(raw)
    except ValidationError as exc:
        raise PlanningValidationError("Invalid selection schema", code="invalid_plan_schema") from exc
    duration_override = checkpoint.get("duration_minutes")
    split = checkpoint.get("allow_split", False)
    initial = _empty_free(profile.timezone, duration_override or 0, split)
    known = task_handles(tasks)
    refs = intent.task_refs
    if len(set(refs)) != len(refs) or any(ref not in known for ref in refs):
        raise PlanningValidationError("Unknown or repeated task handle", code="unknown_task_reference")
    sources = {item["source_ref"] for item in checkpoint.get("memory_search", {}).get("matches", [])
               if isinstance(item, dict) and isinstance(item.get("source_ref"), str)}
    if any(ref not in sources for ref in intent.evidence_refs):
        raise PlanningValidationError("Invented evidence reference", code="unknown_memory_reference")
    if intent.status == "needs_clarification":
        if refs or not intent.questions or any(not question.strip() for question in intent.questions):
            raise PlanningValidationError("Invalid clarification", code="invalid_plan_schema")
        result, free = _unavailable("needs_clarification", "request_ambiguous",
                                    intent.questions[0], initial)
        result["questions"] = intent.questions
        return result, free
    constraints = explicit_constraints(command or "")
    if "question" in constraints:
        return _unavailable("needs_clarification", "request_ambiguous", constraints["question"], initial)
    if constraints:
        intent = intent.model_copy(update=constraints)
    if intent.questions:
        raise PlanningValidationError("Selected request has open questions", code="invalid_plan_schema")
    if not refs:
        return _unavailable("needs_clarification", "task_required",
                            "Choose an active task to schedule.", initial)
    selected = [known[ref] for ref in refs]
    stated_duration = intent.duration_minutes
    if duration_override is not None and stated_duration is not None and duration_override != stated_duration:
        return _unavailable("needs_clarification", "duration_conflict",
            "The duration in your request differs from the duration field. Make them match or clear the field.", initial)
    duration = duration_override if duration_override is not None else stated_duration
    estimates = [task.get("estimate_minutes") for task in selected]
    if duration is None:
        if any(type(value) is not int or value < 15 for value in estimates):
            return _unavailable("needs_clarification", "duration_required",
                "Specify a duration of 15 to 480 minutes or save an estimate for the selected task.", initial)
        duration = sum(estimates)
    if type(duration) is not int or not 15 <= duration <= 480:
        return _unavailable("needs_clarification", "duration_out_of_range",
                            "Choose a total work duration between 15 and 480 minutes.", initial)
    initial = _empty_free(profile.timezone, duration, split)
    if len(refs) > 1:
        if any(type(value) is not int or not 15 <= value <= 480 for value in estimates):
            return _unavailable("needs_clarification", "task_estimates_required",
                "Save an estimate for each selected task so the total work time can be divided.", initial)
        if sum(estimates) != duration:
            return _unavailable("needs_clarification", "task_duration_conflict",
                "The total duration must match the selected task estimates, or schedule one task at a time.", initial)
        allocations = dict(zip(refs, estimates))
    else:
        allocations = {refs[0]: duration}
    snapshot = checkpoint.get("calendar")
    if not isinstance(snapshot, dict) or snapshot.get("complete") is not True:
        raise PlanningValidationError("Incomplete Calendar snapshot", code="calendar_snapshot_incomplete")
    if profile.timezone != snapshot.get("timezone") or profile.timezone != checkpoint.get("timezone"):
        raise PlanningValidationError("Scheduling timezone changed", code="profile_changed")
    reference = datetime.fromisoformat(checkpoint["window_start"])
    current = now or datetime.now(timezone.utc)
    start = datetime.fromisoformat(snapshot["start"])
    end = datetime.fromisoformat(snapshot["end"])
    fetched = datetime.fromisoformat(snapshot["fetched_at"])
    if any(value.utcoffset() is None for value in (reference, current, start, end, fetched)):
        raise PlanningValidationError("Invalid Calendar clock", code="calendar_snapshot_incomplete")
    zone = ZoneInfo(profile.timezone)
    reference_day = reference.astimezone(zone).date()
    if intent.day == "date":
        try:
            target = date.fromisoformat(intent.date or "")
            if target.isoformat() != intent.date:
                raise ValueError()
        except ValueError as exc:
            raise PlanningValidationError("Invalid requested day", code="invalid_time_constraint") from exc
    else:
        if intent.date is not None:
            raise PlanningValidationError("Unexpected scheduling date", code="invalid_time_constraint")
        target = reference_day + timedelta(days=int(intent.day == "tomorrow")) if intent.day != "any" else None
    clock_start = _clock(intent.start_time, 0)
    clock_end = _clock(intent.end_time, 1440)
    if clock_end <= clock_start:
        return _unavailable("needs_clarification", "invalid_time_constraint",
                            "Choose an end time after the start time on the same day.", initial)
    if target is None and (intent.start_time is not None or intent.end_time is not None):
        return _unavailable("needs_clarification", "scheduling_day_required",
                            "Specify which day should use the requested clock times.", initial)
    if target is not None:
        if target < current.astimezone(zone).date():
            return _unavailable("needs_clarification", "scheduling_day_passed",
                                "The requested day has passed. Choose today or a future day.", initial)
        day_start = _local_boundary(target, clock_start, zone)
        day_end = _local_boundary(target, clock_end, zone)
        if day_start >= end:
            return _unavailable("needs_clarification", "scheduling_window_exceeded",
                                "Choose a day within the next seven days.", initial)
        start, end = max(start, day_start), min(end, day_end)
    # Give Calendar writes time to complete and round away seconds/microseconds.
    earliest = current.astimezone(timezone.utc) + timedelta(minutes=START_BUFFER_MINUTES)
    if earliest.second or earliest.microsecond:
        earliest = earliest.replace(second=0, microsecond=0) + timedelta(minutes=1)
    start = max(start, earliest)
    deadlines = {}
    for ref in refs:
        task = known[ref]
        if task.get("due_kind") == "date":
            return _unavailable("needs_clarification", "timed_deadline_required",
                "Set an exact deadline time for this task before scheduling it.", initial, refs)
        deadline = None
        if task.get("due_at"):
            try:
                deadline = datetime.fromisoformat(task["due_at"])
                if deadline.utcoffset() is None:
                    raise ValueError()
            except (TypeError, ValueError) as exc:
                raise PlanningValidationError("Invalid task deadline", code="task_deadline_invalid") from exc
            if deadline <= current:
                return _unavailable("needs_clarification", "deadline_passed",
                    "The task deadline has passed. Update it before scheduling this task.", initial, refs)
        deadlines[ref] = deadline
    events = [{"id": item["id"], "summary": "Busy", "start": {"dateTime": item["start"]},
               "end": {"dateTime": item["end"]}} for item in snapshot["events"]]
    combined_slots, blocks = [], []
    base_window = CalendarWindow(start, end, fetched, "primary", profile.timezone, tuple(events), complete=True)
    inventory = calculate_free_time(base_window, timezone_name=profile.timezone,
        working_hours=profile.working_hours, duration_minutes=duration, allow_split=split,
        minimum_block_minutes=15)
    base_available, free_intervals = inventory.available_minutes, inventory.free_intervals
    for ref in sorted(refs, key=lambda key: deadlines[key] or end):
        window = CalendarWindow(start, end, fetched, "primary", profile.timezone, tuple(events), complete=True)
        free = calculate_free_time(window, timezone_name=profile.timezone,
            working_hours=profile.working_hours, duration_minutes=allocations[ref], allow_split=split,
            deadline=deadlines[ref], minimum_block_minutes=15)
        if len(refs) == 1:
            base_available, free_intervals = free.available_minutes, free.free_intervals
        if free.shortfall_minutes:
            initial = initial.model_copy(update={"available_minutes": free.available_minutes,
                                                 "free_intervals": free.free_intervals})
            return _unavailable("insufficient_time", "insufficient_time",
                "There is not enough work time in the requested window. Check working hours and the task deadline, "
                "choose another day or a shorter duration, or allow multiple work blocks.", initial, refs)
        for slot in free.slots:
            slot_ref = f"slot-{len(combined_slots) + 1}"
            combined_slots.append(slot)
            blocks.append({"slot_ref": slot_ref, "task_ref": ref, "title": known[ref]["title"],
                "reason": "Available work time from the saved Calendar snapshot.",
                "evidence_refs": intent.evidence_refs})
            events.append({"id": slot_ref, "summary": "Busy", "start": {"dateTime": slot.start.isoformat()},
                           "end": {"dateTime": slot.end.isoformat()}})
    if len(blocks) > 16:
        return _unavailable("needs_clarification", "too_many_blocks",
            "This plan needs too many small blocks. Choose fewer tasks or a shorter duration.", initial, refs)
    free = FreeTimeResult(timezone=profile.timezone, requested_minutes=duration,
        available_minutes=base_available, allocated_minutes=duration, shortfall_minutes=0,
        allow_split=split, slots=combined_slots, free_intervals=free_intervals)
    assumptions = []
    if stated_duration is None and duration_override is None:
        assumptions.append("Work duration uses the saved task estimates.")
    elif len(refs) == 1 and estimates[0] != duration:
        assumptions.append("Work duration uses your request rather than the saved task estimate.")
    raw_plan = {"schema_version": "1", "status": "proposed", "task_refs": refs, "blocks": blocks,
        "requested_minutes": duration, "scheduled_minutes": duration, "shortfall_minutes": 0,
        "assumptions": assumptions, "questions": [], "summary": "Work time is available."}
    return validate_planning_response(raw_plan, tasks, free, sources), free
