"""Strict, versioned extraction candidates and grounded date checks."""
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Strict = ConfigDict(extra="forbid", strict=True)
DeadlineKind = Literal["none", "date", "datetime", "unresolved"]
PriorityHint = Literal["low", "normal", "high", "unspecified"]


class Evidence(BaseModel):
    model_config = Strict
    source_ref: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=500)


class Relation(BaseModel):
    model_config = Strict
    event_ref: str = Field(min_length=1, max_length=80)
    offset_days: int = Field(ge=-366, le=366)


class Deadline(BaseModel):
    model_config = Strict
    kind: DeadlineKind
    value: str | None
    timezone: str | None
    raw_text: str = Field(max_length=500)
    reference_time: datetime
    relation: Relation | None

    @field_validator("reference_time", mode="before")
    @classmethod
    def parse_reference_time(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def check_shape(self) -> "Deadline":
        if self.reference_time.utcoffset() is None:
            raise ValueError("Reference time needs UTC offset")
        if self.kind in ("none", "unresolved"):
            if self.value is not None or self.timezone is not None or self.relation is not None:
                raise ValueError("Unresolved date cannot carry a resolved value")
            return self
        if not self.value or not self.timezone:
            raise ValueError("Resolved deadline requires a value and timezone")
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Timezone must be an IANA name") from exc
        if self.kind == "date":
            if len(self.value) != 10 or date.fromisoformat(self.value).isoformat() != self.value:
                raise ValueError("Date must be YYYY-MM-DD")
        else:
            value = datetime.fromisoformat(self.value)
            if value.utcoffset() is None or value.astimezone(zone).replace(tzinfo=None) != value.replace(tzinfo=None):
                raise ValueError("Date-time must have a matching zone offset")
        return self


class EventStart(BaseModel):
    model_config = Strict
    kind: Literal["date", "datetime", "unresolved"]
    value: str | None
    timezone: str | None

    @model_validator(mode="after")
    def check_shape(self) -> "EventStart":
        if self.kind == "unresolved":
            if self.value is not None or self.timezone is not None:
                raise ValueError("Unresolved event start cannot have a value")
        else:
            Deadline(kind=self.kind, value=self.value, timezone=self.timezone,
                     raw_text="", reference_time=datetime.now().astimezone(), relation=None)
        return self


class TaskExtraction(BaseModel):
    model_config = Strict
    schema_version: Literal["1"]
    local_ref: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=2000)
    deadline: Deadline
    estimate_minutes: int | None = Field(ge=1, le=1440)
    estimate_origin: Literal["explicit", "suggested", "unknown"]
    priority_hint: PriorityHint
    project_candidate: str | None = Field(max_length=100)
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(min_length=1, max_length=5)
    uncertainties: list[str] = Field(max_length=10)

    @model_validator(mode="after")
    def check_estimate(self) -> "TaskExtraction":
        if self.estimate_minutes is None and self.estimate_origin != "unknown":
            raise ValueError("Estimate origin requires a value")
        return self


class EventExtraction(BaseModel):
    model_config = Strict
    schema_version: Literal["1"]
    local_ref: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    start: EventStart
    end: EventStart | None
    evidence: list[Evidence] = Field(min_length=1, max_length=5)
    confidence: float = Field(ge=0, le=1)
    uncertainties: list[str] = Field(max_length=10)


class FactExtraction(BaseModel):
    model_config = Strict
    text: str = Field(min_length=1, max_length=500)
    kind: Literal["fact", "decision"]
    evidence: list[Evidence] = Field(min_length=1, max_length=5)


class RequestExtraction(BaseModel):
    model_config = Strict
    kind: Literal["scheduling_request", "other"]
    text: str = Field(min_length=1, max_length=500)
    evidence: list[Evidence] = Field(min_length=1, max_length=5)


class ExtractionEnvelope(BaseModel):
    model_config = Strict
    schema_version: Literal["1"]
    source_ref: str = Field(min_length=1, max_length=100)
    tasks: list[TaskExtraction] = Field(max_length=10)
    events: list[EventExtraction] = Field(max_length=10)
    facts: list[FactExtraction] = Field(max_length=10)
    requests: list[RequestExtraction] = Field(max_length=10)
    project_candidates: list[str] = Field(max_length=10)
    uncertainties: list[str] = Field(max_length=10)

    @model_validator(mode="after")
    def check_count(self) -> "ExtractionEnvelope":
        if sum(map(len, (self.tasks, self.events, self.facts, self.requests))) > 10:
            raise ValueError("Too many candidates")
        refs = [item.local_ref for item in (*self.tasks, *self.events)]
        if len(refs) != len(set(refs)):
            raise ValueError("Candidate references must be unique")
        return self


def validate_grounding(result: ExtractionEnvelope, source_ref: str, body: str, reference_time: datetime) -> None:
    if result.source_ref != source_ref:
        raise ValueError("Source reference mismatch")
    event_by_ref = {event.local_ref: event for event in result.events}
    for candidate in (*result.tasks, *result.events, *result.facts, *result.requests):
        for evidence in candidate.evidence:
            if evidence.source_ref != source_ref or evidence.quote not in body:
                raise ValueError("Evidence does not occur in the source")
    for task in result.tasks:
        deadline = task.deadline
        if deadline.reference_time != reference_time:
            raise ValueError("Model changed the reference time")
        if deadline.raw_text and deadline.raw_text not in body:
            raise ValueError("Deadline wording does not occur in the source")
        if deadline.relation is not None:
            event = event_by_ref.get(deadline.relation.event_ref)
            if event is None or event.start.kind != "date" or deadline.kind != "date":
                raise ValueError("Relative deadline needs a resolved date-only event")
            expected = date.fromisoformat(event.start.value) + timedelta(days=deadline.relation.offset_days)
            if deadline.value != expected.isoformat() or deadline.timezone != event.start.timezone:
                raise ValueError("Relative deadline does not match its event")
