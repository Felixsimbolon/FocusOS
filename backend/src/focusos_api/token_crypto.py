"""Versioned AES-GCM encryption for server-only Google OAuth tokens."""

import base64
import binascii
import json
import os
from dataclasses import dataclass
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12
MAX_TOKEN_BYTES = 16_384


class TokenCipherError(Exception):
    """Configuration, ciphertext, or authentication failure without secret detail."""


@dataclass(frozen=True)
class EncryptedToken:
    ciphertext: bytes
    key_version: int


class TokenCipher:
    def __init__(self, keys: dict[int, bytes], active_version: int) -> None:
        if not keys or active_version not in keys:
            raise TokenCipherError("Active token encryption key is unavailable")
        if any(version < 1 or len(key) != 32 for version, key in keys.items()):
            raise TokenCipherError("Token encryption keys must be versioned 256-bit keys")
        self._keys = dict(keys)
        self._active_version = active_version

    @classmethod
    def from_environment(cls) -> "TokenCipher":
        serialized = os.environ.get("FOCUSOS_TOKEN_ENCRYPTION_KEYS", "")
        active = os.environ.get("FOCUSOS_TOKEN_ENCRYPTION_ACTIVE_VERSION", "")
        try:
            parsed = json.loads(serialized)
            active_version = int(active)
            if not isinstance(parsed, dict):
                raise ValueError
            keys = {
                int(version): base64.b64decode(value, validate=True)
                for version, value in parsed.items()
            }
        except (ValueError, TypeError, binascii.Error, json.JSONDecodeError) as exc:
            raise TokenCipherError("Token encryption configuration is invalid") from exc
        return cls(keys, active_version)

    def encrypt(self, connection_id: UUID, token_kind: str, token: str) -> EncryptedToken:
        if token_kind not in {"access", "refresh"} or not token:
            raise TokenCipherError("Token value is invalid")
        plaintext = token.encode("utf-8")
        if len(plaintext) > MAX_TOKEN_BYTES:
            raise TokenCipherError("Token value is too large")
        nonce = os.urandom(NONCE_BYTES)
        version = self._active_version
        aad = _associated_data(connection_id, token_kind, version)
        ciphertext = AESGCM(self._keys[version]).encrypt(nonce, plaintext, aad)
        return EncryptedToken(nonce + ciphertext, version)

    def decrypt(
        self,
        connection_id: UUID,
        token_kind: str,
        encrypted: bytes,
        key_version: int,
    ) -> str:
        if token_kind not in {"access", "refresh"} or key_version not in self._keys:
            raise TokenCipherError("Encrypted token cannot be opened")
        if len(encrypted) < NONCE_BYTES + 16 or len(encrypted) > MAX_TOKEN_BYTES + NONCE_BYTES + 16:
            raise TokenCipherError("Encrypted token cannot be opened")
        nonce, ciphertext = encrypted[:NONCE_BYTES], encrypted[NONCE_BYTES:]
        try:
            plaintext = AESGCM(self._keys[key_version]).decrypt(
                nonce,
                ciphertext,
                _associated_data(connection_id, token_kind, key_version),
            )
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise TokenCipherError("Encrypted token authentication failed") from exc


def _associated_data(connection_id: UUID, token_kind: str, version: int) -> bytes:
    return f"focusos:oauth:{connection_id}:{token_kind}:v{version}".encode("ascii")
