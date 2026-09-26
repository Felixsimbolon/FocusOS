"""Typed read-only tool boundary. Identity and risk are server-owned."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolValidationError(ValueError):
    pass


class TasksListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open"] = "open"
    limit: int = Field(default=20, ge=1, le=20)
    project_ref: str | None = Field(default=None, max_length=80)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["tasks.list"]
    arguments: TasksListArguments


def validate_tool_request(name: str, arguments: object) -> ToolRequest:
    try:
        return ToolRequest.model_validate({"name": name, "arguments": arguments})
    except ValidationError as exc:
        raise ToolValidationError("Unknown or invalid tool request") from exc


def argument_hash(name: str, arguments: object) -> str:
    canonical = json.dumps({"name": name, "arguments": arguments},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
