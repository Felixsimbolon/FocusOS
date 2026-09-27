"""Bounded Gemini embedding for one explicitly confirmed memory."""

import hashlib
import json
import math
from uuid import UUID

import httpx
from pydantic import BaseModel

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.gemini import api_key, url

EMBED_MODEL = "gemini-embedding-2"
EMBED_DIM = 256
EMBED_URL = url(EMBED_MODEL, "embedContent")


class EmbeddingError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class EmbeddingState(BaseModel):
    state: str
    memory_id: UUID


def embedding_content(text: str, quote: str) -> str:
    return text.strip() + "\nEvidence: " + quote.strip()


def embed_text(text: str) -> list[float]:
    key = api_key()
    if not key:
        raise EmbeddingError("provider_unconfigured")
    if not text or len(text.encode("utf-8")) > 2500:
        raise EmbeddingError("invalid_vector")
    try:
        response = httpx.post(EMBED_URL, headers={"x-goog-api-key": key},
            json={"model": "models/" + EMBED_MODEL,
                  "content": {"parts": [{"text": text}]},
                  "embedContentConfig": {"outputDimensionality": EMBED_DIM}}, timeout=12.0)
        response.raise_for_status()
        if len(response.content) > 65536:
            raise EmbeddingError("invalid_vector")
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise EmbeddingError("provider_unavailable") from exc
    if not isinstance(data, dict):
        raise EmbeddingError("invalid_vector")
    embedding = data.get("embedding")
    vector = embedding.get("values") if isinstance(embedding, dict) else None
    if not isinstance(vector, list) or len(vector) != EMBED_DIM:
        raise EmbeddingError("invalid_vector")
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
           for value in vector) or not any(value != 0 for value in vector):
        raise EmbeddingError("invalid_vector")
    return [float(value) for value in vector]


def _rpc(access_token: str, name: str, args: dict):
    with scoped_client(access_token) as (_, client):
        return client.rpc(name, args).execute().data


def embed_memory(access_token: str, memory_id: UUID) -> EmbeddingState:
    with scoped_client(access_token) as (owner, client):
        rows = (client.table("memories").select("id,text,evidence_quote,status")
                .eq("id", str(memory_id)).eq("user_id", owner).limit(1).execute().data)
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("status") != "active":
        return EmbeddingState(state="unavailable", memory_id=memory_id)
    content = embedding_content(rows[0]["text"], rows[0]["evidence_quote"])
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    claim = _rpc(access_token, "focusos_claim_memory_embedding", {
        "p_memory_id": str(memory_id), "p_model": EMBED_MODEL,
        "p_dim": EMBED_DIM, "p_content_hash": content_hash,
    })
    if not isinstance(claim, dict) or claim.get("state") not in ("claimed", "reused", "busy", "unavailable"):
        raise DatabaseUnavailable("Unexpected embedding claim")
    if claim["state"] != "claimed":
        return EmbeddingState(state=claim["state"], memory_id=memory_id)
    lease = claim.get("lease_token")
    if not isinstance(lease, str) or embedding_content(claim.get("text", ""), claim.get("quote", "")) != content:
        raise DatabaseUnavailable("Embedding source changed during claim")
    try:
        vector = embed_text(content)
    except EmbeddingError as exc:
        _rpc(access_token, "focusos_finish_memory_embedding", {
            "p_memory_id": str(memory_id), "p_lease_token": lease,
            "p_content_hash": content_hash, "p_vector": None, "p_error": exc.code,
        })
        return EmbeddingState(state="failed", memory_id=memory_id)
    saved = _rpc(access_token, "focusos_finish_memory_embedding", {
        "p_memory_id": str(memory_id), "p_lease_token": lease,
        "p_content_hash": content_hash, "p_vector": json.dumps(vector, separators=(",", ":")),
        "p_error": None,
    })
    if saved is not True:
        raise DatabaseUnavailable("Embedding lease or source changed")
    return EmbeddingState(state="ready", memory_id=memory_id)
