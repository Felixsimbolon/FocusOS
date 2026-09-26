"""Fetch full Gmail payloads only after fresh selected-label membership checks."""
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from focusos_api.gmail_selection import (GMAIL_ROOT, ID_PATTERN, GmailMessageGone,
    GmailSelectionError, google_bearer, parse_metadata, provider_json, selected_label_id)

MAX_SELECTED = 3
MAX_MESSAGE_BYTES = 524288


@dataclass(frozen=True)
class RawSelectedMessage:
    id: str
    status: Literal["available", "unavailable"]
    message: dict | None
    label_id: str


class SelectedFetchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=MAX_SELECTED)


class SelectedFetchStatus(BaseModel):
    id: str
    status: Literal["available", "unavailable"]


class SelectedFetchEnvelope(BaseModel):
    messages: list[SelectedFetchStatus]


def fetch_selected_messages(access_token: str, ids: list[str],
                            *, http_client: httpx.Client | None = None) -> list[RawSelectedMessage]:
    if not ids or len(ids) > MAX_SELECTED or len(ids) != len(set(ids)) or any(not ID_PATTERN.fullmatch(i) for i in ids):
        raise GmailSelectionError("Invalid selected message IDs")
    _, bearer = google_bearer(access_token)
    own = http_client is None
    client = http_client or httpx.Client(timeout=10.0, follow_redirects=False)
    try:
        label_id = selected_label_id(client, bearer)
        return fetch_selected_with_bearer(client, bearer, label_id, ids)
    finally:
        if own:
            client.close()


def fetch_selected_status(access_token: str, request: SelectedFetchInput) -> SelectedFetchEnvelope:
    messages = fetch_selected_messages(access_token, request.ids)
    return SelectedFetchEnvelope(messages=[SelectedFetchStatus(id=m.id, status=m.status) for m in messages])


def fetch_selected_with_bearer(client: httpx.Client, bearer: str, label_id: str, ids: list[str]) -> list[RawSelectedMessage]:
    results: list[RawSelectedMessage] = []
    for message_id in ids:
        url = GMAIL_ROOT + "/messages/" + quote(message_id, safe="")
        try:
            metadata = provider_json(client, url, bearer,
                [("format", "metadata"), ("metadataHeaders", "Subject"),
                 ("metadataHeaders", "From"), ("metadataHeaders", "Date")], max_bytes=65536)
            parse_metadata(metadata, message_id, label_id)
            full = provider_json(client, url, bearer, {"format": "full"},
                                 max_bytes=MAX_MESSAGE_BYTES)
            if full.get("id") != message_id or not isinstance(full.get("labelIds"), list) or label_id not in full["labelIds"]:
                raise GmailSelectionError("Selected message changed")
            results.append(RawSelectedMessage(message_id, "available", full, label_id))
        except GmailMessageGone:
            results.append(RawSelectedMessage(message_id, "unavailable", None, label_id))
    return results
