"""Read one user-selected Gmail message for an in-memory diagnostic only."""

import base64
import binascii
import re
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict

from focusos_api.connections import read_google_connection
from focusos_api.database import DatabaseUnavailable
from focusos_api.google_token_store import SupabaseGoogleTokenStore
from focusos_api.google_tokens import (
    GoogleOAuthClient,
    GoogleReconnectRequired,
    GoogleRefreshInProgress,
    GoogleTokenError,
    GoogleTokenProviderUnavailable,
    get_google_access_token,
)
from focusos_api.token_crypto import TokenCipher, TokenCipherError

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class GmailProbeError(Exception):
    """A safe Gmail probe failure."""


class GmailProbeUnavailable(GmailProbeError):
    """A provider or local dependency is temporarily unavailable."""


class GmailReconnectRequired(GmailProbeError):
    """The Google grant must be authorized again."""


class GmailMessageProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    internal_date_ms: int | None
    label_count: int
    text_body_bytes: int


def read_selected_gmail_message(
    access_token: str,
    message_id: str,
    *,
    http_client: httpx.Client | None = None,
) -> GmailMessageProbe:
    if not _MESSAGE_ID.fullmatch(message_id):
        raise GmailProbeError("Gmail message ID is invalid")

    connection = read_google_connection(access_token)
    if connection is None or connection.status != "connected":
        raise GmailReconnectRequired("Google connection needs authorization")
    if GMAIL_READ_SCOPE not in connection.granted_scopes:
        raise GmailReconnectRequired("Gmail read permission is missing")

    try:
        cipher = TokenCipher.from_environment()
        oauth_client = GoogleOAuthClient.from_environment()
    except (TokenCipherError, GoogleTokenError) as exc:
        raise GmailProbeUnavailable("Google token configuration is unavailable") from exc

    try:
        bearer = get_google_access_token(
            connection.id, SupabaseGoogleTokenStore(), cipher, oauth_client
        )
    except GoogleReconnectRequired as exc:
        raise GmailReconnectRequired("Google connection needs authorization") from exc
    except GoogleRefreshInProgress as exc:
        raise GmailProbeUnavailable("Google token refresh is already in progress") from exc
    except (GoogleTokenProviderUnavailable, DatabaseUnavailable, GoogleTokenError) as exc:
        raise GmailProbeUnavailable("Google token is temporarily unavailable") from exc

    own_client = http_client is None
    client = http_client or httpx.Client(timeout=10.0, follow_redirects=False)
    try:
        try:
            response = client.get(
                GMAIL_API + quote(message_id, safe=""),
                params={"format": "full"},
                headers={"Authorization": "Bearer " + bearer},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise GmailProbeUnavailable("Gmail is temporarily unavailable") from exc
        if response.status_code == 401:
            raise GmailReconnectRequired("Google connection needs authorization")
        if response.status_code != 200:
            raise GmailProbeError("Gmail could not read the selected message")
        try:
            message = response.json()
        except ValueError as exc:
            raise GmailProbeError("Gmail returned an invalid message response") from exc
        if not isinstance(message, dict) or message.get("id") != message_id:
            raise GmailProbeError("Gmail returned an unexpected message")
        labels = message.get("labelIds", [])
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            raise GmailProbeError("Gmail returned invalid message metadata")
        internal_date = message.get("internalDate")
        try:
            internal_date_ms = int(internal_date) if internal_date is not None else None
        except (TypeError, ValueError) as exc:
            raise GmailProbeError("Gmail returned invalid message metadata") from exc
        body_bytes = _text_body_bytes(message.get("payload"))
        return GmailMessageProbe(
            message_id=message_id,
            internal_date_ms=internal_date_ms,
            label_count=len(labels),
            text_body_bytes=body_bytes,
        )
    finally:
        if own_client:
            client.close()


def _text_body_bytes(payload: Any) -> int:
    """Decode text/plain into a short-lived local value, returning only its byte count."""
    if not isinstance(payload, dict):
        return 0
    mime_type = payload.get("mimeType")
    body = payload.get("body")
    if mime_type == "text/plain" and isinstance(body, dict):
        encoded = body.get("data")
        if isinstance(encoded, str):
            try:
                compact = encoded.replace("-", "+").replace("_", "/")
                raw = base64.b64decode(compact + "=" * (-len(compact) % 4), validate=True)
                return len(raw)
            except (binascii.Error, ValueError) as exc:
                raise GmailProbeError("Gmail returned invalid message content") from exc
    parts = payload.get("parts", [])
    if isinstance(parts, list):
        for part in parts:
            length = _text_body_bytes(part)
            if length:
                return length
    return 0
