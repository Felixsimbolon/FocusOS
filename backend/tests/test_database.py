import base64
import json
import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from focusos_api import database
from focusos_api.database import DatabaseUnavailable, InvalidSession, check_database_identity, scoped_client, service_client
from focusos_api.main import app


SETTINGS = {"FOCUSOS_SUPABASE_URL": "https://example.supabase.co", "FOCUSOS_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test"}


def jwt(exp: float) -> str:
    claims = base64.urlsafe_b64encode(json.dumps({"sub": "user-123", "exp": exp}).encode()).decode().rstrip("=")
    return f"header.{claims}.signature"


class DatabaseIdentityTests(unittest.TestCase):
    def setUp(self):
        database.forget_verified_sessions()

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


class VerifiedSessionCacheTests(unittest.TestCase):
    def setUp(self):
        database.forget_verified_sessions()

    def tearDown(self):
        database.forget_verified_sessions()

    def operations(self, *tokens):
        with patch.dict(os.environ, SETTINGS), patch("focusos_api.database.httpx.Client"), patch("focusos_api.database.create_client") as create_client:
            client = create_client.return_value
            client.auth.get_user.return_value.user.id = "user-123"
            owners = []
            for token in tokens:
                with scoped_client(token) as (owner, _):
                    owners.append(owner)
            return owners, client

    def test_one_session_is_verified_once_for_many_operations(self):
        token = jwt(time.time() + 3600)
        owners, client = self.operations(token, token, token)
        self.assertEqual(owners, ["user-123"] * 3)
        client.auth.get_user.assert_called_once_with(token)
        # Every operation still carries the caller's JWT to PostgREST, which checks it itself.
        self.assertEqual(client.postgrest.auth.call_count, 3)

    def test_each_session_is_verified_on_its_own(self):
        first, second = jwt(time.time() + 3600), jwt(time.time() + 3601)
        _, client = self.operations(first, second)
        self.assertEqual([call.args[0] for call in client.auth.get_user.call_args_list], [first, second])

    def test_a_verification_is_forgotten_after_the_ttl_or_the_tokens_own_expiry(self):
        token = jwt(time.time() + 3600)
        self.operations(token)
        with patch("focusos_api.database.time.time", return_value=time.time() + database.SESSION_TTL_SECONDS + 1):
            self.assertIsNone(database._verified_user(token))
        nearly_expired = jwt(time.time() + 5)
        self.operations(nearly_expired)
        with patch("focusos_api.database.time.time", return_value=time.time() + 6):
            self.assertIsNone(database._verified_user(nearly_expired))
        expired = jwt(time.time() - 1)
        _, client = self.operations(expired, expired)
        self.assertEqual(client.auth.get_user.call_count, 2)

    def test_a_rejected_session_is_never_remembered(self):
        with patch.dict(os.environ, SETTINGS), patch("focusos_api.database.httpx.Client"), patch("focusos_api.database.create_client") as create_client:
            create_client.return_value.auth.get_user.return_value.user = None
            for _ in range(2):
                with self.assertRaises(InvalidSession):
                    with scoped_client("bad-token"):
                        pass
            self.assertEqual(create_client.return_value.auth.get_user.call_count, 2)
        self.assertIsNone(database._verified_user("bad-token"))

    def test_tokens_are_kept_only_as_hashes(self):
        token = jwt(time.time() + 3600)
        self.operations(token)
        self.assertNotIn(token, database._verified)


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


class ServiceClientTests(unittest.TestCase):
    def test_user_publishable_key_cannot_be_used_for_privileged_client(self):
        settings = {
            "FOCUSOS_SUPABASE_URL": "https://example.supabase.co",
            "FOCUSOS_SUPABASE_SERVICE_ROLE_KEY": "sb_publishable_not-a-server-secret",
        }
        with patch.dict(os.environ, settings), patch(
            "focusos_api.database.create_client"
        ) as create_client:
            with self.assertRaises(DatabaseUnavailable):
                with service_client():
                    pass
            create_client.assert_not_called()

    def test_privileged_client_requires_server_secret_key(self):
        settings = {
            "FOCUSOS_SUPABASE_URL": "https://example.supabase.co",
            "FOCUSOS_SUPABASE_SERVICE_ROLE_KEY": "sb_secret_server-only",
        }
        with patch.dict(os.environ, settings), patch(
            "focusos_api.database.httpx.Client"
        ) as transport_factory, patch("focusos_api.database.create_client") as create_client:
            with service_client() as client:
                self.assertIs(client, create_client.return_value)

        self.assertEqual(create_client.call_args.args[1], "sb_secret_server-only")
        self.assertIs(
            create_client.call_args.kwargs["options"].httpx_client,
            transport_factory.return_value.__enter__.return_value,
        )


if __name__ == "__main__":
    unittest.main()
