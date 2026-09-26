import unittest
from datetime import date, datetime
from pydantic import ValidationError

from focusos_api.tasks import TaskCreate


class TaskPayloadTests(unittest.TestCase):
    def test_no_deadline_defaults_cleanly_and_normalizes_text(self):
        task = TaskCreate(title="  Review proposal  ", description="  details  ")
        self.assertEqual(task.title, "Review proposal")
        self.assertEqual(task.description, "details")
        self.assertEqual(task.due_kind, "none")
        self.assertIsNone(task.due_date)
        self.assertIsNone(task.due_at)

    def test_blank_description_becomes_none(self):
        self.assertIsNone(TaskCreate(title="Task", description="  ").description)

    def test_title_and_description_length_boundaries(self):
        self.assertEqual(len(TaskCreate(title="x" * 200).title), 200)
        self.assertEqual(len(TaskCreate(title="x", description="d" * 2000).description), 2000)
        for payload in ({"title": " "}, {"title": "x" * 201}, {"title": "x", "description": "d" * 2001}):
            with self.subTest(payload_length=len(str(payload))):
                with self.assertRaises(ValidationError):
                    TaskCreate(**payload)

    def test_date_only_accepts_valid_iso_date(self):
        task = TaskCreate(title="Submit form", due_kind="date", due_date="2028-02-29")
        self.assertEqual(task.due_date, date(2028, 2, 29))
        self.assertIsNone(task.due_at)
        self.assertIsNone(task.due_timezone)

    def test_date_only_rejects_impossible_or_non_date_values(self):
        for value in ("2027-02-29", "2028-2-09", "2028-02-29T00:00:00Z", "2028-01-01 "):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    TaskCreate(title="Submit form", due_kind="date", due_date=value)

    def test_deadline_kinds_require_exact_field_shapes(self):
        invalid = [
            {"title": "x", "due_kind": "none", "due_date": "2028-01-01"},
            {"title": "x", "due_kind": "date"},
            {"title": "x", "due_kind": "date", "due_date": "2028-01-01", "due_timezone": "UTC"},
            {"title": "x", "due_kind": "datetime", "due_at": "2028-01-01T09:00:00+07:00"},
            {"title": "x", "due_kind": "datetime", "due_at": "2028-01-01T09:00:00"},
            {"title": "x", "due_kind": "datetime", "due_at": "2028-01-01T09:00:00+07:00", "due_timezone": "No/Such_Zone"},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    TaskCreate(**payload)

    def test_zoned_datetime_requires_matching_offset_and_zone(self):
        task = TaskCreate(
            title="Call",
            due_kind="datetime",
            due_at="2026-10-02T09:30:00+07:00",
            due_timezone="Asia/Jakarta",
        )
        self.assertEqual(task.due_at, datetime.fromisoformat("2026-10-02T09:30:00+07:00"))
        with self.assertRaises(ValidationError):
            TaskCreate(
                title="Call",
                due_kind="datetime",
                due_at="2026-10-02T09:30:00+00:00",
                due_timezone="Asia/Jakarta",
            )

    def test_priority_and_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            TaskCreate(title="x", priority="urgent")
        with self.assertRaises(ValidationError):
            TaskCreate(title="x", user_id="00000000-0000-4000-8000-000000000001")

    def test_estimate_has_inclusive_bounds_and_rejects_coercion(self):
        self.assertEqual(TaskCreate(title="x", estimate_minutes=1).estimate_minutes, 1)
        self.assertEqual(TaskCreate(title="x", estimate_minutes=1440).estimate_minutes, 1440)
        for value in (0, 1441, True, "30", 30.5):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    TaskCreate(title="x", estimate_minutes=value)


if __name__ == "__main__":
    unittest.main()
