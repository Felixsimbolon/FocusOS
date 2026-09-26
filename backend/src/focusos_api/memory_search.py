"""Owner-filtered semantic memory retrieval with explicitly marked lexical fallback."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.memory_embeddings import EmbeddingError, embed_text


class MemorySearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1000)
    project_id: UUID | None = None
    limit: int = Field(default=5, ge=1, le=5)


class MemoryMatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    text: str
    evidence_quote: str
    source_id: UUID
    source_ref: str
    project_id: UUID | None
    match_kind: str
    score: float


class MemorySearchResult(BaseModel):
    mode: str
    matches: list[MemoryMatch]


def search_memories(access_token: str, request: MemorySearchInput) -> MemorySearchResult:
    vector: list[float] | None
    try:
        vector = embed_text(request.query.strip())
        mode = "semantic_enabled"
    except EmbeddingError:
        vector = None
        mode = "lexical_fallback"
    with scoped_client(access_token) as (_, client):
        result = client.rpc("focusos_search_memories", {
            "p_query": request.query.strip(),
            "p_vector": None if vector is None else "[" + ",".join(format(v, ".9g") for v in vector) + "]",
            "p_project_id": str(request.project_id) if request.project_id else None,
            "p_limit": request.limit,
        }).execute().data
    if not isinstance(result, list):
        raise DatabaseUnavailable("Memory search unavailable")
    return MemorySearchResult(mode=mode, matches=[MemoryMatch.model_validate(row) for row in result])
