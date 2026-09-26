"""Bounded Gmail metadata discovery for one explicit user label."""
from datetime import datetime
import re
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from focusos_api.connections import read_google_connection
from focusos_api.database import DatabaseUnavailable
from focusos_api.google_gmail import GMAIL_READ_SCOPE
from focusos_api.google_token_store import SupabaseGoogleTokenStore
from focusos_api.google_tokens import (GoogleOAuthClient, GoogleReconnectRequired,
    GoogleRefreshInProgress, GoogleTokenError, GoogleTokenProviderUnavailable,
    get_google_access_token)
from focusos_api.token_crypto import TokenCipher, TokenCipherError

GMAIL_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
SELECTED_LABEL = "FocusOS"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class GmailSelectionError(Exception):
    pass


class GmailSelectionMissing(GmailSelectionError):
    pass


class GmailSelectionReconnect(GmailSelectionError):
    pass


class GmailSelectionUnavailable(GmailSelectionError):
    def __init__(self, retry_after: int | None = None):
        self.retry_after = retry_after
        super().__init__("Gmail temporarily unavailable")


class GmailMessageGone(GmailSelectionError):
    pass


class GmailMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    thread_id: str
    history_id: str | None
    internal_date_ms: int | None
    subject: str
    sender: str
    label_ids: list[str]


class GmailSelectedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label_id: str
    items: list[GmailMetadata] = Field(max_length=10)
    next_page_token: str | None
    result_size_estimate: int | None


def google_bearer(access_token: str):
    connection = read_google_connection(access_token)
    if connection is None or connection.status != "connected" or GMAIL_READ_SCOPE not in connection.granted_scopes:
        raise GmailSelectionReconnect()
    try:
        bearer = get_google_access_token(connection.id, SupabaseGoogleTokenStore(),
            TokenCipher.from_environment(), GoogleOAuthClient.from_environment())
    except GoogleReconnectRequired as exc:
        raise GmailSelectionReconnect() from exc
    except (GoogleRefreshInProgress, GoogleTokenProviderUnavailable, GoogleTokenError,
            TokenCipherError, DatabaseUnavailable) as exc:
        raise GmailSelectionUnavailable() from exc
    return connection, bearer


def provider_json(client: httpx.Client, url: str, bearer: str, params: dict | list | None = None) -> dict:
    try:
        response = client.get(url, params=params, headers={"Authorization": "Bearer " + bearer},
                              timeout=10.0)
    except httpx.HTTPError as exc:
        raise GmailSelectionUnavailable() from exc
    if response.status_code == 401:
        raise GmailSelectionReconnect()
    if response.status_code == 404:
        raise GmailMessageGone()
    if response.status_code in (429, 500, 502, 503, 504):
        retry = response.headers.get("Retry-After")
        retry_seconds = min(int(retry), 3600) if retry and retry.isdigit() else None
        raise GmailSelectionUnavailable(retry_seconds)
    if response.status_code == 403:
        raise GmailSelectionUnavailable()
    if response.status_code != 200 or len(response.content) > 2097152:
        raise GmailSelectionError("Unexpected Gmail response")
    try:
        data = response.json()
    except ValueError as exc:
        raise GmailSelectionError("Invalid Gmail response") from exc
    if not isinstance(data, dict):
        raise GmailSelectionError("Invalid Gmail response")
    return data


def selected_label_id(client: httpx.Client, bearer: str) -> str:
    data = provider_json(client, GMAIL_ROOT + "/labels", bearer)
    labels = data.get("labels", [])
    if not isinstance(labels, list):
        raise GmailSelectionError("Invalid label response")
    for label in labels:
        if isinstance(label, dict) and label.get("name") == SELECTED_LABEL and label.get("type") == "user":
            label_id = label.get("id")
            if isinstance(label_id, str) and ID_PATTERN.fullmatch(label_id):
                return label_id
    raise GmailSelectionMissing()


def parse_metadata(data: dict, expected_id: str, label_id: str) -> GmailMetadata:
    if data.get("id") != expected_id or not isinstance(data.get("labelIds"), list) or label_id not in data["labelIds"]:
        raise GmailSelectionError("Selected message changed")
    payload = data.get("payload")
    headers = payload.get("headers") if isinstance(payload, dict) else None
    if not isinstance(headers, list):
        raise GmailSelectionError("Invalid metadata response")
    def header(name: str) -> str:
        for item in headers:
            if isinstance(item, dict) and str(item.get("name", "")).lower() == name.lower():
                value = item.get("value")
                return value[:300] if isinstance(value, str) else ""
        return ""
    thread = data.get("threadId")
    history = data.get("historyId")
    internal = data.get("internalDate")
    labels = data.get("labelIds")
    if not isinstance(thread, str) or not ID_PATTERN.fullmatch(thread) or not isinstance(labels, list):
        raise GmailSelectionError("Invalid metadata response")
    try:
        timestamp = int(internal) if internal is not None else None
    except (TypeError, ValueError) as exc:
        raise GmailSelectionError("Invalid message timestamp") from exc
    return GmailMetadata(id=expected_id, thread_id=thread,
        history_id=str(history) if history is not None else None,
        internal_date_ms=timestamp, subject=header("Subject"), sender=header("From"),
        label_ids=[str(item) for item in labels if isinstance(item, str)][:20])


def list_selected_metadata(access_token: str, page_token: str | None = None,
                           *, http_client: httpx.Client | None = None) -> GmailSelectedPage:
    if page_token is not None and (len(page_token) > 1024 or not re.fullmatch(r"[A-Za-z0-9_=-]+", page_token)):
        raise GmailSelectionError("Invalid page token")
    _, bearer = google_bearer(access_token)
    own = http_client is None
    client = http_client or httpx.Client(timeout=10.0, follow_redirects=False)
    try:
        label_id = selected_label_id(client, bearer)
        params = {"labelIds": label_id, "maxResults": 10, "includeSpamTrash": "false"}
        if page_token:
            params["pageToken"] = page_token
        listing = provider_json(client, GMAIL_ROOT + "/messages", bearer, params)
        messages = listing.get("messages", [])
        if not isinstance(messages, list) or len(messages) > 10:
            raise GmailSelectionError("Invalid message list")
        items = []
        for item in messages:
            message_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(message_id, str) or not ID_PATTERN.fullmatch(message_id):
                raise GmailSelectionError("Invalid message ID")
            detail = provider_json(client, GMAIL_ROOT + "/messages/" + quote(message_id, safe=""),
                bearer, [("format", "metadata"), ("metadataHeaders", "Subject"),
                         ("metadataHeaders", "From"), ("metadataHeaders", "Date")])
            items.append(parse_metadata(detail, message_id, label_id))
        next_token = listing.get("nextPageToken")
        if next_token is not None and (not isinstance(next_token, str) or len(next_token) > 1024 or not re.fullmatch(r"[A-Za-z0-9_=-]+", next_token)):
            raise GmailSelectionError("Invalid page token")
        estimate = listing.get("resultSizeEstimate")
        return GmailSelectedPage(label_id=label_id, items=items,
            next_page_token=next_token, result_size_estimate=estimate if isinstance(estimate, int) else None)
    finally:
        if own:
            client.close()
