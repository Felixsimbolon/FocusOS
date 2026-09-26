"""Persist one read-only command run and return server-grounded task results."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from focusos_api.agent_model import AgentModelError, finish_tasks_turn, first_tasks_turn
from focusos_api.agent_tools import ToolValidationError, argument_hash, validate_tool_request
from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.tasks import list_tasks


class CommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    command: str = Field(min_length=1, max_length=1000)


class CommandResult(BaseModel):
    run_id: UUID
    status: str
    message: str
    tasks: list[dict] = Field(default_factory=list)


def _rpc(access_token: str, name: str, args: dict):
    with scoped_client(access_token) as (_, client):
        return client.rpc(name, args).execute().data


def _checkpoint(access_token: str, run_id: UUID, version: int, status: str,
                stage: str, checkpoint: dict, result: dict | None,
                turns: int, calls: int, error: str | None = None) -> bool:
    return _rpc(access_token, "focusos_checkpoint_command_run", {
        "p_run_id": str(run_id), "p_expected_version": version, "p_status": status,
        "p_stage": stage, "p_checkpoint": checkpoint, "p_result": result,
        "p_model_turns": turns, "p_tool_calls_count": calls, "p_safe_error": error,
    }) is True


def _log(access_token: str, run_id: UUID, name: str, args: dict,
         status: str, code: str | None = None) -> None:
    saved = _rpc(access_token, "focusos_log_tool_call", {
        "p_run_id": str(run_id), "p_ordinal": 1, "p_name": name,
        "p_arguments_hash": argument_hash(name, args),
        "p_status": status, "p_safe_code": code,
    })
    if saved is not True:
        raise DatabaseUnavailable("Tool ledger unavailable")


def run_tasks_command(access_token: str, request: CommandInput) -> CommandResult:
    initial = _rpc(access_token, "focusos_start_command_run", {
        "p_request_key": str(request.request_key), "p_command": request.command.strip(),
    })
    if not isinstance(initial, dict):
        raise DatabaseUnavailable("Unexpected command run")
    run_id, status, version = UUID(str(initial["id"])), initial["status"], initial["version"]
    if status != "pending" or not _checkpoint(access_token, run_id, version,
            "running", "tasks", {}, None, 0, 0):
        return CommandResult(run_id=run_id, status="waiting",
                             message="Run already started; inspect its saved status")
    try:
        _, call_id, args, output = first_tasks_turn(request.command)
        logical = validate_tool_request("tasks.list", args)
        if logical.arguments.project_ref is not None:
            raise ToolValidationError("Project filter is not enabled")
        normalized_args = logical.arguments.model_dump(exclude={"project_ref"})
        _log(access_token, run_id, "tasks.list", normalized_args, "requested")
        task_page = list_tasks(access_token, status="open", limit=logical.arguments.limit)
        task_data = [
            {"id": str(task.id), "title": task.title, "due_kind": task.due_kind,
             "due_date": task.due_date.isoformat() if task.due_date else None,
             "due_at": task.due_at.isoformat() if task.due_at else None,
             "source_id": str(task.source_id) if task.source_id else None}
            for task in task_page.tasks
        ]
        tool_result = {"tasks": task_data, "truncated": task_page.truncated}
        _log(access_token, run_id, "tasks.list", normalized_args, "succeeded")
        finish_tasks_turn(request.command, output, call_id, tool_result)
        result = {"message": f"Found {len(task_data)} open task(s).",
                  "tasks": task_data, "truncated": task_page.truncated}
        if not _checkpoint(access_token, run_id, version+1, "succeeded", "done",
                           {}, result, 2, 1):
            raise DatabaseUnavailable("Run checkpoint lost")
        return CommandResult(run_id=run_id, status="succeeded",
                             message=result["message"], tasks=task_data)
    except (AgentModelError, ToolValidationError, DatabaseUnavailable) as exc:
        code = exc.code if isinstance(exc, AgentModelError) else (
            "invalid_tool_request" if isinstance(exc, ToolValidationError) else "database_unavailable")
        _checkpoint(access_token, run_id, version+1, "failed", "done", {}, None, 0, 0, code)
        raise
