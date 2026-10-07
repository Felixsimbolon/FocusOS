"""Owned confirmed memories with exact source evidence."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.sources import get_source


class MemoryEvidenceInvalid(ValueError):
    pass


class MemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    source_id: UUID
    project_id: UUID | None = None
    text: str = Field(min_length=1, max_length=500)
    evidence_quote: str = Field(min_length=1, max_length=500)


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    source_id: UUID
    project_id: UUID | None
    source_hash: str
    text: str
    evidence_quote: str
    status: str
    embedding_status: str = "pending"
    embedding_model: str | None = None
    embedding_error: str | None = None
    created_at: datetime


class MemoryList(BaseModel):
    memories: list[MemoryRecord]


def confirm_memory(access_token: str, request: MemoryInput) -> MemoryRecord:
    source = get_source(access_token, request.source_id)
    if source is None or source.normalized_body is None or not request.evidence_quote.strip() or (
        request.evidence_quote.strip() not in source.normalized_body
    ):
        raise MemoryEvidenceInvalid("Exact source quote required")
    with scoped_client(access_token) as (_, client):
        data = client.rpc("focusos_confirm_memory", {
            "p_request_key": str(request.request_key),
            "p_source_id": str(request.source_id),
            "p_project_id": str(request.project_id) if request.project_id else None,
            "p_text": request.text.strip(), "p_quote": request.evidence_quote.strip(),
        }).execute().data
    if not isinstance(data, dict):
        raise DatabaseUnavailable("Memory confirmation unavailable")
    return MemoryRecord.model_validate(data)


def list_memories(access_token: str, source_id: UUID | None = None) -> MemoryList:
    with scoped_client(access_token) as (owner, client):
        query = (client.table("memories")
                .select( "id,source_id,project_id,source_hash,text,evidence_quote,status,embedding_status,embedding_model,embedding_error,created_at")
                .eq("user_id", owner).eq("status", "active"))
        if source_id is not None:
            query = query.eq("source_id", str(source_id))
        rows = query.order("created_at", desc=True).limit(50).execute().data
    if not isinstance(rows, list):
        raise DatabaseUnavailable("Memories unavailable")
    return MemoryList(memories=[MemoryRecord.model_validate(row) for row in rows])


def supersede_memory(access_token: str, memory_id: UUID) -> bool:
    with scoped_client(access_token) as (_, client):
        result = client.rpc("focusos_supersede_memory", {
            "p_memory_id": str(memory_id),
        }).execute().data
    if not isinstance(result, bool):
        raise DatabaseUnavailable("Memory update unavailable")
    return result
