import base64
import json
import os
import unittest
from uuid import UUID, uuid4
from unittest.mock import patch

from focusos_api.token_crypto import TokenCipher, TokenCipherError


class TokenCipherTests(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(32)
        self.cipher = TokenCipher({1: self.key}, 1)
        self.connection_id = UUID("a4e0ce3a-c955-4b30-9d67-f47859cd38af")

    def test_encrypt_decrypt_uses_random_nonce_and_round_trips(self):
        first = self.cipher.encrypt(self.connection_id, "refresh", "secret-refresh")
        second = self.cipher.encrypt(self.connection_id, "refresh", "secret-refresh")
        self.assertNotEqual(first.ciphertext, second.ciphertext)
        self.assertEqual(first.key_version, 1)
        self.assertEqual(
            self.cipher.decrypt(self.connection_id, "refresh", first.ciphertext, 1),
            "secret-refresh",
        )

    def test_ciphertext_cannot_move_between_connections_or_token_types(self):
        encrypted = self.cipher.encrypt(self.connection_id, "access", "access-secret")
        with self.assertRaises(TokenCipherError):
            self.cipher.decrypt(uuid4(), "access", encrypted.ciphertext, 1)
        with self.assertRaises(TokenCipherError):
            self.cipher.decrypt(self.connection_id, "refresh", encrypted.ciphertext, 1)

    def test_tampering_and_unknown_key_version_fail_closed(self):
        encrypted = self.cipher.encrypt(self.connection_id, "refresh", "secret")
        tampered = encrypted.ciphertext[:-1] + bytes([encrypted.ciphertext[-1] ^ 1])
        with self.assertRaises(TokenCipherError):
            self.cipher.decrypt(self.connection_id, "refresh", tampered, 1)
        with self.assertRaises(TokenCipherError):
            self.cipher.decrypt(self.connection_id, "refresh", encrypted.ciphertext, 2)

    def test_keyring_reads_versioned_base64_keys_from_environment(self):
        values = {
            "FOCUSOS_TOKEN_ENCRYPTION_KEYS": json.dumps({"1": base64.b64encode(self.key).decode()}),
            "FOCUSOS_TOKEN_ENCRYPTION_ACTIVE_VERSION": "1",
        }
        with patch.dict(os.environ, values):
            cipher = TokenCipher.from_environment()
        encrypted = cipher.encrypt(self.connection_id, "access", "token")
        self.assertEqual(cipher.decrypt(self.connection_id, "access", encrypted.ciphertext, 1), "token")

    def test_keyring_can_decrypt_old_version_and_encrypt_with_active_version(self):
        old = TokenCipher({1: b"o" * 32}, 1)
        encrypted = old.encrypt(self.connection_id, "refresh", "refresh-secret")
        rotated = TokenCipher({1: b"o" * 32, 2: b"n" * 32}, 2)

        self.assertEqual(
            rotated.decrypt(self.connection_id, "refresh", encrypted.ciphertext, 1),
            "refresh-secret",
        )
        reencrypted = rotated.encrypt(self.connection_id, "refresh", "refresh-secret")
        self.assertEqual(reencrypted.key_version, 2)

    def test_missing_or_malformed_key_configuration_fails_closed(self):
        with patch.dict(os.environ, {"FOCUSOS_TOKEN_ENCRYPTION_KEYS": "{}", "FOCUSOS_TOKEN_ENCRYPTION_ACTIVE_VERSION": "1"}):
            with self.assertRaises(TokenCipherError):
                TokenCipher.from_environment()


if __name__ == "__main__":
    unittest.main()
