"""Automatically persist grounded tasks and facts from one extraction."""
import logging
from datetime import date, datetime
from uuid import UUID, uuid5

from focusos_api.confirmation import (ConfirmInput, ConfirmConflict, ConfirmNotFound, ConfirmStale, confirm_candidate)
from focusos_api.extraction_contracts import ExtractionEnvelope, TaskExtraction
from focusos_api.database import DatabaseUnavailable
from focusos_api.extractions import ExtractionEnvelopeResponse, process_extraction
from focusos_api.memories import MemoryEvidenceInvalid, MemoryInput, confirm_memory
from focusos_api.tasks import TaskCreate

logger = logging.getLogger(__name__)
MEMORY_NAMESPACE = UUID("be9b03cb-2919-4827-8e57-936e45fb2980")


def task_input(candidate: TaskExtraction) -> TaskCreate:
    deadline = candidate.deadline
    values = {
        "title": candidate.title,
        "description": candidate.description or None,
        "priority": "normal" if candidate.priority_hint == "unspecified" else candidate.priority_hint,
        "estimate_minutes": candidate.estimate_minutes,
    }
    if deadline.kind == "date":
        values.update(due_kind="date", due_date=date.fromisoformat(deadline.value))
    elif deadline.kind == "datetime":
        values.update(due_kind="datetime", due_at=datetime.fromisoformat(deadline.value),
                      due_timezone=deadline.timezone)
    return TaskCreate(**values)


def capture_ready(access_token: str, response: ExtractionEnvelopeResponse) -> dict:
    record = response.extraction
    result = {"tasks_saved": 0, "memories_saved": 0, "task_failures": 0,
              "memory_failures": 0, "memory_ids": []}
    if record.status != "ready" or record.validated_payload is None:
        return result
    payload = ExtractionEnvelope.model_validate(record.validated_payload)
    for candidate in payload.tasks:
        try:
            confirm_candidate(access_token, record.id,
                              ConfirmInput(local_ref=candidate.local_ref, task=task_input(candidate)))
            result["tasks_saved"] += 1
        except (DatabaseUnavailable, ConfirmConflict, ConfirmNotFound, ConfirmStale) as error:
            logger.warning("Automatic task capture failed: extraction=%s error=%s", record.id, type(error).__name__)
            result["task_failures"] += 1
    for fact in payload.facts:
        quote = fact.evidence[0].quote
        request_key = uuid5(MEMORY_NAMESPACE, ":".join(
            (str(record.source_id), record.content_hash, fact.kind, fact.text, quote)))
        try:
            saved = confirm_memory(access_token, MemoryInput(
                request_key=request_key, source_id=record.source_id,
                text=fact.text, evidence_quote=quote))
            result["memories_saved"] += 1
            result["memory_ids"].append(str(saved.id))
        except (DatabaseUnavailable, MemoryEvidenceInvalid) as error:
            logger.warning("Automatic memory capture failed: extraction=%s error=%s", record.id, type(error).__name__)
            result["memory_failures"] += 1
    return result


def process_and_capture(access_token: str, source_id: UUID) -> ExtractionEnvelopeResponse:
    response = process_extraction(access_token, source_id)
    capture = capture_ready(access_token, response)
    return response.model_copy(update={"capture": capture})
