import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from focusos_api.calendar_availability import build_availability_preview
from focusos_api.calendar_fetch import CalendarFetchUnavailable, CalendarWindow
from focusos_api.main import app
from focusos_api.profiles import ProfileRecord, WorkingHours

NOW = datetime(2026, 9, 28, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 28, 17, tzinfo=timezone.utc)


class AvailabilityTests(unittest.TestCase):
    def test_preview_uses_profile_zone_and_complete_window(self):
        profile = ProfileRecord(id=uuid4(), timezone="Asia/Jakarta",
            working_hours=WorkingHours(days=[1], start_minute=9*60, end_minute=17*60))
        event = {"id": "meeting", "summary": "Synthetic meeting",
            "start": {"dateTime": "2026-09-28T10:00:00+07:00"},
            "end": {"dateTime": "2026-09-28T11:00:00+07:00"}}
        window = CalendarWindow(NOW, END, NOW, "primary", "Asia/Jakarta", (event,))
        with patch("focusos_api.calendar_availability.read_profile", return_value=profile):
            result = build_availability_preview("user", now=NOW, calendar_window=window)
        self.assertTrue(result.complete)
        self.assertEqual(result.event_count, 1)
        self.assertEqual(result.busy_events[0].title, "Synthetic meeting")
        self.assertEqual(result.free_time.available_minutes, 420)

    def test_provider_failure_exposes_no_partial_schedule(self):
        with patch("focusos_api.main.build_availability_preview",
                   side_effect=CalendarFetchUnavailable("private provider response")):
            result = TestClient(app).get("/connections/google/calendar/availability",
                headers={"Authorization": "Bearer synthetic"})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private provider response", result.text)
        self.assertNotIn("busy_events", result.text)

    def test_anonymous_route_rejected(self):
        self.assertEqual(TestClient(app).get(
            "/connections/google/calendar/availability?days=1&duration_minutes=60").status_code, 401)


if __name__ == "__main__":
    unittest.main()
