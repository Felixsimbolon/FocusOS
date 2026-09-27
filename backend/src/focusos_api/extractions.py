"""Durable, deduplicated extraction review repository and orchestration."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.extractor import ExtractionFailure, MODEL, PROMPT_VERSION, SCHEMA_VERSION
from focusos_api.profiles import read_profile
from focusos_api.runs import recorded_extraction
from focusos_api.sources import get_source

SELECT = ("id,source_id,content_hash,schema_version,prompt_version,model_version,"
          "status,validated_payload,safe_error,ignored_item_keys,run_id,created_at,updated_at,reviewed_at")


class ExtractionNotFound(Exception):
    pass


class ExtractionSourceExpired(Exception):
    pass


class ExtractionRateLimited(Exception):
    pass


class ExtractionRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    source_id: UUID
    content_hash: str
    schema_version: str
    prompt_version: str
    model_version: str
    status: Literal["processing", "ready", "failed"]
    validated_payload: dict | None
    safe_error: str | None
    ignored_item_keys: list[str] = Field(default_factory=list)
    confirmed_item_keys: list[str] = Field(default_factory=list)
    run_id: UUID | None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None


class ExtractionEnvelopeResponse(BaseModel):
    extraction: ExtractionRecord
    replayed: bool
    capture: dict | None = None


def _with_confirmed_items(record: ExtractionRecord, owner: str, client: object) -> ExtractionRecord:
    if record.status != "ready":
        return record
    rows = (client.table("tasks").select("extraction_item_key")
            .eq("user_id", owner).eq("extraction_result_id", str(record.id))
            .limit(10).execute().data)
    if not isinstance(rows, list):
        raise DatabaseUnavailable("Unexpected confirmed candidate list")
    return record.model_copy(update={
        "confirmed_item_keys": [row["extraction_item_key"] for row in rows
                                if isinstance(row, dict) and isinstance(row.get("extraction_item_key"), str)]
    })


def _read_result(access_token: str, result_id: UUID) -> ExtractionRecord:
    with scoped_client(access_token) as (owner, client):
        rows = client.table("extraction_results").select(SELECT).eq("user_id", owner).eq("id", str(result_id)).limit(1).execute().data
        if not isinstance(rows, list) or not rows:
            raise DatabaseUnavailable("Extraction result missing")
        return _with_confirmed_items(ExtractionRecord.model_validate(rows[0]), owner, client)


def read_extraction(access_token: str, source_id: UUID) -> ExtractionRecord | None:
    source = get_source(access_token, source_id)
    if source is None:
        raise ExtractionNotFound()
    with scoped_client(access_token) as (owner, client):
        rows = (client.table("extraction_results").select(SELECT)
                .eq("user_id", owner).eq("source_id", str(source_id))
                .eq("content_hash", source.body_hash)
                .eq("schema_version", SCHEMA_VERSION)
                .eq("prompt_version", PROMPT_VERSION)
                .eq("model_version", MODEL).limit(1).execute().data)
        if not isinstance(rows, list) or not rows:
            return None
        return _with_confirmed_items(ExtractionRecord.model_validate(rows[0]), owner, client)


def process_extraction(access_token: str, source_id: UUID) -> ExtractionEnvelopeResponse:
    source = get_source(access_token, source_id)
    if source is None:
        raise ExtractionNotFound()
    if source.normalized_body is None:
        raise ExtractionSourceExpired()
    with scoped_client(access_token) as (_, client):
        claim = client.rpc("focusos_claim_extraction", {
            "p_source_id": str(source_id), "p_content_hash": source.body_hash,
            "p_schema": SCHEMA_VERSION, "p_prompt": PROMPT_VERSION, "p_model": MODEL,
        }).execute().data
    if not isinstance(claim, dict):
        raise DatabaseUnavailable("Unexpected extraction claim")
    state = claim.get("state")
    if state == "missing":
        raise ExtractionNotFound()
    if state == "source_unavailable":
        raise ExtractionSourceExpired()
    if state == "rate_limited":
        raise ExtractionRateLimited()
    if state in ("ready", "processing"):
        return ExtractionEnvelopeResponse(extraction=_read_result(access_token, UUID(claim["id"])), replayed=True)
    if state != "claimed":
        raise DatabaseUnavailable("Unexpected extraction claim")
    result_id = UUID(claim["id"])
    token = UUID(claim["claim_token"])
    profile = read_profile(access_token)
    zone_name = profile.timezone if profile else "UTC"
    reference = source.received_at.astimezone(ZoneInfo(zone_name))
    recorded = None
    failure = None
    try:
        recorded = recorded_extraction(access_token, source_id, source.source_ref,
                                       source.normalized_body, reference, zone_name)
    except ExtractionFailure as exc:
        failure = exc
    with scoped_client(access_token) as (_, client):
        finished = client.rpc("focusos_finish_extraction", {
            "p_result_id": str(result_id), "p_claim_token": str(token),
            "p_status": "failed" if failure else "ready",
            "p_payload": recorded.call.result.model_dump(mode="json") if recorded else None,
            "p_safe_error": failure.kind if failure else None,
            "p_run_id": str(recorded.run_id) if recorded else None,
        }).execute().data
    if finished is not True:
        raise DatabaseUnavailable("Extraction claim expired before completion")
    return ExtractionEnvelopeResponse(extraction=_read_result(access_token, result_id), replayed=False)


class IgnoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_ref: str
    ignored: bool


def set_extraction_ignored(access_token: str, extraction_id: UUID, request: IgnoreInput) -> ExtractionRecord:
    if not request.local_ref or len(request.local_ref) > 80:
        raise ExtractionNotFound()
    with scoped_client(access_token) as (_, client):
        changed = client.rpc("focusos_set_extraction_ignored", {
            "p_extraction_id": str(extraction_id),
            "p_local_ref": request.local_ref,
            "p_ignored": request.ignored,
        }).execute().data
    if changed is not True:
        raise ExtractionNotFound()
    return _read_result(access_token, extraction_id)
