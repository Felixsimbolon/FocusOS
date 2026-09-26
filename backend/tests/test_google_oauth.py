import base64
import json
import os
import unittest
from datetime import datetime, timezone
from uuid import UUID
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from focusos_api.connections import GoogleConnection
from focusos_api.google_oauth import (
    GOOGLE_TOKEN_ENDPOINT,
    GOOGLE_USERINFO_ENDPOINT,
    GoogleAuthorizationInput,
    GOOGLE_CALENDAR_WRITE_SCOPE,
    GoogleOAuthError,
    SupabaseGoogleCredentialWriter,
    complete_calendar_write_upgrade,
    complete_google_authorization,
)
from focusos_api.main import app
from focusos_api.token_crypto import TokenCipher

USER_ID = UUID("a4e0ce3a-c955-4b30-9d67-f47859cd38af")
CONNECTION_ID = UUID("5e89e258-825f-4f32-8b63-bb86aa17e596")
CALLBACK = "http://localhost:3000/api/integrations/google/callback"
SCOPES = "openid email profile https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/calendar.events.owned.readonly"


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        return self.body


class FakeHttp:
    def __init__(self, *, scopes=SCOPES):
        self.scopes = scopes
        self.calls = []

    def post(self, url, *, data, timeout):
        self.calls.append((url, data, timeout))
        return FakeResponse({
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": 3600,
            "scope": self.scopes,
            "token_type": "Bearer",
        })

    def get(self, url, *, headers, timeout):
        self.calls.append((url, headers, timeout))
        return FakeResponse({"sub": "google-subject-1", "email": "person@example.test", "email_verified": True})


class FakeWriter:
    def __init__(self):
        self.prepared = None
        self.saved = None

    def prepare(self, user_id, provider_subject, display_email):
        self.prepared = (user_id, provider_subject, display_email)
        return CONNECTION_ID

    def store(self, connection_id, user_id, provider_subject, display_email, scopes,
              encrypted_refresh_token, encrypted_access_token, expires_at, key_version):
        self.saved = (connection_id, user_id, provider_subject, display_email, scopes,
                       encrypted_refresh_token, encrypted_access_token, expires_at, key_version)
        return GoogleConnection(
            id=connection_id, provider="google", display_email=display_email,
            granted_scopes=scopes, status="connected", last_refresh_at=None,
        )


class GoogleOAuthExchangeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "FOCUSOS_GOOGLE_CLIENT_ID": "web-client-id",
            "FOCUSOS_GOOGLE_CLIENT_SECRET": "client-secret",
            "FOCUSOS_GOOGLE_REDIRECT_URIS": CALLBACK,
            "FOCUSOS_TOKEN_ENCRYPTION_KEYS": json.dumps({"3": base64.b64encode(b"k" * 32).decode()}),
            "FOCUSOS_TOKEN_ENCRYPTION_ACTIVE_VERSION": "3",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def _exchange(self, *, scopes=SCOPES, redirect=CALLBACK):
        http = FakeHttp(scopes=scopes)
        writer = FakeWriter()
        with patch("focusos_api.google_oauth.scoped_client") as scoped:
            scoped.return_value.__enter__.return_value = (str(USER_ID), object())
            result = complete_google_authorization(
                "supabase-session",
                GoogleAuthorizationInput(code="authorization-code", code_verifier="v" * 43, redirect_uri=redirect),
                writer=writer,
                http_client=http,
                now=datetime(2026, 9, 26, tzinfo=timezone.utc),
            )
        return result, writer, http

    def test_exchanges_code_verifies_google_identity_and_stores_only_encrypted_tokens(self):
        result, writer, http = self._exchange()
        self.assertEqual(result.status, "connected")
        self.assertEqual(result.display_email, "person@example.test")
        self.assertEqual(writer.prepared, (USER_ID, "google-subject-1", "person@example.test"))
        saved = writer.saved
        self.assertEqual(saved[0], CONNECTION_ID)
        self.assertNotIn(b"refresh-secret", saved[5])
        self.assertNotIn(b"access-secret", saved[6])
        cipher = TokenCipher({3: b"k" * 32}, 3)
        self.assertEqual(cipher.decrypt(CONNECTION_ID, "refresh", saved[5], 3), "refresh-secret")
        self.assertEqual(cipher.decrypt(CONNECTION_ID, "access", saved[6], 3), "access-secret")
        self.assertEqual(http.calls[0][0], GOOGLE_TOKEN_ENDPOINT)
        self.assertEqual(http.calls[0][1]["code_verifier"], "v" * 43)
        self.assertEqual(http.calls[1][0], GOOGLE_USERINFO_ENDPOINT)
        self.assertEqual(saved[7], datetime(2026, 9, 26, 1, tzinfo=timezone.utc))


    def test_supabase_writer_calls_service_only_rpc_and_returns_safe_metadata(self):
        client = Mock()
        client.rpc.side_effect = [
            Mock(execute=Mock(return_value=Mock(data=str(CONNECTION_ID)))),
            Mock(execute=Mock(return_value=Mock(data=[{
                "id": str(CONNECTION_ID), "provider": "google", "display_email": "person@example.test",
                "granted_scopes": ["openid"], "status": "connected", "last_refresh_at": None,
            }]))),
        ]
        writer = SupabaseGoogleCredentialWriter()
        with patch("focusos_api.google_oauth.service_client") as service:
            service.return_value.__enter__.return_value = client
            prepared = writer.prepare(USER_ID, "google-subject-1", "person@example.test")
            saved = writer.store(
                CONNECTION_ID, USER_ID, "google-subject-1", "person@example.test", ["openid"],
                b"refresh-ciphertext", b"access-ciphertext", datetime(2026, 9, 26, tzinfo=timezone.utc), 3,
            )
        self.assertEqual(prepared, CONNECTION_ID)
        self.assertEqual(saved.id, CONNECTION_ID)
        self.assertEqual(client.rpc.call_args_list[0].args[0], "focusos_prepare_google_connection")
        name, params = client.rpc.call_args_list[1].args
        self.assertEqual(name, "focusos_store_google_credentials")
        self.assertEqual(params["p_encrypted_refresh_token"], "\\x" + b"refresh-ciphertext".hex())
        self.assertEqual(params["p_encrypted_access_token"], "\\x" + b"access-ciphertext".hex())

    def test_upgrade_rpc_rejects_subject_mismatch_without_returning_connection(self):
        client = Mock()
        client.rpc.return_value.execute.return_value.data = []
        writer = SupabaseGoogleCredentialWriter()
        with patch("focusos_api.google_oauth.service_client") as service:
            service.return_value.__enter__.return_value = client
            result = writer.upgrade(
                CONNECTION_ID, USER_ID, "another-google-subject", "person@example.test", ["openid"],
                b"refresh-ciphertext", b"access-ciphertext", datetime(2026, 9, 26, tzinfo=timezone.utc), 3,
            )
        self.assertIsNone(result)
        self.assertEqual(client.rpc.call_args.args[0], "focusos_upgrade_google_credentials")
        self.assertEqual(client.rpc.call_args.args[1]["p_provider_subject"], "another-google-subject")

    def test_rejects_callback_url_outside_exact_allowlist_before_provider_request(self):
        http = FakeHttp()
        with patch("focusos_api.google_oauth.scoped_client") as scoped:
            scoped.return_value.__enter__.return_value = (str(USER_ID), object())
            with self.assertRaises(GoogleOAuthError):
                complete_google_authorization(
                    "session", GoogleAuthorizationInput(code="authorization-code", code_verifier="v" * 43,
                    redirect_uri="https://attacker.test/callback"), http_client=http, writer=FakeWriter()
                )
        self.assertEqual(http.calls, [])

    def test_rejects_incomplete_scopes_before_identity_or_storage(self):
        result_writer = FakeWriter()
        http = FakeHttp(scopes="openid email profile https://www.googleapis.com/auth/gmail.readonly")
        with patch("focusos_api.google_oauth.scoped_client") as scoped:
            scoped.return_value.__enter__.return_value = (str(USER_ID), object())
            with self.assertRaises(GoogleOAuthError):
                complete_google_authorization(
                    "session", GoogleAuthorizationInput(code="authorization-code", code_verifier="v" * 43, redirect_uri=CALLBACK),
                    writer=result_writer, http_client=http
                )
        self.assertEqual(len(http.calls), 1)
        self.assertIsNone(result_writer.prepared)


class CalendarWriteUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.key_v1 = b"1" * 32
        self.key_v3 = b"3" * 32
        self.cipher = TokenCipher({1: self.key_v1, 3: self.key_v3}, 3)
        self.env = patch.dict(os.environ, {
            "FOCUSOS_GOOGLE_CLIENT_ID": "web-client-id",
            "FOCUSOS_GOOGLE_CLIENT_SECRET": "client-secret",
            "FOCUSOS_GOOGLE_REDIRECT_URIS": CALLBACK,
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.connection = GoogleConnection(
            id=CONNECTION_ID, provider="google", display_email="person@example.test",
            granted_scopes=SCOPES.split(), status="connected", last_refresh_at=None,
        )
        old_cipher = TokenCipher({1: self.key_v1}, 1)
        self.stored = Mock(
            status="connected",
            encrypted_refresh_token=old_cipher.encrypt(CONNECTION_ID, "refresh", "old-refresh-token").ciphertext,
            encryption_key_version=1,
        )

    def _run(self, *, subject="google-subject-1", scopes=SCOPES + " " + GOOGLE_CALENDAR_WRITE_SCOPE, writer_result=True):
        http = UpgradeHttp(scopes=scopes, subject=subject)
        writer = UpgradeWriter(self.connection if writer_result else None)
        with (
            patch("focusos_api.google_oauth.scoped_client") as scoped,
            patch("focusos_api.google_oauth.read_google_connection", return_value=self.connection),
            patch("focusos_api.google_oauth.SupabaseGoogleTokenStore.read", return_value=self.stored),
            patch("focusos_api.google_oauth.TokenCipher.from_environment", return_value=self.cipher),
        ):
            scoped.return_value.__enter__.return_value = (str(USER_ID), object())
            result = complete_calendar_write_upgrade(
                "supabase-session",
                GoogleAuthorizationInput(code="authorization-code", code_verifier="v" * 43, redirect_uri=CALLBACK),
                writer=writer, http_client=http, now=datetime(2026, 9, 26, tzinfo=timezone.utc),
            )
        return result, writer, http

    def test_write_upgrade_checks_same_account_and_preserves_refresh_token(self):
        result, writer, http = self._run()
        self.assertEqual(result.status, "connected")
        self.assertIn(GOOGLE_CALENDAR_WRITE_SCOPE, writer.saved[4])
        self.assertEqual(writer.saved[0], CONNECTION_ID)
        self.assertEqual(writer.saved[1], USER_ID)
        self.assertEqual(self.cipher.decrypt(CONNECTION_ID, "refresh", writer.saved[5], 3), "old-refresh-token")
        self.assertEqual(self.cipher.decrypt(CONNECTION_ID, "access", writer.saved[6], 3), "access-secret")
        self.assertEqual(http.calls[0][1]["code_verifier"], "v" * 43)

    def test_rejects_upgrade_when_google_did_not_grant_write_scope(self):
        http = UpgradeHttp(scopes=SCOPES)
        writer = UpgradeWriter(self.connection)
        with (
            patch("focusos_api.google_oauth.scoped_client") as scoped,
            patch("focusos_api.google_oauth.read_google_connection", return_value=self.connection),
        ):
            scoped.return_value.__enter__.return_value = (str(USER_ID), object())
            with self.assertRaises(GoogleOAuthError):
                complete_calendar_write_upgrade(
                    "session", GoogleAuthorizationInput(code="authorization-code", code_verifier="v" * 43, redirect_uri=CALLBACK),
                    writer=writer, http_client=http,
                )
        self.assertIsNone(writer.saved)
        self.assertEqual(len(http.calls), 1)

    def test_rejects_a_different_google_account_without_persisting(self):
        http = UpgradeHttp(subject="another-google-subject")
        writer = UpgradeWriter(None)
        with (
            patch("focusos_api.google_oauth.scoped_client") as scoped,
            patch("focusos_api.google_oauth.read_google_connection", return_value=self.connection),
            patch("focusos_api.google_oauth.SupabaseGoogleTokenStore.read", return_value=self.stored),
            patch("focusos_api.google_oauth.TokenCipher.from_environment", return_value=self.cipher),
        ):
            scoped.return_value.__enter__.return_value = (str(USER_ID), object())
            with self.assertRaises(GoogleOAuthError):
                complete_calendar_write_upgrade(
                    "session", GoogleAuthorizationInput(code="authorization-code", code_verifier="v" * 43, redirect_uri=CALLBACK),
                    writer=writer, http_client=http,
                )
        self.assertIsNotNone(writer.saved)
        self.assertEqual(writer.saved[2], "another-google-subject")
        self.assertIsNone(writer.result)


class UpgradeHttp(FakeHttp):
    def __init__(self, *, scopes=SCOPES + " " + GOOGLE_CALENDAR_WRITE_SCOPE, subject="google-subject-1"):
        self.scopes = scopes
        self.subject = subject
        self.calls = []

    def post(self, url, *, data, timeout):
        self.calls.append((url, data, timeout))
        return FakeResponse({
            "access_token": "access-secret", "expires_in": 3600,
            "scope": self.scopes, "token_type": "Bearer",
        })

    def get(self, url, *, headers, timeout):
        self.calls.append((url, headers, timeout))
        return FakeResponse({"sub": self.subject, "email": "person@example.test", "email_verified": True})


class UpgradeWriter:
    def __init__(self, result):
        self.result = result
        self.saved = None

    def upgrade(self, connection_id, user_id, provider_subject, display_email, scopes,
                encrypted_refresh_token, encrypted_access_token, expires_at, key_version):
        self.saved = (connection_id, user_id, provider_subject, display_email, scopes,
                      encrypted_refresh_token, encrypted_access_token, expires_at, key_version)
        return self.result



class GoogleOAuthRouteTests(unittest.TestCase):
    def test_anonymous_exchange_is_denied(self):
        with TestClient(app) as client:
            response = client.post("/connections/google/authorize", json={
                "code": "authorization-code", "code_verifier": "v" * 43, "redirect_uri": CALLBACK,
            })
        self.assertEqual(response.status_code, 401)

    def test_anonymous_calendar_write_upgrade_is_denied(self):
        with TestClient(app) as client:
            response = client.post("/connections/google/calendar-write/authorize", json={
                "code": "authorization-code", "code_verifier": "v" * 43, "redirect_uri": CALLBACK,
            })
        self.assertEqual(response.status_code, 401)

    def test_authenticated_exchange_returns_only_safe_connection_metadata(self):
        value = GoogleConnection(
            id=CONNECTION_ID, provider="google", display_email="person@example.test",
            granted_scopes=SCOPES.split(), status="connected", last_refresh_at=None,
        )
        with patch("focusos_api.main.complete_google_authorization", return_value=value):
            with TestClient(app) as client:
                response = client.post("/connections/google/authorize", headers={
                    "Authorization": "Bearer supabase-session",
                }, json={"code": "authorization-code", "code_verifier": "v" * 43, "redirect_uri": CALLBACK})
        self.assertEqual(response.status_code, 200)
        self.assertIn("connection", response.json())
        self.assertNotIn("access-secret", response.text)
        self.assertNotIn("refresh-secret", response.text)


if __name__ == "__main__":
    unittest.main()
