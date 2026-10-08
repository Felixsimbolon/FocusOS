"""Proposal-only Calendar tool. The database derives fields from an owned saved plan."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from focusos_api.agent_tasks import _rpc
from focusos_api.approval_payload import CalendarAction
from focusos_api.database import DatabaseUnavailable


class ProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_index: int = Field(strict=True, ge=0, le=15)


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    run_id: UUID
    block_index: int
    task_id: UUID | None
    connection_id: UUID
    calendar_id: str
    event_id: str
    payload: CalendarAction
    payload_hash: str
    status: str
    authorization_mode: str = "manual"
    status_version: int
    expires_at: datetime
    lease_until: datetime | None = None
    provider_event_id: str | None = None
    provider_link: str | None = None
    safe_code: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
    updated_at: datetime


class ProposalRejected(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


PROPOSAL_REASONS = {
    "Calendar grant unavailable": "calendar_write_required",
    "Scheduling profile unavailable": "profile_required",
    "No active proposal": "plan_expired",
    "Run proposal unavailable": "plan_expired",
    "Task changed": "task_changed",
    "Timed deadline required": "timed_deadline_required",
    "Invalid proposed interval": "slot_expired",
    "Invalid approval time": "slot_expired",
    "Block is not a saved free slot": "plan_stale",
    "Invalid approval identity": "plan_stale",
    "Unknown proposal block": "invalid_block",
    "Invalid block": "invalid_block",
}


def propose_calendar_event(access_token: str, run_id: UUID, request: ProposalInput) -> ApprovalRecord:
    # No Google HTTP client is reachable from this function.
    try:
        row = _rpc(access_token, "focusos_propose_calendar_action", {
            "p_run_id": str(run_id), "p_block_index": request.block_index,
        })
        if not isinstance(row, dict):
            raise DatabaseUnavailable("Approval proposal unavailable")
        approval = ApprovalRecord.model_validate(row)
        if approval.run_id != run_id or approval.block_index != request.block_index:
            raise DatabaseUnavailable("Approval identity mismatch")
        return approval
    except ValidationError as exc:
        raise DatabaseUnavailable("Invalid approval record") from exc
    except DatabaseUnavailable as exc:
        cause = exc.__cause__
        message = getattr(cause, "message", None)
        code = PROPOSAL_REASONS.get(message) if isinstance(message, str) else None
        if code:
            raise ProposalRejected(code) from exc
        raise
