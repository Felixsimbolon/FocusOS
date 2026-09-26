"""Expiry-aware Google access-token refresh with versioned leases."""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from focusos_api.token_crypto import TokenCipher


GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REFRESH_EARLY_SECONDS = 60
REFRESH_LEASE_SECONDS = 30


class StoredGoogleCredentials(BaseModel):
    connection_id: UUID
    encrypted_refresh_token: bytes
    encrypted_access_token: bytes | None
    access_token_expires_at: datetime | None
    encryption_key_version: int
    token_version: int
    status: str = "connected"


class GoogleTokenStore(Protocol):
    def read(self, connection_id: UUID) -> StoredGoogleCredentials | None: ...
    def claim(
        self, connection_id: UUID, expected_version: int, lease_id: UUID, lease_seconds: int
    ) -> StoredGoogleCredentials | None: ...
    def save(
        self,
        connection_id: UUID,
        expected_version: int,
        lease_id: UUID,
        encrypted_access_token: bytes,
        encrypted_refresh_token: bytes,
        expires_at: datetime,
        key_version: int,
    ) -> bool: ...
    def mark_reconnect_required(self, connection_id: UUID, lease_id: UUID) -> None: ...
    def release(self, connection_id: UUID, lease_id: UUID) -> None: ...


class GoogleTokenError(Exception):
    """Safe token lifecycle failure."""


class GoogleReconnectRequired(GoogleTokenError):
    """Google revoked or invalidated the refresh grant."""


class GoogleRefreshInProgress(GoogleTokenError):
    """Another request already owns the refresh lease."""


class GoogleTokenProviderUnavailable(GoogleTokenError):
    """Google could not refresh the token for a retryable reason."""


class GoogleTokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str = Field(min_length=1, max_length=16_384)
    expires_in: int = Field(gt=0, le=86_400)
    refresh_token: str | None = Field(default=None, min_length=1, max_length=16_384)


@dataclass(frozen=True)
class GoogleOAuthClient:
    client_id: str
    client_secret: str

    @classmethod
    def from_environment(cls) -> "GoogleOAuthClient":
        client_id = os.environ.get("FOCUSOS_GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("FOCUSOS_GOOGLE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise GoogleTokenError("Google OAuth server configuration is missing")
        return cls(client_id, client_secret)


def get_google_access_token(
    connection_id: UUID,
    store: GoogleTokenStore,
    cipher: TokenCipher,
    oauth_client: GoogleOAuthClient,
    *,
    http_client: httpx.Client | None = None,
    now: datetime | None = None,
) -> str:
    current_time = _utc(now or datetime.now(timezone.utc))
    stored = store.read(connection_id)
    if stored is None:
        raise GoogleReconnectRequired("Google connection needs authorization")
    if stored.status != "connected":
        raise GoogleReconnectRequired("Google connection needs authorization")
    if stored.encrypted_access_token and stored.access_token_expires_at:
        if _utc(stored.access_token_expires_at) > current_time + timedelta(seconds=REFRESH_EARLY_SECONDS):
            return cipher.decrypt(
                connection_id, "access", stored.encrypted_access_token, stored.encryption_key_version
            )

    lease_id = uuid4()
    claimed = store.claim(connection_id, stored.token_version, lease_id, REFRESH_LEASE_SECONDS)
    if claimed is None:
        raise GoogleRefreshInProgress("Google token refresh is already in progress")

    successful = False
    try:
        refresh_token = cipher.decrypt(
            connection_id, "refresh", claimed.encrypted_refresh_token, claimed.encryption_key_version
        )
        own_client = http_client is None
        client = http_client or httpx.Client(timeout=10.0)
        try:
            response = client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": oauth_client.client_id,
                    "client_secret": oauth_client.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=10.0,
            )
        finally:
            if own_client:
                client.close()

        if response.status_code >= 400:
            _raise_provider_error(response, store, connection_id, lease_id)
        try:
            result = GoogleTokenResponse.model_validate(response.json())
        except (ValueError, TypeError, ValidationError) as exc:
            raise GoogleTokenProviderUnavailable("Google returned an invalid token response") from exc

        next_refresh_token = result.refresh_token or refresh_token
        encrypted_access = cipher.encrypt(connection_id, "access", result.access_token)
        encrypted_refresh = cipher.encrypt(connection_id, "refresh", next_refresh_token)
        expires_at = current_time + timedelta(seconds=result.expires_in)
        if encrypted_access.key_version != encrypted_refresh.key_version:
            raise GoogleTokenError("Token encryption key changed during refresh")
        saved = store.save(
            connection_id,
            claimed.token_version,
            lease_id,
            encrypted_access.ciphertext,
            encrypted_refresh.ciphertext,
            expires_at,
            encrypted_access.key_version,
        )
        if not saved:
            raise GoogleRefreshInProgress("Google token refresh lost its lease")
        successful = True
        return result.access_token
    except GoogleReconnectRequired:
        raise
    except GoogleTokenError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise GoogleTokenProviderUnavailable("Google token refresh failed") from exc
    finally:
        if not successful:
            store.release(connection_id, lease_id)


def _raise_provider_error(
    response: httpx.Response,
    store: GoogleTokenStore,
    connection_id: UUID,
    lease_id: UUID,
) -> None:
    try:
        error_code = response.json().get("error")
    except (ValueError, AttributeError):
        error_code = None
    if error_code == "invalid_grant":
        store.mark_reconnect_required(connection_id, lease_id)
        raise GoogleReconnectRequired("Google connection needs authorization")
    raise GoogleTokenProviderUnavailable("Google token refresh failed")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise GoogleTokenError("Token expiration must include a timezone")
    return value.astimezone(timezone.utc)
