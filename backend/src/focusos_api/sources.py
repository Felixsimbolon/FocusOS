"""Bounded, owner-scoped manual source persistence."""
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from focusos_api.database import DatabaseUnavailable, scoped_client

SOURCE_SELECT = "id,kind,title,source_ref,normalized_body,body_hash,normalization_version,body_truncated,received_at,created_at,body_expires_at"
MAX_BODY_BYTES = 20480


class SourceConflict(Exception):
    pass


def normalize_source(text: str) -> str:
    # Manual input is plain text; remove controls and normalize line endings.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", normalized)
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n")).strip()
    if not normalized or len(normalized.encode("utf-8")) > MAX_BODY_BYTES:
        raise ValueError("Source text must be 1 to 20480 UTF-8 bytes")
    return normalized


class ManualSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=25000)
    received_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Source title cannot be blank")
        return value

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return normalize_source(value)

    @field_validator("received_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("received_at must have an offset")
        return value


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    kind: str
    title: str
    source_ref: str
    normalized_body: str | None
    body_hash: str
    normalization_version: str
    body_truncated: bool
    received_at: datetime
    created_at: datetime
    body_expires_at: datetime


class SourceEnvelope(BaseModel):
    source: SourceRecord
    replayed: bool


class SourceListEnvelope(BaseModel):
    sources: list[SourceRecord]


def create_manual_source(access_token: str, request_id: UUID, source: ManualSourceInput) -> SourceEnvelope:
    received = source.received_at or datetime.now(timezone.utc)
    body_hash = hashlib.sha256(source.text.encode("utf-8")).hexdigest()
    fingerprint = hashlib.sha256(json.dumps({
        "title": source.title, "body_hash": body_hash, "received_at": source.received_at.isoformat() if source.received_at else None
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    with scoped_client(access_token) as (_, client):
        client.rpc("focusos_expire_source_bodies", {"p_limit": 100}).execute()
        result = client.rpc("focusos_create_manual_source", {
            "p_request_id": str(request_id), "p_request_hash": fingerprint,
            "p_title": source.title, "p_body": source.text,
            "p_body_hash": body_hash, "p_received_at": received.isoformat(),
        }).execute().data
    if not isinstance(result, dict) or not isinstance(result.get("source"), dict):
        raise DatabaseUnavailable("Unexpected source response")
    if result.get("conflict"):
        raise SourceConflict()
    return SourceEnvelope(source=SourceRecord.model_validate(result["source"]),
                          replayed=result.get("replayed") is True)


def list_sources(access_token: str, limit: int = 30) -> SourceListEnvelope:
    with scoped_client(access_token) as (owner, client):
        client.rpc("focusos_expire_source_bodies", {"p_limit": 100}).execute()
        rows = client.table("source_items").select(SOURCE_SELECT).eq("user_id", owner).is_("deleted_at", "null").order("created_at", desc=True).limit(limit).execute().data
    if not isinstance(rows, list):
        raise DatabaseUnavailable("Unexpected source list response")
    return SourceListEnvelope(sources=[SourceRecord.model_validate(row) for row in rows])


def get_source(access_token: str, source_id: UUID) -> SourceRecord | None:
    with scoped_client(access_token) as (owner, client):
        client.rpc("focusos_expire_source_bodies", {"p_limit": 100}).execute()
        rows = client.table("source_items").select(SOURCE_SELECT).eq("user_id", owner).eq("id", str(source_id)).is_("deleted_at", "null").limit(1).execute().data
    return SourceRecord.model_validate(rows[0]) if isinstance(rows, list) and rows else None
