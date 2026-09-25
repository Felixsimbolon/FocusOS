import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from focusos_api.database import DatabaseUnavailable, InvalidSession, check_database_identity
from focusos_api.main import app


class DatabaseIdentityTests(unittest.TestCase):
    def test_user_jwt_is_scoped_to_the_postgrest_request(self):
        token = "user-access-token"
        settings = {
            "FOCUSOS_SUPABASE_URL": "https://example.supabase.co",
            "FOCUSOS_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
        }
        with patch.dict(os.environ, settings), patch(
            "focusos_api.database.httpx.Client"
        ) as transport_factory, patch("focusos_api.database.create_client") as create_client:
            client = create_client.return_value
            client.auth.get_user.return_value.user.id = "user-123"
            client.rpc.return_value.execute.return_value.data = "user-123"

            check_database_identity(token)

            create_client.assert_called_once()
            self.assertIs(
                create_client.call_args.kwargs["options"].httpx_client,
                transport_factory.return_value.__enter__.return_value,
            )
            client.auth.get_user.assert_called_once_with(token)
            client.postgrest.auth.assert_called_once_with(token)
            client.rpc.assert_called_once_with("focusos_session_uid", get=True)

    def test_identity_mismatch_fails_closed(self):
        settings = {
            "FOCUSOS_SUPABASE_URL": "https://example.supabase.co",
            "FOCUSOS_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
        }
        with patch.dict(os.environ, settings), patch(
            "focusos_api.database.httpx.Client"
        ), patch("focusos_api.database.create_client") as create_client:
            client = create_client.return_value
            client.auth.get_user.return_value.user.id = "user-123"
            client.rpc.return_value.execute.return_value.data = "user-456"

            with self.assertRaises(DatabaseUnavailable):
                check_database_identity("user-access-token")

    def test_secret_key_is_rejected_before_client_creation(self):
        settings = {
            "FOCUSOS_SUPABASE_URL": "https://example.supabase.co",
            "FOCUSOS_SUPABASE_PUBLISHABLE_KEY": "sb_secret_do_not_use",
        }
        with patch.dict(os.environ, settings), patch(
            "focusos_api.database.create_client"
        ) as create_client:
            with self.assertRaises(DatabaseUnavailable):
                check_database_identity("user-access-token")

            create_client.assert_not_called()

    def test_missing_token_is_rejected(self):
        with self.assertRaises(InvalidSession):
            check_database_identity("")


class DatabaseHealthRouteTests(unittest.TestCase):
    def test_anonymous_request_is_rejected_before_database_access(self):
        with patch("focusos_api.main.check_database_identity") as check:
            with TestClient(app) as client:
                response = client.get("/health/database")

        self.assertEqual(response.status_code, 401)
        check.assert_not_called()

    def test_invalid_session_is_rejected(self):
        with patch(
            "focusos_api.main.check_database_identity", side_effect=InvalidSession()
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/health/database", headers={"Authorization": "Bearer bad-token"}
                )

        self.assertEqual(response.status_code, 401)

    def test_database_failure_returns_503_without_internal_detail(self):
        with patch(
            "focusos_api.main.check_database_identity",
            side_effect=DatabaseUnavailable("internal connection detail"),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/health/database", headers={"Authorization": "Bearer good-token"}
                )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("internal connection detail", response.text)

    def test_verified_database_check_returns_no_identity_or_token(self):
        with patch("focusos_api.main.check_database_identity"):
            with TestClient(app) as client:
                response = client.get(
                    "/health/database", headers={"Authorization": "Bearer good-token"}
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
