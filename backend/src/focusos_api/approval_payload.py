"""Exact, server-constructed Calendar action bound to one approval."""
import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApprovalPayloadError(ValueError):
    pass


class CalendarAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1"
    tool: str = "calendar.create_event"
    run_id: UUID
    block_index: int = Field(ge=0, le=15)
    task_id: UUID
    task_version: int = Field(ge=1)
    connection_id: UUID
    calendar_id: str = "primary"
    event_id: str
    title: str = Field(min_length=1, max_length=200)
    start: datetime
    end: datetime
    timezone: str = Field(min_length=1, max_length=64)
    source_id: UUID | None = None
    guests: list[str] = Field(default_factory=list)
    send_updates: str = "none"

    @model_validator(mode="after")
    def validate_action(self) -> "CalendarAction":
        if self.schema_version != "1" or self.tool != "calendar.create_event":
            raise ValueError("Unknown action contract")
        if self.calendar_id != "primary" or self.guests or self.send_updates != "none":
            raise ValueError("Calendar action may use only primary, no guests, no notifications")
        if re.fullmatch(r"[a-v0-9]{5,1024}", self.event_id) is None:
            raise ValueError("Invalid stable Calendar event ID")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Invalid Calendar timezone") from exc
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Event interval needs timezone")
        minutes = (self.end.astimezone(timezone.utc)-self.start.astimezone(timezone.utc)).total_seconds()/60
        if minutes < 15 or minutes > 480:
            raise ValueError("Event duration out of bounds")
        return self


def canonical_action_hash(action: CalendarAction) -> str:
    encoded = json.dumps(action.model_dump(mode="json"), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
