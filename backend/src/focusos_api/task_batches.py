"""Recognize explicit task lists and require a distinct grounded task per item."""
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from focusos_api.extraction_contracts import ExtractionEnvelope

MAX_BATCH_TASKS = 10
_ITEM = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)]|\(\d+\))\s+(?:\[[ xX]\]\s+)?\S")
_TASK = re.compile(r"\b(?:tasks?|tugas|pekerjaan|to[- ]?do)\b", re.IGNORECASE)
_CREATE = re.compile(r"\b(?:buat(?:kan)?|bikin(?:kan)?|tambahkan|simpan|create|add|save)\b", re.IGNORECASE)


class TaskBatchIncomplete(ValueError):
    """The model omitted or merged an item in an explicit task list."""


def explicit_task_items(body: str) -> list[str]:
    """Only task-headed lists; ordinary email bullets/facts are not task counts.

    Keep original source substrings, including indented continuation lines, so
    evidence can be compared without translating or rewriting the user's input.
    """
    lines = body.splitlines(keepends=True)
    items = []
    index = 0
    while index < len(lines):
        heading = lines[index].strip().strip("*# ")
        is_heading = bool(_TASK.search(heading)) and (
            (bool(_CREATE.search(heading)) and (heading.endswith(":") or re.search(r"\b(?:berikut|following|these)\b", heading, re.IGNORECASE)))
            or bool(re.fullmatch(r"(?:tasks?|tugas|pekerjaan|to[- ]?do)(?:\s+(?:berikut|list))?\s*:", heading, re.IGNORECASE)))
        index += 1
        if not is_heading:
            continue
        pending = []
        while index < len(lines):
            line = lines[index]
            if _ITEM.match(line):
                if pending:
                    items.append("".join(pending).rstrip())
                pending = [line]
            elif not line.strip():
                if pending:
                    pending.append(line)
            elif pending and line[:1].isspace():
                pending.append(line)
            else:
                break
            index += 1
        if pending:
            items.append("".join(pending).rstrip())
    return items


def validate_task_batch(result: "ExtractionEnvelope", items: list[str]) -> None:
    """Match each requested list item to a different extracted task by evidence."""
    if len(items) < 2:
        return
    if len(items) > MAX_BATCH_TASKS or len(result.tasks) < len(items):
        raise TaskBatchIncomplete("Task batch is incomplete")
    def belongs_to_item(task, item):
        if not any(evidence.quote in item for evidence in task.evidence):
            return False
        # A deadline quoted from a different item cannot be attached to this one.
        # Shared deadline wording outside the list remains available to all items.
        raw = task.deadline.raw_text
        return not raw or raw in item or not any(raw in other for other in items)

    matches = [[index for index, task in enumerate(result.tasks)
                if belongs_to_item(task, item)] for item in items]
    assigned = {}

    def assign(item_index: int, seen: set[int]) -> bool:
        for task_index in matches[item_index]:
            if task_index in seen:
                continue
            seen.add(task_index)
            if task_index not in assigned or assign(assigned[task_index], seen):
                assigned[task_index] = item_index
                return True
        return False

    if any(not assign(index, set()) for index in range(len(items))):
        raise TaskBatchIncomplete("Task batch is incomplete")
