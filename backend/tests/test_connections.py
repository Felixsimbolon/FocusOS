import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from focusos_api.connections import read_google_connection
from focusos_api.main import app


class GoogleConnectionRepositoryTests(unittest.TestCase):
    def test_query_is_owner_filtered_and_projects_only_safe_metadata(self):
        expected = {
            "id": "5e89e258-825f-4f32-8b63-bb86aa17e596",
            "provider": "google",
            "display_email": "user@example.test",
            "granted_scopes": ["openid"],
            "status": "connected",
            "last_refresh_at": None,
        }
        with patch("focusos_api.connections.scoped_client") as scoped:
            client = Mock()
            table = client.table.return_value
            scoped.return_value.__enter__.return_value = ("user-123", client)
            table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [expected]
            connection = read_google_connection("user-token")

        self.assertEqual(connection.model_dump(mode="json"), expected)
        scoped.assert_called_once_with("user-token")
        client.table.assert_called_once_with("connections")
        table.select.assert_called_once_with(
            "id,provider,display_email,granted_scopes,status,last_refresh_at"
        )
        table.select.return_value.eq.assert_any_call("user_id", "user-123")
        table.select.return_value.eq.return_value.eq.assert_called_once_with("provider", "google")

    def test_missing_connection_is_returned_as_none(self):
        with patch("focusos_api.connections.scoped_client") as scoped:
            client = Mock()
            table = client.table.return_value
            scoped.return_value.__enter__.return_value = ("user-123", client)
            table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
            self.assertIsNone(read_google_connection("user-token"))


class GoogleConnectionRouteTests(unittest.TestCase):
    def test_anonymous_status_read_is_rejected(self):
        with TestClient(app) as client:
            response = client.get("/connections/google")
        self.assertEqual(response.status_code, 401)

    def test_status_route_returns_only_connection_metadata(self):
        value = {
            "id": "5e89e258-825f-4f32-8b63-bb86aa17e596",
            "provider": "google",
            "display_email": "user@example.test",
            "granted_scopes": ["openid"],
            "status": "connected",
            "last_refresh_at": None,
        }
        with patch("focusos_api.main.read_google_connection") as read:
            read.return_value = value
            with TestClient(app) as client:
                response = client.get(
                    "/connections/google",
                    headers={"Authorization": "Bearer user-token"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"connection": value})
        self.assertNotIn("token", response.text.lower())


if __name__ == "__main__":
    unittest.main()
