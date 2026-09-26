import unittest
from datetime import date, datetime, timedelta, timezone
from dataclasses import replace

from focusos_api.calendar_fetch import CalendarWindow
from focusos_api.calendar_free_time import CalendarPlanningError, calculate_free_time
from focusos_api.profiles import WorkingHours

START = datetime(2026, 9, 28, 0, tzinfo=timezone.utc)
HOURS = WorkingHours(days=[1], start_minute=9*60, end_minute=17*60)


def window(*events, start=START, end=START+timedelta(days=1), zone="Asia/Jakarta"):
    return CalendarWindow(start, end, START, "primary", zone, tuple(events))


def event(identifier, start, end):
    return {"id": identifier, "start": {"dateTime": start}, "end": {"dateTime": end}}


class FreeTimeTests(unittest.TestCase):
    def test_merge_touching_busy_and_select_contiguous(self):
        source = window(
            event("one", "2026-09-28T10:00:00+07:00", "2026-09-28T11:00:00+07:00"),
            event("two", "2026-09-28T11:00:00+07:00", "2026-09-28T12:00:00+07:00"))
        result = calculate_free_time(source, timezone_name="Asia/Jakarta",
            working_hours=HOURS, duration_minutes=120)
        self.assertEqual(result.available_minutes, 360)
        self.assertEqual(result.slots[0].start, datetime(2026, 9, 28, 5, tzinfo=timezone.utc))
        self.assertEqual(result.shortfall_minutes, 0)

    def test_full_day_busy_and_no_events(self):
        all_day = {"id": "day", "start": {"date": "2026-09-28"}, "end": {"date": "2026-09-29"}}
        busy = calculate_free_time(window(all_day), timezone_name="Asia/Jakarta",
            working_hours=HOURS, duration_minutes=60)
        empty = calculate_free_time(window(), timezone_name="Asia/Jakarta",
            working_hours=HOURS, duration_minutes=60)
        self.assertEqual((busy.available_minutes, busy.shortfall_minutes), (0, 60))
        self.assertEqual((empty.available_minutes, empty.slots[0].start),
            (480, datetime(2026, 9, 28, 2, tzinfo=timezone.utc)))

    def test_split_policy_and_deadline(self):
        source = window(event("midday", "2026-09-28T11:00:00+07:00", "2026-09-28T15:00:00+07:00"))
        contiguous = calculate_free_time(source, timezone_name="Asia/Jakarta",
            working_hours=HOURS, duration_minutes=180)
        split = calculate_free_time(source, timezone_name="Asia/Jakarta",
            working_hours=HOURS, duration_minutes=180, allow_split=True)
        self.assertEqual((contiguous.allocated_minutes, contiguous.shortfall_minutes), (0, 180))
        self.assertEqual((split.allocated_minutes, len(split.slots)), (180, 2))
        before = calculate_free_time(source, timezone_name="Asia/Jakarta",
            working_hours=HOURS, duration_minutes=180, allow_split=True,
            deadline=datetime(2026, 9, 28, 4, tzinfo=timezone.utc))
        self.assertEqual(before.shortfall_minutes, 60)

    def test_incomplete_and_date_only_deadline_rejected(self):
        source = window()
        for candidate, deadline in ((replace(source, complete=False), None),
                                    (source, date(2026, 9, 28))):
            with self.assertRaises(CalendarPlanningError):
                calculate_free_time(candidate, timezone_name="Asia/Jakarta",
                    working_hours=HOURS, duration_minutes=60, deadline=deadline)

    def test_dst_work_boundary_rejected(self):
        start = datetime(2026, 3, 8, tzinfo=timezone.utc)
        source = window(start=start, end=start+timedelta(days=1), zone="America/New_York")
        with self.assertRaises(CalendarPlanningError):
            calculate_free_time(source, timezone_name="America/New_York",
                working_hours=WorkingHours(days=[7], start_minute=2*60+30, end_minute=4*60),
                duration_minutes=30)


if __name__ == "__main__":
    unittest.main()

