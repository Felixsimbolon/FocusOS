"""Owned, provider-identity-keyed Gmail source upsert."""
import hashlib
from uuid import UUID

from pydantic import BaseModel

from focusos_api.connections import read_google_connection
from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.gmail_fetch import RawSelectedMessage, SelectedFetchInput, fetch_selected_messages
from focusos_api.gmail_normalize import GmailNormalizationError, normalize_gmail_message
from focusos_api.gmail_selection import GmailSelectionReconnect
from focusos_api.sources import SourceRecord


class GmailSourceStatus(BaseModel):
    id: str
    status: str
    source: SourceRecord | None = None
    created: bool = False
    changed: bool = False


class GmailIngestEnvelope(BaseModel):
    messages: list[GmailSourceStatus]


def upsert_gmail_source(access_token: str, connection_id: UUID,
                        item: RawSelectedMessage) -> GmailSourceStatus:
    if item.status == "unavailable" or item.message is None:
        return GmailSourceStatus(id=item.id, status="unavailable")
    normalized = normalize_gmail_message(item.message)
    body_hash = normalized.body_hash or hashlib.sha256(b"").hexdigest()
    with scoped_client(access_token) as (_, client):
        client.rpc("focusos_expire_source_bodies", {"p_limit": 100}).execute()
        result = client.rpc("focusos_upsert_gmail_source", {
            "p_connection_id": str(connection_id),
            "p_message_id": normalized.provider_message_id,
            "p_thread_id": normalized.thread_id,
            "p_history_id": normalized.history_id,
            "p_label_id": item.label_id,
            "p_title": normalized.title,
            "p_sender": normalized.sender,
            "p_received_at": normalized.received_at.isoformat(),
            "p_body": normalized.normalized_body,
            "p_body_hash": body_hash,
            "p_truncated": normalized.body_truncated,
            "p_has_attachments": normalized.has_attachments,
        }).execute().data
    if not isinstance(result, dict):
        raise DatabaseUnavailable("Unexpected Gmail upsert response")
    if result.get("outcome") == "connection_unavailable":
        raise GmailSelectionReconnect()
    if result.get("outcome") != "saved" or not isinstance(result.get("source"), dict):
        raise DatabaseUnavailable("Unexpected Gmail upsert response")
    return GmailSourceStatus(id=item.id,
        status="saved" if normalized.normalized_body else "nonactionable",
        source=SourceRecord.model_validate(result["source"]),
        created=result.get("created") is True,
        changed=result.get("changed") is True)


def ingest_selected_messages(access_token: str, request: SelectedFetchInput) -> GmailIngestEnvelope:
    items = fetch_selected_messages(access_token, request.ids)
    connection = read_google_connection(access_token)
    if connection is None or connection.status != "connected":
        raise GmailSelectionReconnect()
    return GmailIngestEnvelope(messages=[
        upsert_gmail_source(access_token, connection.id, item) for item in items
    ])
