import unittest
from uuid import uuid4
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from focusos_api.gmail_status import read_gmail_sync_status
from focusos_api.main import app


class GmailStatusTests(unittest.TestCase):
    def test_no_connection_has_safe_idle_status(self):
        with patch("focusos_api.gmail_status.read_google_connection", return_value=None):
            status = read_gmail_sync_status("session")
        self.assertEqual(status.connection_status, "not_connected")
        self.assertEqual(status.source_count, 0)

    def test_connected_status_uses_owner_scoped_rpc(self):
        connection = Mock(id=uuid4(), status="connected", granted_scopes=["https://www.googleapis.com/auth/gmail.readonly"])
        client = Mock()
        client.rpc.return_value.execute.return_value.data = {
            "mode": "history", "last_status": "partial", "pending_staged": 2,
            "page_pending": True, "source_count": 3, "ready_count": 1,
            "failed_count": 0, "pending_count": 2,
        }
        context = Mock()
        context.__enter__ = Mock(return_value=(None, client))
        context.__exit__ = Mock(return_value=False)
        with patch("focusos_api.gmail_status.read_google_connection", return_value=connection), \
             patch("focusos_api.gmail_status.scoped_client", return_value=context):
            status = read_gmail_sync_status("session")
        self.assertEqual(status.connection_status, "connected")
        self.assertEqual(status.pending_staged, 2)
        self.assertEqual(status.source_count, 3)
        self.assertEqual(client.rpc.call_args.args[0], "focusos_gmail_sync_status")

    def test_anonymous_status_route(self):
        self.assertEqual(TestClient(app).get("/connections/google/gmail/sync/status").status_code, 401)


if __name__ == "__main__":
    unittest.main()
