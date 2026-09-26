"""Service-only Supabase RPC adapter for encrypted Google credentials."""

from uuid import UUID

from postgrest.exceptions import APIError

from focusos_api.database import DatabaseUnavailable, service_client
from focusos_api.google_tokens import GoogleTokenStore, StoredGoogleCredentials


def _decode_bytea(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str) and value.startswith("\\x"):
        try:
            return bytes.fromhex(value[2:])
        except ValueError as exc:
            raise DatabaseUnavailable("Encrypted credential response was invalid") from exc
    raise DatabaseUnavailable("Encrypted credential response was invalid")


def _one_row(value: object) -> dict[str, object] | None:
    if value is None or value == []:
        return None
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    raise DatabaseUnavailable("Credential operation returned an unexpected result")


class SupabaseGoogleTokenStore(GoogleTokenStore):
    def read(self, connection_id: UUID) -> StoredGoogleCredentials | None:
        try:
            with service_client() as client:
                row = _one_row(
                    client.rpc(
                        "focusos_read_google_credentials",
                        {"p_connection_id": str(connection_id)},
                    ).execute().data
                )
        except APIError as exc:
            raise DatabaseUnavailable("Credential operation failed") from exc
        if row is None:
            return None
        return _credentials(row)

    def claim(self, connection_id: UUID, expected_version: int, lease_id: UUID, lease_seconds: int) -> StoredGoogleCredentials | None:
        try:
            with service_client() as client:
                row = _one_row(
                    client.rpc(
                        "focusos_claim_google_refresh",
                        {
                            "p_connection_id": str(connection_id),
                            "p_expected_token_version": expected_version,
                            "p_lease_id": str(lease_id),
                            "p_lease_seconds": lease_seconds,
                        },
                    ).execute().data
                )
        except APIError as exc:
            raise DatabaseUnavailable("Credential operation failed") from exc
        return _credentials(row) if row else None

    def save(
        self,
        connection_id: UUID,
        expected_version: int,
        lease_id: UUID,
        encrypted_access_token: bytes,
        encrypted_refresh_token: bytes,
        expires_at,
        key_version: int,
    ) -> bool:
        result = self._rpc(
            "focusos_save_google_refresh",
            {
                "p_connection_id": str(connection_id),
                "p_expected_token_version": expected_version,
                "p_lease_id": str(lease_id),
                "p_encrypted_access_token": "\\x" + encrypted_access_token.hex(),
                "p_encrypted_refresh_token": "\\x" + encrypted_refresh_token.hex(),
                "p_access_token_expires_at": expires_at.isoformat(),
                "p_encryption_key_version": key_version,
            },
        )
        return result is True or result == [True]

    def mark_reconnect_required(self, connection_id: UUID, lease_id: UUID) -> None:
        self._rpc(
            "focusos_mark_google_reconnect_required",
            {"p_connection_id": str(connection_id), "p_lease_id": str(lease_id)},
        )

    def release(self, connection_id: UUID, lease_id: UUID) -> None:
        self._rpc(
            "focusos_release_google_refresh",
            {"p_connection_id": str(connection_id), "p_lease_id": str(lease_id)},
        )

    @staticmethod
    def _rpc(name: str, params: dict[str, object]) -> object:
        try:
            with service_client() as client:
                return client.rpc(name, params).execute().data
        except APIError as exc:
            raise DatabaseUnavailable("Credential operation failed") from exc


def _credentials(row: dict[str, object]) -> StoredGoogleCredentials:
    try:
        return StoredGoogleCredentials(
            connection_id=row["connection_id"],
            status=row["status"],
            encrypted_refresh_token=_decode_bytea(row["encrypted_refresh_token"]),
            encrypted_access_token=(
                _decode_bytea(row["encrypted_access_token"])
                if row.get("encrypted_access_token") is not None
                else None
            ),
            access_token_expires_at=row.get("access_token_expires_at"),
            encryption_key_version=row["encryption_key_version"],
            token_version=row["token_version"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DatabaseUnavailable("Credential operation returned an unexpected result") from exc
