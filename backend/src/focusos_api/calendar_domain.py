"""Validated provider-neutral Calendar occurrences for deterministic scheduling."""

from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CalendarEventError(ValueError):
    """The provider event cannot be trusted for availability."""


class CalendarOccurrence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1, max_length=1024)
    calendar_id: str = "primary"
    title: str = Field(default="Busy", max_length=500)
    kind: Literal["timed", "all_day"]
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date_exclusive: date | None = None
    timezone: str | None = None
    status: Literal["confirmed", "tentative", "cancelled"] = "confirmed"
    transparency: Literal["opaque", "transparent"] = "opaque"
    self_response: Literal["accepted", "tentative", "needsAction", "declined"] | None = None
    recurring_event_id: str | None = None
    original_start: str | None = None
    observed_at: datetime

    @model_validator(mode="after")
    def valid_shape(self) -> "CalendarOccurrence":
        if self.observed_at.tzinfo is None:
            raise ValueError("Observation time requires an offset")
        if self.kind == "timed":
            if self.start_at is None or self.end_at is None:
                raise ValueError("Timed event requires start and end")
            if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
                raise ValueError("Timed event requires UTC offsets")
            if self.end_at.astimezone(timezone.utc) <= self.start_at.astimezone(timezone.utc):
                raise ValueError("Timed event must have positive duration")
            if self.start_date is not None or self.end_date_exclusive is not None:
                raise ValueError("Timed event cannot carry all-day dates")
        else:
            if self.start_date is None or self.end_date_exclusive is None:
                raise ValueError("All-day event requires date bounds")
            if self.end_date_exclusive <= self.start_date:
                raise ValueError("All-day end date must be exclusive")
            if self.start_at is not None or self.end_at is not None:
                raise ValueError("All-day event cannot carry timestamps")
            if not self.timezone:
                raise ValueError("All-day event requires a calendar timezone")
        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("Invalid IANA timezone") from exc
        return self
