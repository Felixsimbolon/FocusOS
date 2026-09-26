"""Validated, user-owned scheduling preferences."""

from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from focusos_api.database import DatabaseUnavailable, scoped_client


class WorkingHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: list[int] = Field(min_length=1, max_length=7)
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)

    @field_validator("days")
    @classmethod
    def valid_days(cls, days: list[int]) -> list[int]:
        if any(day < 1 or day > 7 for day in days) or len(set(days)) != len(days):
            raise ValueError("Days must be unique ISO weekdays from 1 to 7")
        return sorted(days)

    @model_validator(mode="after")
    def valid_range(self) -> "WorkingHours":
        if self.start_minute >= self.end_minute:
            raise ValueError("Working hours must end after they start")
        return self


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(min_length=1, max_length=64)
    working_hours: WorkingHours

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, timezone: str) -> str:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use a valid IANA timezone name") from exc
        return timezone


class ProfileRecord(ProfileInput):
    id: UUID


class ProfileEnvelope(BaseModel):
    profile: ProfileRecord | None


def read_profile(access_token: str) -> ProfileRecord | None:
    with scoped_client(access_token) as (user_id, supabase):
        rows = (
            supabase.table("profiles")
            .select("id,timezone,working_hours")
            .eq("id", user_id)
            .limit(1)
            .execute()
            .data
        )

    if not rows:
        return None
    if not isinstance(rows, list) or len(rows) != 1:
        raise DatabaseUnavailable("Unexpected profile response")
    return ProfileRecord.model_validate(rows[0])


def save_profile(access_token: str, profile: ProfileInput) -> ProfileRecord:
    with scoped_client(access_token) as (_, supabase):
        rows = (
            supabase.rpc(
                "focusos_save_profile",
                {
                    "p_timezone": profile.timezone,
                    "p_working_hours": profile.working_hours.model_dump(),
                },
            )
            .execute()
            .data
        )

    if not isinstance(rows, list) or len(rows) != 1:
        raise DatabaseUnavailable("Unexpected profile save response")
    return ProfileRecord.model_validate(rows[0])
