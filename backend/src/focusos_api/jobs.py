"""Durable jobs with short-lived encrypted sessions and one bounded step per claim."""
import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, model_validator
from focusos_api.database import DatabaseUnavailable, InvalidSession, scoped_client, service_client
from focusos_api.token_crypto import TokenCipher, TokenCipherError

logger = logging.getLogger(__name__)
JOB_SELECT = "id,kind,subject_id,status,result,safe_error,steps,failures,available_at,expires_at,created_at,updated_at"
TERMINAL = {"succeeded", "failed", "cancelled", "expired"}

class JobNotFound(Exception): pass
class JobConflict(Exception): pass
class JobLimit(Exception): pass
class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    kind: Literal["planning", "gmail", "source", "embedding"]
    subject_id: UUID | None = None
    @model_validator(mode="after")
    def valid_subject(self):
        if (self.kind == "gmail") != (self.subject_id is None):
            raise ValueError("Only Gmail jobs have no subject")
        return self

class JobRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    kind: str
    subject_id: UUID | None
    status: str
    result: dict | None = None
    safe_error: str | None = None
    steps: int
    failures: int
    available_at: datetime
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

@dataclass(frozen=True)
class Step:
    status: str = "queued"
    checkpoint: dict = field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
    delay: int = 0
    failure: bool = False

class RetryStep(Exception):
    def __init__(self, code="provider_unavailable", delay=30):
        self.code, self.delay = code, delay
        super().__init__(code)


def _service_rpc(name, args):
    with service_client() as client:
        return client.rpc(name, args).execute().data


def session_expiry(token: str, now: datetime | None = None) -> datetime:
    # Auth is verified separately. Unverified exp can only shorten the lifetime, never grant access.
    current = now or datetime.now(timezone.utc)
    try:
        raw = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        exp = payload["exp"]
        if type(exp) not in (int, float): raise ValueError()
        expiry = min(datetime.fromtimestamp(exp, timezone.utc), current + timedelta(minutes=15))
        if expiry < current + timedelta(seconds=60): raise ValueError()
        return expiry
    except (KeyError, ValueError, IndexError, TypeError, OverflowError) as exc:
        raise InvalidSession("Sign in again before starting a background job") from exc


def enqueue_job(token: str, request: JobInput) -> JobRecord:
    with scoped_client(token) as (owner, _):
        pass
    expiry = session_expiry(token)
    job_id = uuid4()
    cipher = TokenCipher.from_environment()
    encrypted = cipher.encrypt(job_id, "job", token)
    try:
        row = _service_rpc("focusos_enqueue_job", {
            "p_id": str(job_id), "p_owner": owner, "p_request_key": str(request.request_key),
            "p_kind": request.kind, "p_subject_id": str(request.subject_id) if request.subject_id else None,
            "p_ciphertext": base64.b64encode(encrypted.ciphertext).decode("ascii"),
            "p_key_version": encrypted.key_version, "p_expires_at": expiry.isoformat(),
        })
    except DatabaseUnavailable as exc:
        code = getattr(exc.__cause__, "code", None)
        if code == "23505": raise JobConflict() from exc
        if code == "54000": raise JobLimit() from exc
        raise
    return JobRecord.model_validate(row)


def _read_job(row: dict, now: datetime) -> JobRecord:
    """Expose expired work consistently without extending its stored credentials."""
    job = JobRecord.model_validate(row)
    if job.status not in TERMINAL and job.expires_at <= now:
        return job.model_copy(update={"status": "expired", "safe_error": "session_expired"})
    return job


def get_job(token: str, job_id: UUID) -> JobRecord:
    with scoped_client(token) as (owner, client):
        rows = client.table("work_jobs").select(JOB_SELECT).eq("user_id", owner).eq("id", str(job_id)).limit(1).execute().data
    if not isinstance(rows, list) or len(rows) != 1: raise JobNotFound()
    return _read_job(rows[0], datetime.now(timezone.utc))


def list_jobs(token: str) -> list[JobRecord]:
    with scoped_client(token) as (owner, client):
        rows = client.table("work_jobs").select(JOB_SELECT).eq("user_id", owner).order("created_at", desc=True).limit(50).execute().data
    now = datetime.now(timezone.utc)
    return [_read_job(row, now) for row in rows]


def cancel_job(token: str, job_id: UUID) -> bool:
    with scoped_client(token) as (_, client):
        return client.rpc("focusos_cancel_job", {"p_id": str(job_id)}).execute().data is True


def _capture_step(token: str, job: dict, response) -> Step:
    extraction = response.extraction
    if extraction.status == "processing": raise RetryStep("processing_busy", 15)
    if extraction.status != "ready":
        error = extraction.safe_error
        previous = job.get("result") or {}
        if error in ("invalid_output", "refused", "incomplete", "oversize_response", "provider_unconfigured", "source_unavailable"):
            # The extractor already attempted one bounded repair. Repeating invalid
            # output five times spends quota without giving the user a useful result.
            return Step("failed", job.get("checkpoint", {}),
                        {**previous, "source_id": str(extraction.source_id)}, "extraction_" + error)
        if error in ("timeout", "provider_error"):
            raise RetryStep("extraction_" + error, 60)
        raise RetryStep("extraction_unavailable", 60)
    capture = response.capture or {}
    if capture.get("task_failures") or capture.get("memory_failures"):
        raise RetryStep("capture_incomplete", 30)
    checkpoint = {**job.get("checkpoint", {}), "memory_ids": capture.get("memory_ids", []), "phase": "embedding"}
    previous = job.get("result") or {}
    result = {**previous, "tasks_saved": previous.get("tasks_saved", 0) + capture.get("tasks_saved", 0), "memories_saved": previous.get("memories_saved", 0) + capture.get("memories_saved", 0), "source_id": str(extraction.source_id)}
    return Step(checkpoint=checkpoint, result=result)


def _process_capture(token: str, job: dict, source_id: UUID) -> Step:
    from focusos_api.auto_capture import process_and_capture
    from focusos_api.extractions import ExtractionRateLimited
    try:
        response = process_and_capture(token, source_id)
    except ExtractionRateLimited as exc:
        # The database enforces five extraction runs per ten-minute window.
        raise RetryStep("extraction_rate_limited", 600) from exc
    return _capture_step(token, job, response)


def _step(token: str, job: dict) -> Step:
    from focusos_api.agent_continuation import load_command_run, continue_staged_run
    from focusos_api.automatic_calendar import schedule_automatic_block, AutomaticCalendarUnavailable
    from focusos_api.approval_proposal import ProposalRejected
    from focusos_api.gmail_selection import GmailSelectionMissing, GmailSelectionReconnect, GmailSelectionUnavailable
    from focusos_api.gmail_sync import run_one_sync_page
    from focusos_api.gmail_processing import next_gmail_source
    from focusos_api.memory_embeddings import embed_memory
    checkpoint = dict(job.get("checkpoint") or {})
    kind = job["kind"]
    subject = UUID(job["subject_id"]) if job.get("subject_id") else None
    phase = checkpoint.get("phase")
    if phase == "embedding":
        ids = checkpoint.get("memory_ids", [])
        index = checkpoint.get("memory_index", 0)
        if index < len(ids):
            state = embed_memory(token, UUID(ids[index])).state
            if state == "busy": raise RetryStep("embedding_busy", 10)
            if state == "failed": raise RetryStep("embedding_unavailable", 60)
            if state not in ("ready", "reused", "unavailable"): raise RetryStep("embedding_unavailable", 60)
            return Step(checkpoint={**checkpoint, "memory_index": index + 1}, result=job.get("result"))
        if kind == "gmail":
            return Step(checkpoint={**checkpoint, "phase": "process", "memory_ids": [], "memory_index": 0}, result=job.get("result"))
        return Step("succeeded", checkpoint, job.get("result"))
    if kind == "planning":
        run = load_command_run(token, subject)
        if run.checkpoint.get("entrypoint") == "unified":
            from focusos_api.unified_commands import advance_work
            advance = advance_work(token, job, run)
            if advance is not None: return advance
        previous = job.get("result") or {}
        if run.status in ("waiting", "running", "pending"):
            run = continue_staged_run(token, subject)
            if run.status in ("waiting", "running", "pending"):
                return Step(checkpoint=checkpoint, result={**previous, "stage": run.stage}, delay=2 if run.status == "running" else 0)
        if run.status != "succeeded" or not run.result or run.result.get("status") != "proposed":
            return Step("failed", checkpoint, {**previous, "run_id": str(subject), "stage": run.stage, "message": (run.result or {}).get("summary", "Could not find a suitable Calendar slot. Try another time window.")}, "planning_not_scheduled")
        if not run.checkpoint.get("auto_calendar"):
            return Step("succeeded", checkpoint, {"run_id": str(subject), "stage": "done"})
        index = checkpoint.get("block_index", 0)
        if index >= len(run.result["blocks"]): return Step("succeeded", checkpoint, {**previous, "run_id": str(subject), "blocks_scheduled": index})
        try:
            action = schedule_automatic_block(token, subject, index)
        except (ProposalRejected, AutomaticCalendarUnavailable) as exc:
            messages = {"calendar_write_required": "Enable Calendar event writes in Google connection, then submit again.",
                        "profile_required": "Save your timezone and working hours in Preferences.",
                        "task_changed": "This task was changed or completed. Submit a new request for an active task.",
                        "plan_expired": "This request expired. Check Calendar before submitting a fresh request.",
                        "slot_expired": "The proposed slot is no longer available. Try another time window.",
                        "plan_stale": "Calendar availability changed. Submit a new request."}
            return Step("failed", checkpoint, {**previous, "message": messages.get(exc.code, "Could not create this Calendar event. Check your connection and try again.")}, exc.code)
        if action.status == "succeeded":
            return Step(checkpoint={**checkpoint, "block_index": index + 1}, result={**previous, "run_id": str(subject), "blocks_scheduled": index + 1, "blocks": [*(previous.get("blocks") or []), {"title": action.payload.title, "start": action.payload.start.isoformat(), "end": action.payload.end.isoformat(), "timezone": action.payload.timezone, "link": action.provider_link}]})
        if action.status in ("executing", "approved", "unknown"):
            raise RetryStep("calendar_pending", 15)
        return Step("failed", checkpoint, {**previous, "run_id": str(subject), "blocks_scheduled": index, "message": "Could not create the Calendar event. Check your Google connection and try again."}, "calendar_not_scheduled")
    if kind == "embedding":
        state = embed_memory(token, subject).state
        if state in ("busy", "failed"): raise RetryStep("embedding_unavailable", 30)
        return Step("succeeded" if state in ("ready", "reused") else "failed", checkpoint, {"embedding_state": state})
    if kind == "source": return _process_capture(token, job, subject)
    if kind == "gmail":
        if phase in (None, "sync"):
            try:
                sync = run_one_sync_page(token)
            except GmailSelectionMissing:
                return Step("failed", checkpoint, {**(job.get("result") or {}), "message": "No eligible email found. Create the FocusOS label in Gmail and apply it to messages you want to organize."}, "gmail_label_missing")
            except GmailSelectionReconnect:
                return Step("failed", checkpoint, {**(job.get("result") or {}), "message": "Reconnect Google to sync selected email."}, "gmail_reconnect_required")
            except GmailSelectionUnavailable as exc:
                raise RetryStep("gmail_backoff", exc.retry_after or 60) from exc
            if sync.state in ("busy", "backoff", "retry_wait"): raise RetryStep("gmail_backoff", 60)
            return Step(checkpoint={"phase": "process" if sync.state == "complete" else "sync"}, result={**(job.get("result") or {}), "imported": (job.get("result") or {}).get("imported", 0) + sync.imported})
        if phase == "capture":
            return _process_capture(token, job, UUID(checkpoint["source_id"]))
        source_id = next_gmail_source(token)
        if source_id is None: return Step("succeeded", checkpoint, job.get("result"))
        # Persist the selected source before extraction: a retry must not skip a ready
        # extraction whose task/memory capture failed or whose worker crashed.
        return Step(checkpoint={"phase": "capture", "source_id": str(source_id)}, result=job.get("result"))
    raise ValueError("Unsupported job kind")


def work_one(job_id: UUID | None = None, owner: str | None = None) -> dict:
    claimed = _service_rpc("focusos_claim_job", {"p_id": str(job_id) if job_id else None, "p_owner": owner})
    if claimed is None: return {"state": "idle"}
    # Ciphertext binds to this exact job ID. Reverify Auth and owner on every claim.
    step = Step("failed", claimed.get("checkpoint", {}), result=claimed.get("result"), error="worker_error")
    try:
        token = TokenCipher.from_environment().decrypt(UUID(claimed["id"]), "job", base64.b64decode(claimed["ciphertext"], validate=True), claimed["key_version"])
        with scoped_client(token) as (verified_owner, _):
            if verified_owner != claimed["user_id"]: raise InvalidSession()
        step = _step(token, claimed)
    except InvalidSession:
        step = Step("expired", claimed.get("checkpoint", {}), error="session_expired")
    except RetryStep as exc:
        step = Step(checkpoint=claimed.get("checkpoint", {}), result=claimed.get("result"), error=exc.code,
                    delay=min(900, max(exc.delay, 15 * 2 ** min(claimed.get("failures", 0), 5))), failure=True)
    except DatabaseUnavailable:
        step = Step(checkpoint=claimed.get("checkpoint", {}), result=claimed.get("result"), error="database_unavailable", delay=30, failure=True)
    except Exception as exc:
        # Log class only; provider bodies/session tokens/task text must not enter logs.
        logger.warning("Job step failed: kind=%s error=%s", claimed.get("kind"), type(exc).__name__)
    saved = _service_rpc("focusos_finish_job", {"p_id": claimed["id"], "p_lease": claimed["lease_token"],
        "p_status": step.status, "p_checkpoint": step.checkpoint, "p_result": step.result,
        "p_error": step.error, "p_delay": step.delay, "p_failure": step.failure})
    return {"state": "advanced" if saved else "lease_lost", "job_id": claimed["id"]}


def work_owned(token: str, job_id: UUID) -> JobRecord:
    get_job(token, job_id)
    with scoped_client(token) as (owner, _): pass
    work_one(job_id, owner)
    return get_job(token, job_id)
