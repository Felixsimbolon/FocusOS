import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from focusos_api.connections import GoogleConnection
from focusos_api.google_calendar import (
    CALENDAR_EVENTS_API,
    CALENDAR_READ_SCOPE,
    CalendarReconnectRequired,
    read_primary_calendar_page,
)
from focusos_api.main import app

CONNECTION_ID = UUID("5e89e258-825f-4f32-8b63-bb86aa17e596")
NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        return self.body


class FakeCalendarHttp:
    def __init__(self, *, status_code=200):
        self.status_code = status_code
        self.call = None

    def get(self, url, *, params, headers, timeout):
        self.call = (url, params, headers, timeout)
        return FakeResponse({
            "items": [
                {"id": "event-1", "summary": "Private event title", "start": {"dateTime": "2026-09-27T09:00:00Z"}},
                {"id": "event-2", "summary": "Another private title", "start": {"date": "2026-09-28"}},
            ],
            "nextPageToken": "opaque-next-page",
        }, self.status_code)


class CalendarProbeTests(unittest.TestCase):
    def setUp(self):
        self.connection = GoogleConnection(
            id=CONNECTION_ID, provider="google", display_email="private@example.test",
            granted_scopes=[CALENDAR_READ_SCOPE], status="connected", last_refresh_at=None,
        )

    def _probe(self, http):
        with (
            patch("focusos_api.google_calendar.read_google_connection", return_value=self.connection),
            patch("focusos_api.google_calendar.TokenCipher.from_environment", return_value=object()),
            patch("focusos_api.google_calendar.GoogleOAuthClient.from_environment", return_value=object()),
            patch("focusos_api.google_calendar.get_google_access_token", return_value="google-access-token"),
        ):
            return read_primary_calendar_page("supabase-token", http_client=http, now=NOW)

    def test_reads_bounded_primary_events_page_and_returns_counts_only(self):
        http = FakeCalendarHttp()
        page = self._probe(http)
        self.assertEqual(http.call[0], CALENDAR_EVENTS_API)
        self.assertEqual(http.call[1]["maxResults"], 10)
        self.assertEqual(http.call[1]["singleEvents"], "true")
        self.assertEqual(http.call[1]["orderBy"], "startTime")
        self.assertEqual(page.calendar, "primary")
        self.assertEqual(page.event_count, 2)
        self.assertTrue(page.page_has_more)
        self.assertEqual((page.window_end - page.window_start).days, 7)
        self.assertNotIn("Private event title", page.model_dump_json())
        self.assertNotIn("event-1", page.model_dump_json())

    def test_missing_calendar_scope_fails_before_provider_call(self):
        self.connection = self.connection.model_copy(update={"granted_scopes": []})
        http = FakeCalendarHttp()
        with patch("focusos_api.google_calendar.read_google_connection", return_value=self.connection):
            with self.assertRaises(CalendarReconnectRequired):
                read_primary_calendar_page("supabase-token", http_client=http, now=NOW)
        self.assertIsNone(http.call)

    def test_anonymous_calendar_probe_is_denied(self):
        with TestClient(app) as client:
            response = client.get("/connections/google/calendar/probe")
        self.assertEqual(response.status_code, 401)

    def test_calendar_endpoint_returns_no_event_titles(self):
        with patch("focusos_api.main.read_primary_calendar_page") as read:
            read.return_value = {
                "calendar": "primary", "window_start": NOW, "window_end": NOW,
                "event_count": 2, "page_has_more": False,
            }
            with TestClient(app) as client:
                response = client.get("/connections/google/calendar/probe", headers={"Authorization": "Bearer token"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("summary", response.text)
        self.assertNotIn("title", response.text)


if __name__ == "__main__":
    unittest.main()
