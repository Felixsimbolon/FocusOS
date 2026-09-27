"""Owner-scoped approval listing and exact-action human decisions."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from focusos_api.agent_tasks import _rpc
from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.database import DatabaseUnavailable


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]


def list_approvals(access_token: str, run_id: UUID) -> list[ApprovalRecord]:
    rows = _rpc(access_token, "focusos_list_approvals", {"p_run_id": str(run_id)})
    if not isinstance(rows, list):
        raise DatabaseUnavailable("Approval list unavailable")
    try:
        return [ApprovalRecord.model_validate(row) for row in rows]
    except ValidationError as exc:
        raise DatabaseUnavailable("Approval list invalid") from exc


def decide_approval(access_token: str, approval_id: UUID, request: DecisionInput) -> ApprovalRecord:
    row = _rpc(access_token, "focusos_decide_approval", {
        "p_approval_id": str(approval_id), "p_decision": request.decision,
    })
    try:
        result = ApprovalRecord.model_validate(row)
    except ValidationError as exc:
        raise DatabaseUnavailable("Approval decision unavailable") from exc
    if result.id != approval_id:
        raise DatabaseUnavailable("Approval identity mismatch")
    return result
