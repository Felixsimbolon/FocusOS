"""Google authorization-code exchange and encrypted credential persistence."""

import os
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from postgrest.exceptions import APIError

from focusos_api.connections import GoogleConnection, read_google_connection
from focusos_api.database import DatabaseUnavailable, InvalidSession, scoped_client, service_client
from focusos_api.google_token_store import SupabaseGoogleTokenStore
from focusos_api.token_crypto import TokenCipher, TokenCipherError

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
REQUIRED_SCOPES = frozenset({
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events.owned.readonly",
})


class GoogleOAuthError(Exception):
    """Safe provider or grant validation error."""


class GoogleOAuthUnavailable(GoogleOAuthError):
    """Provider or storage is temporarily unavailable."""


class GoogleAuthorizationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=8, max_length=4096)
    code_verifier: str = Field(pattern=r"^[A-Za-z0-9._~-]{43,128}$")
    redirect_uri: str = Field(min_length=1, max_length=512)


class GoogleTokenGrant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str = Field(min_length=1, max_length=16_384)
    refresh_token: str | None = Field(default=None, min_length=1, max_length=16_384)
    expires_in: int = Field(gt=0, le=86_400)
    scope: str = Field(min_length=1, max_length=4096)
    token_type: str = Field(min_length=1, max_length=32)


class GoogleUserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    email_verified: bool


class GoogleCredentialWriter(Protocol):
    def prepare(self, user_id: UUID, provider_subject: str, display_email: str) -> UUID: ...

    def store(
        self,
        connection_id: UUID,
        user_id: UUID,
        provider_subject: str,
        display_email: str,
        scopes: list[str],
        encrypted_refresh_token: bytes,
        encrypted_access_token: bytes,
        expires_at: datetime,
        key_version: int,
    ) -> GoogleConnection: ...

    def upgrade(
        self,
        connection_id: UUID,
        user_id: UUID,
        provider_subject: str,
        display_email: str,
        scopes: list[str],
        encrypted_refresh_token: bytes,
        encrypted_access_token: bytes,
        expires_at: datetime,
        key_version: int,
    ) -> GoogleConnection | None: ...


class SupabaseGoogleCredentialWriter:
    def prepare(self, user_id: UUID, provider_subject: str, display_email: str) -> UUID:
        try:
            with service_client() as client:
                data = client.rpc(
                    "focusos_prepare_google_connection",
                    {"p_user_id": str(user_id), "p_provider_subject": provider_subject,
                     "p_display_email": display_email},
                ).execute().data
        except (APIError, DatabaseUnavailable) as exc:
            raise GoogleOAuthUnavailable("Google connection setup is unavailable") from exc
        if isinstance(data, list) and len(data) == 1:
            data = data[0]
        try:
            value = data.get("connection_id") if isinstance(data, dict) else data
            return UUID(str(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise DatabaseUnavailable("Google connection setup returned an invalid result") from exc

    def store(
        self,
        connection_id: UUID,
        user_id: UUID,
        provider_subject: str,
        display_email: str,
        scopes: list[str],
        encrypted_refresh_token: bytes,
        encrypted_access_token: bytes,
        expires_at: datetime,
        key_version: int,
    ) -> GoogleConnection:
        params = {
            "p_connection_id": str(connection_id),
            "p_user_id": str(user_id),
            "p_provider_subject": provider_subject,
            "p_display_email": display_email,
            "p_granted_scopes": scopes,
            "p_encrypted_refresh_token": "\\x" + encrypted_refresh_token.hex(),
            "p_encrypted_access_token": "\\x" + encrypted_access_token.hex(),
            "p_access_token_expires_at": expires_at.isoformat(),
            "p_encryption_key_version": key_version,
        }
        try:
            with service_client() as client:
                data = client.rpc("focusos_store_google_credentials", params).execute().data
        except (APIError, DatabaseUnavailable) as exc:
            raise GoogleOAuthUnavailable("Google connection storage is unavailable") from exc

        if isinstance(data, list) and len(data) == 1:
            data = data[0]
        if not isinstance(data, dict):
            raise DatabaseUnavailable("Google connection storage returned an invalid result")
        try:
            return GoogleConnection.model_validate(data)
        except ValidationError as exc:
            raise DatabaseUnavailable("Google connection storage returned an invalid result") from exc


    def upgrade(
        self,
        connection_id: UUID,
        user_id: UUID,
        provider_subject: str,
        display_email: str,
        scopes: list[str],
        encrypted_refresh_token: bytes,
        encrypted_access_token: bytes,
        expires_at: datetime,
        key_version: int,
    ) -> GoogleConnection | None:
        params = {
            "p_connection_id": str(connection_id),
            "p_user_id": str(user_id),
            "p_provider_subject": provider_subject,
            "p_display_email": display_email,
            "p_granted_scopes": scopes,
            "p_encrypted_refresh_token": "\\x" + encrypted_refresh_token.hex(),
            "p_encrypted_access_token": "\\x" + encrypted_access_token.hex(),
            "p_access_token_expires_at": expires_at.isoformat(),
            "p_encryption_key_version": key_version,
        }
        try:
            with service_client() as client:
                data = client.rpc("focusos_upgrade_google_credentials", params).execute().data
        except (APIError, DatabaseUnavailable) as exc:
            raise GoogleOAuthUnavailable("Google Calendar permission update is unavailable") from exc
        if data is None or data == []:
            return None
        if isinstance(data, list) and len(data) == 1:
            data = data[0]
        if not isinstance(data, dict):
            raise DatabaseUnavailable("Google permission update returned an invalid result")
        try:
            return GoogleConnection.model_validate(data)
        except ValidationError as exc:
            raise DatabaseUnavailable("Google permission update returned an invalid result") from exc


def _google_client_settings() -> tuple[str, str, frozenset[str]]:
    client_id = os.environ.get("FOCUSOS_GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("FOCUSOS_GOOGLE_CLIENT_SECRET", "").strip()
    configured = os.environ.get("FOCUSOS_GOOGLE_REDIRECT_URIS", "")
    redirect_uris = frozenset(uri.strip() for uri in configured.split(",") if uri.strip())
    if not client_id or not client_secret or not redirect_uris:
        raise GoogleOAuthUnavailable("Google OAuth server configuration is missing")
    return client_id, client_secret, redirect_uris


def complete_google_authorization(
    access_token: str,
    request: GoogleAuthorizationInput,
    *,
    writer: GoogleCredentialWriter | None = None,
    http_client: httpx.Client | None = None,
    now: datetime | None = None,
) -> GoogleConnection:
    # Validate the Supabase token and derive owner identity only from verified Auth.
    with scoped_client(access_token) as (owner_id, _supabase):
        try:
            user_id = UUID(owner_id)
        except ValueError as exc:
            raise InvalidSession() from exc

    client_id, client_secret, redirect_uris = _google_client_settings()
    if request.redirect_uri not in redirect_uris:
        raise GoogleOAuthError("Google callback URL is not allowed")

    own_client = http_client is None
    client = http_client or httpx.Client(timeout=10.0, follow_redirects=False)
    try:
        try:
            response = client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": request.code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code_verifier": request.code_verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": request.redirect_uri,
                },
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise GoogleOAuthUnavailable("Google token exchange is unavailable") from exc
        if response.status_code != 200:
            raise GoogleOAuthError("Google authorization code was rejected")
        try:
            grant = GoogleTokenGrant.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise GoogleOAuthError("Google token response was invalid") from exc

        granted_scopes = frozenset(grant.scope.split())
        if not REQUIRED_SCOPES.issubset(granted_scopes) or grant.token_type.lower() != "bearer":
            raise GoogleOAuthError("Google did not grant the required read permissions")

        try:
            identity_response = client.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={"Authorization": "Bearer " + grant.access_token},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise GoogleOAuthUnavailable("Google identity check is unavailable") from exc
        if identity_response.status_code != 200:
            raise GoogleOAuthError("Google identity could not be verified")
        try:
            identity = GoogleUserInfo.model_validate(identity_response.json())
        except (ValidationError, ValueError) as exc:
            raise GoogleOAuthError("Google identity response was invalid") from exc
        if not identity.email_verified:
            raise GoogleOAuthError("Google account email is not verified")

        if not grant.refresh_token:
            raise GoogleOAuthError("Google did not issue offline access")
        credential_writer = writer or SupabaseGoogleCredentialWriter()
        connection_id = credential_writer.prepare(user_id, identity.sub, identity.email)
        try:
            cipher = TokenCipher.from_environment()
            encrypted_refresh = cipher.encrypt(connection_id, "refresh", grant.refresh_token)
            encrypted_access = cipher.encrypt(connection_id, "access", grant.access_token)
        except TokenCipherError as exc:
            raise GoogleOAuthUnavailable("Google token encryption is not configured") from exc

        expires_at = (now or datetime.now(timezone.utc)) + timedelta(seconds=grant.expires_in)
        return credential_writer.store(
            connection_id=connection_id,
            user_id=user_id,
            provider_subject=identity.sub,
            display_email=identity.email,
            scopes=sorted(granted_scopes),
            encrypted_refresh_token=encrypted_refresh.ciphertext,
            encrypted_access_token=encrypted_access.ciphertext,
            expires_at=expires_at,
            key_version=encrypted_refresh.key_version,
        )
    finally:
        if own_client:
            client.close()


GOOGLE_CALENDAR_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
CALENDAR_WRITE_SCOPES = frozenset({*REQUIRED_SCOPES, GOOGLE_CALENDAR_WRITE_SCOPE})


def complete_calendar_write_upgrade(
    access_token: str,
    request: GoogleAuthorizationInput,
    *,
    writer: GoogleCredentialWriter | None = None,
    http_client: httpx.Client | None = None,
    now: datetime | None = None,
) -> GoogleConnection:
    with scoped_client(access_token) as (owner_id, _supabase):
        try:
            user_id = UUID(owner_id)
        except ValueError as exc:
            raise InvalidSession() from exc

    connection = read_google_connection(access_token)
    if connection is None or connection.status != "connected":
        raise GoogleOAuthError("Connect Google before upgrading Calendar permissions")
    if not REQUIRED_SCOPES.issubset(set(connection.granted_scopes)):
        raise GoogleOAuthError("Existing Google read permissions are incomplete")

    client_id, client_secret, redirect_uris = _google_client_settings()
    if request.redirect_uri not in redirect_uris:
        raise GoogleOAuthError("Google callback URL is not allowed")

    own_client = http_client is None
    client = http_client or httpx.Client(timeout=10.0, follow_redirects=False)
    try:
        try:
            response = client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": request.code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code_verifier": request.code_verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": request.redirect_uri,
                },
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise GoogleOAuthUnavailable("Google token exchange is unavailable") from exc
        if response.status_code != 200:
            raise GoogleOAuthError("Google authorization code was rejected")
        try:
            grant = GoogleTokenGrant.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise GoogleOAuthError("Google token response was invalid") from exc
        granted_scopes = frozenset(grant.scope.split())
        if not CALENDAR_WRITE_SCOPES.issubset(granted_scopes) or grant.token_type.lower() != "bearer":
            raise GoogleOAuthError("Google did not grant the Calendar write permission")

        try:
            identity_response = client.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={"Authorization": "Bearer " + grant.access_token},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise GoogleOAuthUnavailable("Google identity check is unavailable") from exc
        if identity_response.status_code != 200:
            raise GoogleOAuthError("Google identity could not be verified")
        try:
            identity = GoogleUserInfo.model_validate(identity_response.json())
        except (ValidationError, ValueError) as exc:
            raise GoogleOAuthError("Google identity response was invalid") from exc
        if not identity.email_verified:
            raise GoogleOAuthError("Google account email is not verified")

        token_store = SupabaseGoogleTokenStore()
        stored = token_store.read(connection.id)
        if stored is None or stored.status != "connected":
            raise GoogleOAuthError("Google connection needs authorization")
        try:
            cipher = TokenCipher.from_environment()
            refresh_token = grant.refresh_token
            if refresh_token is None:
                old_refresh = cipher.decrypt(
                    connection.id, "refresh", stored.encrypted_refresh_token,
                    stored.encryption_key_version,
                )
                refresh_token = old_refresh
            encrypted_refresh = cipher.encrypt(connection.id, "refresh", refresh_token)
            encrypted_access = cipher.encrypt(connection.id, "access", grant.access_token)
        except TokenCipherError as exc:
            raise GoogleOAuthUnavailable("Google token encryption is not configured") from exc

        expires_at = (now or datetime.now(timezone.utc)) + timedelta(seconds=grant.expires_in)
        result = (writer or SupabaseGoogleCredentialWriter()).upgrade(
            connection_id=connection.id,
            user_id=user_id,
            provider_subject=identity.sub,
            display_email=identity.email,
            scopes=sorted(granted_scopes),
            encrypted_refresh_token=encrypted_refresh.ciphertext,
            encrypted_access_token=encrypted_access.ciphertext,
            expires_at=expires_at,
            key_version=encrypted_refresh.key_version,
        )
        if result is None:
            raise GoogleOAuthError("Google account does not match the connected account")
        return result
    finally:
        if own_client:
            client.close()
