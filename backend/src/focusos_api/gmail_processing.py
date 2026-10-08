"""One eligible Gmail source goes through the existing durable review path."""
from uuid import UUID

from pydantic import BaseModel

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.extractor import MODEL, PROMPT_VERSION, SCHEMA_VERSION
from focusos_api.extractions import ExtractionEnvelopeResponse
from focusos_api.auto_capture import process_and_capture


class GmailProcessOne(BaseModel):
    state: str
    source_id: UUID | None = None
    extraction: ExtractionEnvelopeResponse | None = None


def next_gmail_source(access_token: str, excluded: list[str] | None = None) -> UUID | None:
    with scoped_client(access_token) as (_, client):
        candidate = client.rpc("focusos_next_gmail_capture", {
            "p_schema": SCHEMA_VERSION, "p_prompt": PROMPT_VERSION, "p_model": MODEL,
            "p_excluded": excluded or [],
        }).execute().data
    if candidate is None:
        return None
    try:
        source_id = UUID(str(candidate))
    except ValueError as exc:
        raise DatabaseUnavailable("Unexpected Gmail queue response") from exc
    return source_id


def process_one_gmail_source(access_token: str) -> GmailProcessOne:
    source_id = next_gmail_source(access_token)
    if source_id is None:
        return GmailProcessOne(state="no_pending")
    extraction = process_and_capture(access_token, source_id)
    return GmailProcessOne(state=extraction.extraction.status,
                           source_id=source_id, extraction=extraction)
