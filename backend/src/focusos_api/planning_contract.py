"""Strict plan envelope; only server-owned task and slot handles become blocks."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from focusos_api.calendar_free_time import FreeTimeResult


class PlanningValidationError(ValueError):
    pass


class CandidateBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot_ref: str
    task_ref: str
    title: str = Field(max_length=120)
    reason: str = Field(max_length=300)
    evidence_refs: list[str] = Field(max_length=5)


class PlanningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"]
    status: Literal["proposed", "needs_clarification", "insufficient_time"]
    task_refs: list[str]
    blocks: list[CandidateBlock]
    requested_minutes: int
    scheduled_minutes: int
    shortfall_minutes: int
    assumptions: list[str]
    questions: list[str]
    summary: str = Field(max_length=500)


def task_handles(tasks: list[dict]) -> dict[str, dict]:
    return {f"task-{i+1}": task for i, task in enumerate(tasks)}


def slot_handles(free: FreeTimeResult) -> dict[str, object]:
    return {f"slot-{i+1}": slot for i, slot in enumerate(free.slots)}


def validate_planning_response(raw: object, tasks: list[dict], free: FreeTimeResult,
                               source_refs: set[str] | None = None) -> dict:
    try:
        candidate = PlanningResponse.model_validate(raw)
    except Exception as exc:
        raise PlanningValidationError("Invalid plan schema") from exc
    known_tasks, known_slots = task_handles(tasks), slot_handles(free)
    known_sources = source_refs or set()
    if candidate.requested_minutes != free.requested_minutes:
        raise PlanningValidationError("Requested duration changed")
    if len(candidate.blocks) > 16 or len(candidate.task_refs) > 20 or len(candidate.assumptions) > 8 or len(candidate.questions) > 5:
        raise PlanningValidationError("Plan exceeds bounds")
    if len(set(candidate.task_refs)) != len(candidate.task_refs) or any(ref not in known_tasks for ref in candidate.task_refs):
        raise PlanningValidationError("Unknown or repeated task handle")
    used: set[str] = set()
    resolved: list[dict] = []
    for block in candidate.blocks:
        if block.task_ref not in candidate.task_refs or block.slot_ref not in known_slots or block.slot_ref in used:
            raise PlanningValidationError("Unknown or repeated block handle")
        if not block.title.strip() or not block.reason.strip():
            raise PlanningValidationError("Empty block explanation")
        if any(ref not in known_sources for ref in block.evidence_refs):
            raise PlanningValidationError("Invented evidence reference")
        used.add(block.slot_ref)
        task, slot = known_tasks[block.task_ref], known_slots[block.slot_ref]
        if slot.start.tzinfo is None or slot.end.tzinfo is None or slot.end <= slot.start:
            raise PlanningValidationError("Invalid slot interval")
        if task.get("due_kind") == "date" and task.get("due_date"):
            raise PlanningValidationError("Date-only deadline needs clarification")
        if task.get("due_at"):
            try:
                due_at = datetime.fromisoformat(task["due_at"])
            except ValueError as exc:
                raise PlanningValidationError("Invalid deadline") from exc
            if due_at.tzinfo is None or slot.end.astimezone(timezone.utc) > due_at.astimezone(timezone.utc):
                raise PlanningValidationError("Block exceeds deadline")
        resolved.append({"slot_ref": block.slot_ref, "task_ref": block.task_ref,
                         "task_id": task["id"], "start": slot.start.isoformat(),
                         "end": slot.end.isoformat(), "title": block.title,
                         "reason": block.reason, "evidence_refs": block.evidence_refs})
    ordered = sorted(resolved, key=lambda block: block["start"])
    if any(datetime.fromisoformat(a["end"]) > datetime.fromisoformat(b["start"])
           for a, b in zip(ordered, ordered[1:])):
        raise PlanningValidationError("Blocks overlap")
    total = sum(int((datetime.fromisoformat(b["end"]) - datetime.fromisoformat(b["start"])).total_seconds() // 60)
                for b in resolved)
    if candidate.scheduled_minutes != total or candidate.shortfall_minutes != free.requested_minutes-total:
        raise PlanningValidationError("Plan totals do not match slots")
    if candidate.status == "proposed":
        if not resolved or total != free.requested_minutes or candidate.questions:
            raise PlanningValidationError("Proposal needs complete slots and no open questions")
    elif candidate.status == "needs_clarification":
        if resolved or not candidate.questions or total != 0:
            raise PlanningValidationError("Clarification cannot contain proposed blocks")
    elif candidate.status == "insufficient_time":
        if free.shortfall_minutes <= 0 or resolved or total != 0:
            raise PlanningValidationError("Shortfall must reflect calculated availability")
    if not candidate.summary.strip() or any(not item.strip() for item in candidate.assumptions + candidate.questions):
        raise PlanningValidationError("Empty explanation")
    result = candidate.model_dump()
    result["blocks"] = resolved
    result["scheduled_minutes"] = total
    result["shortfall_minutes"] = free.requested_minutes-total
    result["actionable"] = False
    return result
