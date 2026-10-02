"""A narrow model contract: interpret intent, never invent Calendar actions."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


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
