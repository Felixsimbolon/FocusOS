import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from focusos_api.calendar_fetch import CalendarFetchError, fetch_calendar_window
from focusos_api.main import app

NOW = datetime(2026, 9, 27, 0, tzinfo=timezone.utc)


class Response:
    status_code = 200

    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


class FakeHttp:
    def __init__(self, replies):
        self.replies, self.calls = iter(replies), []

    def get(self, url, *, params, headers, timeout):
        self.calls.append((url, params, headers))
        return next(self.replies)


class CalendarFetchTests(unittest.TestCase):
    def test_follows_all_pages_with_same_filters_and_expanded_recurrence(self):
        http = FakeHttp([
            Response({"timeZone": "Asia/Jakarta", "items": [{"id": "one"}], "nextPageToken": "page2"}),
            Response({"timeZone": "Asia/Jakarta", "items": [{"id": "two"}]}),
        ])
        result = fetch_calendar_window("", NOW, NOW + timedelta(days=2), http_client=http, bearer="private")
        self.assertEqual(len(result.events), 2)
        self.assertEqual(http.calls[1][1]["pageToken"], "page2")
        self.assertEqual(http.calls[0][1]["singleEvents"], "true")
        self.assertEqual(http.calls[1][1]["orderBy"], "startTime")
        self.assertEqual(http.calls[0][1]["timeMin"], http.calls[1][1]["timeMin"])
        self.assertEqual(http.calls[1][2], {"Authorization": "Bearer private"})

    def test_failed_second_page_yields_no_window(self):
        http = FakeHttp([
            Response({"timeZone": "UTC", "items": [{"id": "one"}], "nextPageToken": "next"}),
            Response({}, 500),
        ])
        with self.assertRaises(Exception):
            fetch_calendar_window("", NOW, NOW + timedelta(days=1), http_client=http, bearer="private")

    def test_repeated_cursor_and_large_window_rejected(self):
        http = FakeHttp([
            Response({"timeZone": "UTC", "items": [], "nextPageToken": "again"}),
            Response({"timeZone": "UTC", "items": [], "nextPageToken": "again"}),
        ])
        with self.assertRaises(CalendarFetchError):
            fetch_calendar_window("", NOW, NOW + timedelta(days=1), http_client=http, bearer="private")
        with self.assertRaises(CalendarFetchError):
            fetch_calendar_window("", NOW, NOW + timedelta(days=15), http_client=http, bearer="private")
        self.assertEqual(len(http.calls), 2)

    def test_anonymous_window_endpoint(self):
        result = TestClient(app).get("/connections/google/calendar/window",
            params={"start": NOW.isoformat(), "end": (NOW + timedelta(days=1)).isoformat()})
        self.assertEqual(result.status_code, 401)


if __name__ == "__main__":
    unittest.main()
