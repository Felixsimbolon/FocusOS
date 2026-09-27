"""Derived run outcome from persisted approvals and append-only transitions."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from focusos_api.agent_continuation import load_command_run, list_run_tools
from focusos_api.approval_decisions import list_approvals
from focusos_api.database import DatabaseUnavailable, scoped_client


class ApprovalTransition(BaseModel):
    model_config = ConfigDict(extra="ignore")
    approval_id: UUID
    block_index: int
    status: str
    status_version: int
    safe_code: str | None = None
    occurred_at: datetime


class RunActionAudit(BaseModel):
    run_id: UUID
    planning_status: str
    action_status: str
    expected_blocks: int
    approvals_count: int
    succeeded_count: int
    tool_calls: list[dict]
    transitions: list[ApprovalTransition]


def _state(expected: int, statuses: list[str]) -> str:
    if expected == 0:
        return "no_proposal"
    if statuses and len(statuses) == expected and all(item == "succeeded" for item in statuses):
        return "completed"
    if "unknown" in statuses:
        return "unknown"
    if "executing" in statuses:
        return "executing"
    if any(item in ("failed", "stale", "rejected", "expired") for item in statuses):
        return "partially_completed" if "succeeded" in statuses else "blocked"
    if "succeeded" in statuses:
        return "partially_completed"
    if len(statuses) < expected:
        return "awaiting_proposals"
    if "approved" in statuses:
        return "approved_not_executed"
    return "awaiting_approval"


def read_run_action_audit(access_token: str, run_id: UUID) -> RunActionAudit:
    run = load_command_run(access_token, run_id)
    approvals = list_approvals(access_token, run_id)
    tools = list_run_tools(access_token, run_id)
    with scoped_client(access_token) as (user_id, client):
        rows = (client.table("approval_action_events")
                .select("approval_id,block_index,status,status_version,safe_code,occurred_at")
                .eq("user_id", user_id).eq("run_id", str(run_id))
                .order("id").limit(128).execute().data)
    if not isinstance(rows, list):
        raise DatabaseUnavailable("Approval audit unavailable")
    result = run.result or {}
    expected = len(result.get("blocks", [])) if result.get("status") == "proposed" else 0
    statuses = [item.status for item in approvals]
    return RunActionAudit(run_id=run_id, planning_status=run.status,
        action_status=_state(expected,statuses),expected_blocks=expected,
        approvals_count=len(approvals),succeeded_count=statuses.count("succeeded"),
        tool_calls=tools,transitions=[ApprovalTransition.model_validate(row) for row in rows])
