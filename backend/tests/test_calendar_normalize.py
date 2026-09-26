import unittest
from datetime import datetime, timezone

from focusos_api.calendar_domain import CalendarEventError
from focusos_api.calendar_normalize import normalize_event, occurrence_interval

OBSERVED = datetime(2026, 9, 27, tzinfo=timezone.utc)


class CalendarNormalizeTests(unittest.TestCase):
    def _event(self, start=None, end=None, **fields):
        return dict(id="evt", summary="Meeting",
            start=start or {"dateTime": "2026-09-27T09:00:00+07:00", "timeZone": "Asia/Jakarta"},
            end=end or {"dateTime": "2026-09-27T10:00:00+07:00", "timeZone": "Asia/Jakarta"}, **fields)

    def _normalize(self, event):
        return normalize_event(event, calendar_timezone="Asia/Jakarta", observed_at=OBSERVED)

    def test_timed_and_all_day_exclusive_end(self):
        timed = self._normalize(self._event())
        self.assertEqual(occurrence_interval(timed)[0], datetime(2026, 9, 27, 2, tzinfo=timezone.utc))
        all_day = self._normalize(self._event(start={"date": "2026-09-27"}, end={"date": "2026-09-28"}))
        self.assertEqual(occurrence_interval(all_day), (
            datetime(2026, 9, 26, 17, tzinfo=timezone.utc),
            datetime(2026, 9, 27, 17, tzinfo=timezone.utc)))

    def test_cancelled_transparent_declined_do_not_block(self):
        self.assertIsNone(self._normalize(self._event(status="cancelled", start={}, end={})))
        self.assertIsNone(self._normalize(self._event(transparency="transparent")))
        self.assertIsNone(self._normalize(self._event(attendees=[{"self": True, "responseStatus": "declined"}])))

    def test_recurring_exception_and_cross_midnight(self):
        event = self._event(
            start={"dateTime": "2026-09-27T23:00:00+07:00"},
            end={"dateTime": "2026-09-28T01:00:00+07:00"},
            recurringEventId="series", originalStartTime={"dateTime": "2026-09-26T23:00:00+07:00"})
        occurrence = self._normalize(event)
        self.assertEqual(occurrence.recurring_event_id, "series")
        self.assertEqual(occurrence_interval(occurrence)[1], datetime(2026, 9, 27, 18, tzinfo=timezone.utc))

    def test_dst_gap_or_fold_without_offset_is_rejected(self):
        for local in ("2026-03-08T02:30:00", "2026-11-01T01:30:00"):
            event = self._event(start={"dateTime": local, "timeZone": "America/New_York"},
                                end={"dateTime": "2026-11-01T03:00:00-05:00"})
            with self.assertRaises(CalendarEventError):
                self._normalize(event)

    def test_offset_mismatch_and_mixed_bounds_rejected(self):
        for event in (
            self._event(start={"dateTime": "2026-09-27T09:00:00+08:00", "timeZone": "Asia/Jakarta"}),
            self._event(start={"date": "2026-09-27"}, end={"dateTime": "2026-09-28T09:00:00Z"}),
        ):
            with self.assertRaises(CalendarEventError):
                self._normalize(event)


if __name__ == "__main__":
    unittest.main()
