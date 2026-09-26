"""Validated task schemas and owner-scoped persistence."""

from datetime import date, datetime
import hashlib
import json
import re
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from focusos_api.database import DatabaseUnavailable, scoped_client

Priority = Literal["low", "normal", "high"]
DueKind = Literal["none", "date", "datetime"]
TaskStatus = Literal["open", "done", "archived"]

_TASK_SELECT = (
    "id,title,description,status,priority,due_kind,due_date,due_at,due_timezone,"
    "estimate_minutes,estimate_origin,project_id,version,created_at,updated_at"
)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: Priority = "normal"
    due_kind: DueKind = "none"
    due_date: date | None = None
    due_at: datetime | None = None
    due_timezone: str | None = Field(default=None, min_length=1, max_length=64)
    project_id: UUID | None = None
    estimate_minutes: int | None = Field(default=None, strict=True, ge=1, le=1440)

    @field_validator("title")
    @classmethod
    def normalized_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be blank")
        return value

    @field_validator("description")
    @classmethod
    def normalized_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("due_date", mode="before")
    @classmethod
    def date_only(cls, value: object) -> object:
        if value is None or isinstance(value, date) and not isinstance(value, datetime):
            return value
        if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            raise ValueError("Date deadlines must use YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Date deadline is invalid") from exc

    @model_validator(mode="after")
    def consistent_deadline(self) -> "TaskCreate":
        if self.due_kind == "none":
            if any(value is not None for value in (self.due_date, self.due_at, self.due_timezone)):
                raise ValueError("No-deadline tasks cannot include deadline fields")
            return self

        if self.due_kind == "date":
            if self.due_date is None or self.due_at is not None or self.due_timezone is not None:
                raise ValueError("Date deadlines require only due_date")
            return self

        if self.due_date is not None or self.due_at is None or self.due_timezone is None:
            raise ValueError("Date-time deadlines require due_at and due_timezone only")
        if self.due_at.utcoffset() is None:
            raise ValueError("Date-time deadlines must include a UTC offset")
        try:
            zone = ZoneInfo(self.due_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use a valid IANA timezone name") from exc
        local_time = self.due_at.astimezone(zone)
        if local_time.replace(tzinfo=None) != self.due_at.replace(tzinfo=None):
            raise ValueError("The timestamp offset does not match due_timezone")
        return self


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: Priority
    due_kind: DueKind
    due_date: date | None
    due_at: datetime | None
    due_timezone: str | None
    estimate_minutes: int | None
    estimate_origin: Literal["explicit", "suggested", "unknown"] | None
    project_id: UUID | None
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class TaskListEnvelope(BaseModel):
    tasks: list[TaskRecord]
    truncated: bool


class TaskCreateEnvelope(BaseModel):
    task: TaskRecord
    replayed: bool


class TaskRequestConflict(Exception):
    """An idempotency key was reused for a different task payload."""


class TaskProjectNotFound(Exception):
    """The requested project is not owned by the authenticated user."""


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def normalized_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name cannot be blank")
        return value


class ProjectRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    created_at: datetime


class ProjectEnvelope(BaseModel):
    project: ProjectRecord
    existing: bool


class ProjectListEnvelope(BaseModel):
    projects: list[ProjectRecord]


def _payload_hash(task: TaskCreate) -> str:
    canonical = json.dumps(
        task.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def list_tasks(
    access_token: str,
    *,
    status: TaskStatus | None = None,
    limit: int = 100,
) -> TaskListEnvelope:
    with scoped_client(access_token) as (user_id, supabase):
        query = (
            supabase.table("tasks")
            .select(_TASK_SELECT)
            .eq("user_id", user_id)
        )
        if status is not None:
            query = query.eq("status", status)
        rows = (
            query.order("created_at", desc=True)
            .order("id", desc=True)
            .limit(limit + 1)
            .execute()
            .data
        )

    if not isinstance(rows, list):
        raise DatabaseUnavailable("Unexpected task list response")
    return TaskListEnvelope(
        tasks=[TaskRecord.model_validate(row) for row in rows[:limit]],
        truncated=len(rows) > limit,
    )


def create_task(
    access_token: str,
    request_id: UUID,
    task: TaskCreate,
) -> TaskCreateEnvelope:
    payload_hash = _payload_hash(task)
    with scoped_client(access_token) as (_, supabase):
        rows = (
            supabase.rpc(
                "focusos_create_task",
                {
                    "p_create_request_id": str(request_id),
                    "p_create_request_hash": payload_hash,
                    "p_title": task.title,
                    "p_description": task.description,
                    "p_priority": task.priority,
                    "p_due_kind": task.due_kind,
                    "p_due_date": task.due_date.isoformat() if task.due_date else None,
                    "p_due_at": task.due_at.isoformat() if task.due_at else None,
                    "p_due_timezone": task.due_timezone,
                    "p_estimate_minutes": task.estimate_minutes,
                    "p_project_id": str(task.project_id) if task.project_id else None,
                },
            )
            .execute()
            .data
        )

    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise DatabaseUnavailable("Unexpected task create response")
    row = rows[0]
    if row.get("project_available") is False:
        raise TaskProjectNotFound()
    if row.get("stored_request_hash") != payload_hash:
        raise TaskRequestConflict()
    task_data = row.get("task")
    if not isinstance(task_data, dict):
        raise DatabaseUnavailable("Unexpected task create response")
    return TaskCreateEnvelope(
        task=TaskRecord.model_validate(task_data),
        replayed=row.get("replayed") is True,
    )


def list_projects(access_token: str) -> ProjectListEnvelope:
    with scoped_client(access_token) as (user_id, supabase):
        rows = (
            supabase.table("projects")
            .select("id,name,created_at")
            .eq("user_id", user_id)
            .order("name")
            .order("id")
            .limit(100)
            .execute()
            .data
        )

    if not isinstance(rows, list):
        raise DatabaseUnavailable("Unexpected project list response")
    return ProjectListEnvelope(
        projects=[ProjectRecord.model_validate(row) for row in rows]
    )


def create_project(access_token: str, project: ProjectCreate) -> ProjectEnvelope:
    with scoped_client(access_token) as (_, supabase):
        rows = (
            supabase.rpc("focusos_create_project", {"p_name": project.name})
            .execute()
            .data
        )

    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise DatabaseUnavailable("Unexpected project create response")
    row = rows[0]
    project_data = row.get("project")
    if not isinstance(project_data, dict) or not isinstance(row.get("existing"), bool):
        raise DatabaseUnavailable("Unexpected project create response")
    return ProjectEnvelope(
        project=ProjectRecord.model_validate(project_data),
        existing=row["existing"],
    )
