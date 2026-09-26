"""One eligible Gmail source goes through the existing durable review path."""
from uuid import UUID

from pydantic import BaseModel

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.extractor import MODEL, PROMPT_VERSION, SCHEMA_VERSION
from focusos_api.extractions import ExtractionEnvelopeResponse, process_extraction


class GmailProcessOne(BaseModel):
    state: str
    source_id: UUID | None = None
    extraction: ExtractionEnvelopeResponse | None = None


def process_one_gmail_source(access_token: str) -> GmailProcessOne:
    with scoped_client(access_token) as (_, client):
        candidate = client.rpc("focusos_next_gmail_source", {
            "p_schema": SCHEMA_VERSION, "p_prompt": PROMPT_VERSION, "p_model": MODEL,
        }).execute().data
    if candidate is None:
        return GmailProcessOne(state="no_pending")
    try:
        source_id = UUID(str(candidate))
    except ValueError as exc:
        raise DatabaseUnavailable("Unexpected Gmail queue response") from exc
    extraction = process_extraction(access_token, source_id)
    return GmailProcessOne(state=extraction.extraction.status,
                           source_id=source_id, extraction=extraction)
