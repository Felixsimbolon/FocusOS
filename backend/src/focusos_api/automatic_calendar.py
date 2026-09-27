"""One owner-scoped automatic Calendar block using the existing safe write path."""
from uuid import UUID

from pydantic import ValidationError

from focusos_api.agent_continuation import load_command_run
from focusos_api.agent_tasks import _rpc
from focusos_api.approval_execute import execute_approval
from focusos_api.approval_proposal import ApprovalRecord, ProposalInput, propose_calendar_event
from focusos_api.database import DatabaseUnavailable


class AutomaticCalendarUnavailable(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def schedule_automatic_block(access_token: str, run_id: UUID, block_index: int) -> ApprovalRecord:
    run = load_command_run(access_token, run_id)
    if run.checkpoint.get("auto_calendar") is not True:
        raise AutomaticCalendarUnavailable("automatic_plan_required")
    if run.status != "succeeded" or not isinstance(run.result, dict) or run.result.get("status") != "proposed":
        raise AutomaticCalendarUnavailable("plan_not_ready")
    blocks = run.result.get("blocks")
    if not isinstance(blocks, list) or block_index < 0 or block_index >= len(blocks):
        raise AutomaticCalendarUnavailable("block_unavailable")

    proposal = propose_calendar_event(access_token, run_id, ProposalInput(block_index=block_index))
    if proposal.authorization_mode != "automatic":
        row = _rpc(access_token, "focusos_authorize_automatic_calendar_action", {
            "p_run_id": str(run_id), "p_block_index": block_index,
        })
        try:
            proposal = ApprovalRecord.model_validate(row)
        except ValidationError as exc:
            raise DatabaseUnavailable("Automatic Calendar authorization unavailable") from exc
    if proposal.run_id != run_id or proposal.block_index != block_index or proposal.authorization_mode != "automatic":
        raise DatabaseUnavailable("Automatic Calendar authorization identity mismatch")
    if proposal.status in ("approved", "executing", "unknown"):
        return execute_approval(access_token, proposal.id)
    return proposal
