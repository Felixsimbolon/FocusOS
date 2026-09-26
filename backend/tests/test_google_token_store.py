import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from focusos_api.database import DatabaseUnavailable
from focusos_api.google_token_store import SupabaseGoogleTokenStore


CONNECTION_ID = UUID("a4e0ce3a-c955-4b30-9d67-f47859cd38af")


class GoogleTokenStoreTests(unittest.TestCase):
    def test_read_decodes_ciphertext_and_returns_only_private_credential_dto(self):
        client = Mock()
        client.rpc.return_value.execute.return_value.data = [{
            "connection_id": str(CONNECTION_ID),
            "status": "connected",
            "encrypted_refresh_token": "\\x" + (b"r" * 28).hex(),
            "encrypted_access_token": "\\x" + (b"a" * 28).hex(),
            "access_token_expires_at": "2026-09-26T13:00:00+00:00",
            "encryption_key_version": 2,
            "token_version": 7,
        }]
        with patch("focusos_api.google_token_store.service_client") as context:
            context.return_value.__enter__.return_value = client
            stored = SupabaseGoogleTokenStore().read(CONNECTION_ID)

        self.assertEqual(stored.connection_id, CONNECTION_ID)
        self.assertEqual(stored.encrypted_refresh_token, b"r" * 28)
        self.assertEqual(stored.encrypted_access_token, b"a" * 28)
        self.assertEqual(stored.token_version, 7)
        client.rpc.assert_called_once_with(
            "focusos_read_google_credentials",
            {"p_connection_id": str(CONNECTION_ID)},
        )

    def test_claim_with_no_returned_row_means_another_refresh_owns_lease(self):
        client = Mock()
        client.rpc.return_value.execute.return_value.data = []
        lease_id = uuid4()
        with patch("focusos_api.google_token_store.service_client") as context:
            context.return_value.__enter__.return_value = client
            claimed = SupabaseGoogleTokenStore().claim(CONNECTION_ID, 4, lease_id, 30)
        self.assertIsNone(claimed)

    def test_save_sends_bytea_in_postgres_hex_format(self):
        client = Mock()
        client.rpc.return_value.execute.return_value.data = True
        lease_id = uuid4()
        expires = datetime(2026, 9, 26, 13, tzinfo=timezone.utc)
        with patch("focusos_api.google_token_store.service_client") as context:
            context.return_value.__enter__.return_value = client
            result = SupabaseGoogleTokenStore().save(
                CONNECTION_ID, 4, lease_id, b"access-ciphertext", b"refresh-ciphertext", expires, 2
            )
        self.assertTrue(result)
        name, params = client.rpc.call_args.args
        self.assertEqual(name, "focusos_save_google_refresh")
        self.assertEqual(params["p_encrypted_access_token"], "\\x" + b"access-ciphertext".hex())
        self.assertEqual(params["p_encrypted_refresh_token"], "\\x" + b"refresh-ciphertext".hex())


if __name__ == "__main__":
    unittest.main()
