"""A narrow model contract: interpret intent, never invent Calendar actions."""
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SessionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    count: int = Field(ge=1, le=7)
    minutes: int = Field(ge=15, le=480)
    date_start: str
    date_end: str
    min_days_between: int = Field(ge=1, le=14)

    @model_validator(mode="after")
    def validate_range(self):
        first, last = date.fromisoformat(self.date_start), date.fromisoformat(self.date_end)
        if first.isoformat() != self.date_start or last.isoformat() != self.date_end:
            raise ValueError("Use ISO session dates")
        if last < first or (last-first).days >= 14 or self.count*self.minutes > 1440:
            raise ValueError("Session request exceeds a bounded date range or duration")
        return self


class PlanningSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["selected", "needs_clarification"]
    task_refs: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(max_length=20)
    duration_minutes: int | None
    day: Literal["any", "today", "tomorrow", "date"]
    date: str | None
    start_time: str | None
    end_time: str | None
    evidence_refs: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(max_length=5)
    questions: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(max_length=5)
    sessions: SessionSelection | None = None
