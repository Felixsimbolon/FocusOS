"""Review-time, owner-scoped confirmation of one candidate task."""
from datetime import timezone
import hashlib
import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.extraction_contracts import ExtractionEnvelope, validate_grounding
from focusos_api.extractions import ExtractionRecord, SELECT
from focusos_api.sources import get_source
from focusos_api.tasks import TaskCreate, TaskCreateEnvelope, TaskRecord


class ConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_ref: str = Field(min_length=1, max_length=80)
    task: TaskCreate


class ConfirmNotFound(Exception):
    pass


class ConfirmStale(Exception):
    pass


class ConfirmConflict(Exception):
    pass


class ConfirmProjectNotFound(Exception):
    pass


def confirm_candidate(access_token: str, extraction_id: UUID, request: ConfirmInput) -> TaskCreateEnvelope:
    with scoped_client(access_token) as (owner, client):
        rows = (client.table("extraction_results").select(SELECT)
                .eq("user_id", owner).eq("id", str(extraction_id)).eq("status", "ready")
                .limit(1).execute().data)
    if not isinstance(rows, list) or not rows:
        raise ConfirmNotFound()
    extraction = ExtractionRecord.model_validate(rows[0])
    source = get_source(access_token, extraction.source_id)
    if source is None or source.normalized_body is None or source.body_hash != extraction.content_hash:
        raise ConfirmStale()
    if extraction.validated_payload is None:
        raise ConfirmStale()
    try:
        payload = ExtractionEnvelope.model_validate(extraction.validated_payload)
        candidate = next(task for task in payload.tasks if task.local_ref == request.local_ref)
        reference = candidate.deadline.reference_time
        if reference.astimezone(timezone.utc) != source.received_at.astimezone(timezone.utc):
            raise ValueError("Source reference time mismatch")
        validate_grounding(payload, source.source_ref, source.normalized_body, reference)
    except (ValueError, StopIteration) as exc:
        raise ConfirmStale() from exc
    review_json = request.task.model_dump(mode="json")
    canonical = json.dumps({"extraction_id":str(extraction_id),"local_ref":request.local_ref,
                            "content_hash":extraction.content_hash,"task":review_json},
                           sort_keys=True,separators=(",",":"),ensure_ascii=False)
    review_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    with scoped_client(access_token) as (_, client):
        outcome = client.rpc("focusos_confirm_extraction_task", {
            "p_extraction_id": str(extraction_id), "p_local_ref": request.local_ref,
            "p_review_hash": review_hash, "p_title": request.task.title,
            "p_description": request.task.description, "p_priority": request.task.priority,
            "p_due_kind": request.task.due_kind,
            "p_due_date": request.task.due_date.isoformat() if request.task.due_date else None,
            "p_due_at": request.task.due_at.isoformat() if request.task.due_at else None,
            "p_due_timezone": request.task.due_timezone,
            "p_estimate_minutes": request.task.estimate_minutes,
            "p_project_id": str(request.task.project_id) if request.task.project_id else None,
            "p_evidence": [item.model_dump(mode="json") for item in candidate.evidence],
            "p_confidence": candidate.confidence,
        }).execute().data
    if not isinstance(outcome, dict):
        raise DatabaseUnavailable("Unexpected confirmation response")
    if outcome.get("outcome") == "not_found" or outcome.get("outcome") == "candidate_not_found":
        raise ConfirmNotFound()
    if outcome.get("outcome") == "stale":
        raise ConfirmStale()
    if outcome.get("outcome") == "conflict":
        raise ConfirmConflict()
    if outcome.get("outcome") == "project_not_found":
        raise ConfirmProjectNotFound()
    if outcome.get("outcome") != "confirmed" or not isinstance(outcome.get("task"), dict):
        raise DatabaseUnavailable("Unexpected confirmation response")
    return TaskCreateEnvelope(task=TaskRecord.model_validate(outcome["task"]),
                              replayed=outcome.get("replayed") is True)
