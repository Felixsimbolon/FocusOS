"""Month view of the whole Google Calendar. Calendar and database are simulated."""
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from focusos_api.calendar_month import MonthOutOfRange, month_bounds, month_events, windows

ZONE = ZoneInfo("Asia/Jakarta")
NOW = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)


def timed(provider_id, start, minutes=60, title="Meeting"):
    return SimpleNamespace(provider_id=provider_id, title=title, kind="timed", start_at=start, end_at=start + timedelta(minutes=minutes),
                           start_date=None, end_date_exclusive=None)


def all_day(provider_id, day, days=1, title="Holiday"):
    return SimpleNamespace(provider_id=provider_id, title=title, kind="all_day", start_at=None, end_at=None,
                           start_date=day, end_date_exclusive=day + timedelta(days=days))


class BoundsTests(unittest.TestCase):
    def test_month_runs_from_local_midnight_to_the_next_month(self):
        start, end = month_bounds("2026-12", ZONE, date(2026, 10, 17))
        self.assertEqual((start.isoformat(), end.isoformat()), ("2026-12-01T00:00:00+07:00", "2027-01-01T00:00:00+07:00"))

    def test_reads_are_split_into_windows_of_at_most_fourteen_days(self):
        start, end = month_bounds("2026-10", ZONE, date(2026, 10, 17))
        parts = windows(start, end)
        self.assertEqual(len(parts), 3)
        self.assertEqual((parts[0][0], parts[-1][1]), (start, end))
        self.assertTrue(all(high - low <= timedelta(days=14) for low, high in parts))
        self.assertTrue(all(a[1] == b[0] for a, b in zip(parts, parts[1:])))

    def test_months_far_away_or_malformed_are_refused(self):
        for month in ("2030-01", "2026-13", "nonsense"):
            with self.subTest(month), self.assertRaises(MonthOutOfRange):
                month_bounds(month, ZONE, date(2026, 10, 17))


class MonthEventsTests(unittest.TestCase):
    def test_merges_windows_marks_focusos_events_and_uses_local_time(self):
        meeting = timed("meeting", datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc))
        focus = timed("focusos1", datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc), title="Write report")
        holiday = all_day("holiday", date(2026, 10, 28))
        pages = [[meeting], [meeting, focus], [holiday]]  # the meeting appears in two windows
        with patch("focusos_api.calendar_month.read_profile", return_value=SimpleNamespace(timezone="Asia/Jakarta")), \
             patch("focusos_api.calendar_month.fetch_calendar_window", side_effect=lambda *_: object()), \
             patch("focusos_api.calendar_month.normalize_window", side_effect=pages), \
             patch("focusos_api.calendar_month._focusos_event_ids", return_value={"focusos1"}):
            result = month_events("session", "2026-10", NOW)
        self.assertEqual([event["id"] for event in result["events"]], ["meeting", "focusos1", "holiday"])
        self.assertEqual(result["events"][0]["start"], "2026-10-20T09:00:00+07:00")
        self.assertEqual([event["focusos"] for event in result["events"]], [False, True, False])
        self.assertEqual((result["events"][2]["all_day"], result["events"][2]["end"]), (True, "2026-10-29"))
        self.assertFalse(result["truncated"])


if __name__ == "__main__":
    unittest.main()
