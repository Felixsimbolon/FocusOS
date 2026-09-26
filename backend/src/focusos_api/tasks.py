"""Task request schemas with explicit date-only and zoned-deadline semantics."""

from datetime import date, datetime
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Priority = Literal["low", "normal", "high"]
DueKind = Literal["none", "date", "datetime"]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: Priority = "normal"
    due_kind: DueKind = "none"
    due_date: date | None = None
    due_at: datetime | None = None
    due_timezone: str | None = Field(default=None, min_length=1, max_length=64)
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
