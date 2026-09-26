import base64
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from focusos_api.connections import GoogleConnection
from focusos_api.google_gmail import (
    GMAIL_API,
    GMAIL_READ_SCOPE,
    GmailProbeError,
    GmailReconnectRequired,
    read_selected_gmail_message,
)
from focusos_api.main import app

USER_ID = UUID("a4e0ce3a-c955-4b30-9d67-f47859cd38af")
CONNECTION_ID = UUID("5e89e258-825f-4f32-8b63-bb86aa17e596")
MESSAGE_ID = "selected_message_123"


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        return self.body


class FakeGmailHttp:
    def __init__(self, *, status_code=200):
        self.status_code = status_code
        self.calls = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append((url, params, headers, timeout))
        text = "Synthetic email body".encode()
        return FakeResponse({
            "id": MESSAGE_ID,
            "threadId": "thread-id",
            "labelIds": ["INBOX", "UNREAD"],
            "internalDate": "1799990000000",
            "snippet": "PRIVATE SNIPPET MUST NOT LEAVE API",
            "payload": {"mimeType": "multipart/alternative", "parts": [
                {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(text).decode().rstrip("=")}},
                {"mimeType": "text/html", "body": {"data": "cHJpdmF0ZWh0bWw="}},
            ]},
        }, self.status_code)


class GmailProbeTests(unittest.TestCase):
    def setUp(self):
        self.connection = GoogleConnection(
            id=CONNECTION_ID, provider="google", display_email="private@example.test",
            granted_scopes=[GMAIL_READ_SCOPE], status="connected", last_refresh_at=None,
        )

    def test_reads_only_one_selected_message_and_returns_counts_not_content(self):
        http = FakeGmailHttp()
        with (
            patch("focusos_api.google_gmail.read_google_connection", return_value=self.connection),
            patch("focusos_api.google_gmail.TokenCipher.from_environment", return_value=object()),
            patch("focusos_api.google_gmail.GoogleOAuthClient.from_environment", return_value=object()),
            patch("focusos_api.google_gmail.get_google_access_token", return_value="google-access-token"),
        ):
            probe = read_selected_gmail_message("supabase-token", MESSAGE_ID, http_client=http)

        self.assertEqual(probe.message_id, MESSAGE_ID)
        self.assertEqual(probe.text_body_bytes, len(b"Synthetic email body"))
        self.assertEqual(probe.label_count, 2)
        self.assertEqual(http.calls[0][0], GMAIL_API + MESSAGE_ID)
        self.assertEqual(http.calls[0][1], {"format": "full"})
        self.assertEqual(http.calls[0][2]["Authorization"], "Bearer google-access-token")
        self.assertNotIn("snippet", probe.model_dump())
        self.assertNotIn("body", probe.model_dump())
        self.assertNotIn("private@example.test", probe.model_dump_json())

    def test_rejects_invalid_message_id_before_database_or_provider_access(self):
        with patch("focusos_api.google_gmail.read_google_connection") as read:
            with self.assertRaises(GmailProbeError):
                read_selected_gmail_message("supabase-token", "../other-user")
        read.assert_not_called()

    def test_missing_gmail_scope_requires_reconnect_without_provider_call(self):
        connection = self.connection.model_copy(update={"granted_scopes": []})
        http = FakeGmailHttp()
        with patch("focusos_api.google_gmail.read_google_connection", return_value=connection):
            with self.assertRaises(GmailReconnectRequired):
                read_selected_gmail_message("supabase-token", MESSAGE_ID, http_client=http)
        self.assertEqual(http.calls, [])

    def test_provider_unauthorized_response_requires_reconnect(self):
        http = FakeGmailHttp(status_code=401)
        with (
            patch("focusos_api.google_gmail.read_google_connection", return_value=self.connection),
            patch("focusos_api.google_gmail.TokenCipher.from_environment", return_value=object()),
            patch("focusos_api.google_gmail.GoogleOAuthClient.from_environment", return_value=object()),
            patch("focusos_api.google_gmail.get_google_access_token", return_value="google-access-token"),
        ):
            with self.assertRaises(GmailReconnectRequired):
                read_selected_gmail_message("supabase-token", MESSAGE_ID, http_client=http)


class GmailProbeRouteTests(unittest.TestCase):
    def test_anonymous_probe_is_rejected(self):
        with TestClient(app) as client:
            response = client.get(f"/connections/google/gmail/messages/{MESSAGE_ID}")
        self.assertEqual(response.status_code, 401)

    def test_probe_endpoint_does_not_return_message_content(self):
        with patch("focusos_api.main.read_selected_gmail_message") as probe:
            probe.return_value = {
                "message_id": MESSAGE_ID, "internal_date_ms": 1799990000000,
                "label_count": 2, "text_body_bytes": 21,
            }
            with TestClient(app) as client:
                response = client.get(
                    f"/connections/google/gmail/messages/{MESSAGE_ID}",
                    headers={"Authorization": "Bearer supabase-token"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("PRIVATE", response.text)
        self.assertNotIn("body", response.json())


if __name__ == "__main__":
    unittest.main()
