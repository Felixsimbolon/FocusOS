import unittest
from datetime import date, datetime, timezone

from pydantic import ValidationError
from focusos_api.calendar_domain import CalendarOccurrence


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


class CalendarDomainTests(unittest.TestCase):
    def test_timed_occurrence_needs_offsets_and_positive_duration(self):
        valid = dict(provider_id="evt1", kind="timed", start_at=NOW,
                     end_at=datetime(2026, 9, 27, 1, tzinfo=timezone.utc), observed_at=NOW)
        self.assertEqual(CalendarOccurrence(**valid).kind, "timed")
        for change in ({"start_at": NOW.replace(tzinfo=None)},
                       {"end_at": NOW}, {"start_date": date(2026, 9, 27)}):
            with self.assertRaises(ValidationError):
                CalendarOccurrence(**(valid | change))

    def test_all_day_exclusive_end_and_zone(self):
        valid = dict(provider_id="evt2", kind="all_day", start_date=date(2026, 9, 27),
                     end_date_exclusive=date(2026, 9, 28), timezone="Asia/Jakarta", observed_at=NOW)
        self.assertEqual(CalendarOccurrence(**valid).kind, "all_day")
        for change in ({"end_date_exclusive": date(2026, 9, 27)},
                       {"timezone": "Invalid/Zone"}, {"timezone": None},
                       {"start_at": NOW}):
            with self.assertRaises(ValidationError):
                CalendarOccurrence(**(valid | change))


if __name__ == "__main__":
    unittest.main()
