"""Routines: occurrences, claiming, and booking through the request pipeline. Providers/DB simulated."""
import json
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from focusos_api import routines as rules
from focusos_api.jobs import RetryStep
from focusos_api.planning_request import explicit_constraints
from focusos_api.routines import RoutineIntent, describe, occurrence_schedule, plan_occurrences, upcoming_dates
from focusos_api.unified_commands import WorkIntent, constraint_text, infer_work
from test_combined_requests import plan
from test_planning_compiler import NOW, PROFILE

ZONE = ZoneInfo("Asia/Jakarta")
FRIDAY_NOON = datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc)  # Friday 12:00 in Jakarta
ROUTINE = {"id": str(uuid4()), "title": "Belajar Python", "weekdays": [2, 4], "start_minute": 420, "duration_minutes": 60, "ends_on": None}
TEXT = "Belajar Python setiap Selasa dan Kamis jam 7-8 pagi."


def routine_intent(**changes):
    return RoutineIntent.model_validate({"title_quote": "Belajar Python", "request_quote": TEXT, "weekdays": [2, 4],
                                         "start_time": "07:00", "duration_minutes": 60, "ends_on": None, **changes})


class OccurrenceTests(unittest.TestCase):
    def test_coming_week_only_on_the_chosen_days_and_still_in_the_future(self):
        self.assertEqual(upcoming_dates(ROUTINE, FRIDAY_NOON, ZONE), [date(2026, 10, 20), date(2026, 10, 22)])
        thursday_morning = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)  # 07:00 Jakarta: today's start has passed
        self.assertEqual(upcoming_dates(ROUTINE, thursday_morning, ZONE), [date(2026, 10, 27)])
        ended = {**ROUTINE, "ends_on": "2026-10-21"}
        self.assertEqual(upcoming_dates(ended, FRIDAY_NOON, ZONE), [date(2026, 10, 20)])

    def test_an_occurrence_is_a_fixed_activity_whose_title_never_becomes_a_limit(self):
        schedule = occurrence_schedule({**ROUTINE, "title": "Gym 18:00 besok"}, date(2026, 10, 20))
        self.assertEqual((schedule.target, schedule.occurrence, schedule.selection.date), ("activity", "2026-10-20", "2026-10-20"))
        self.assertEqual((schedule.selection.start_time, schedule.selection.end_time, schedule.selection.duration_minutes), ("07:00", "08:00", 60))
        limits = explicit_constraints(constraint_text(plan(), schedule, "ignored"))
        self.assertEqual(limits, {"start_time": "07:00", "end_time": "08:00", "day": "date", "date": "2026-10-20"})

    def test_indonesian_part_of_day_sets_both_ends_of_a_range(self):
        cases = {"blokir jumat jam 4-6 sore buat futsal": ("16:00", "18:00"), "jam 7-9 pagi": ("07:00", "09:00"),
                 "jam 1-3 siang": ("13:00", "15:00"), "jam 7-9 malam": ("19:00", "21:00"), "jam 16-18": ("16:00", "18:00")}
        for text, (start, end) in cases.items():
            with self.subTest(text=text):
                limits = explicit_constraints(text)
                self.assertEqual((limits["start_time"], limits["end_time"]), (start, end))

    def test_only_dates_the_database_lets_this_request_claim_are_booked(self):
        run_id = uuid4()
        with patch.object(rules, "claim", return_value=[date(2026, 10, 22)]) as claim:
            schedules, mapping = plan_occurrences("session", run_id, [ROUTINE], ZONE, FRIDAY_NOON, offset=1)
        self.assertEqual(claim.call_args.args[2], [date(2026, 10, 20), date(2026, 10, 22)])
        self.assertEqual([item.occurrence for item in schedules], ["2026-10-22"])
        self.assertEqual(mapping, [{"routine_id": ROUTINE["id"], "date": "2026-10-22", "index": 1}])

    def test_outcomes_mark_each_date_booked_or_failed(self):
        client = MagicMock()
        mapping = [{"routine_id": "r", "date": "2026-10-20", "index": 0}, {"routine_id": "r", "date": "2026-10-22", "index": 1}]
        with patch.object(rules, "scoped_client") as scoped:
            scoped.return_value.__enter__.return_value = ("owner", client)
            rules.finish_occurrences("session", uuid4(), mapping, [{"status": "scheduled"}, {"status": "failed"}])
        self.assertEqual([call.args[1]["p_status"] for call in client.rpc.call_args_list], ["booked", "failed"])

    def test_summary_reads_naturally(self):
        self.assertEqual(describe(ROUTINE), "Belajar Python: Tue, Thu, 07:00–08:00")
        self.assertEqual(describe({**ROUTINE, "weekdays": [1, 2, 3, 4, 5]}), "Belajar Python: weekdays, 07:00–08:00")


class RoutineIntentTests(unittest.TestCase):
    def infer(self, value, text=TEXT):
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]}
        with patch("focusos_api.unified_commands.api_key", return_value="synthetic"), \
             patch("focusos_api.unified_commands.request", return_value=response) as call:
            result = infer_work(text, [], NOW.isoformat(), PROFILE.timezone)
        return result, call.call_args.args[0]

    def test_a_recurring_request_becomes_a_routine(self):
        value = {**plan().model_dump(), "routines": [routine_intent().model_dump()]}
        result, payload = self.infer(value)
        self.assertEqual((result.routines[0].weekdays, result.action), ([2, 4], "routine"))
        # The model is never offered the server-only occurrence field.
        self.assertNotIn("occurrence", json.dumps(payload["generationConfig"]))

    def test_rejects_routines_not_grounded_in_the_text_or_impossible(self):
        for bad in (routine_intent(title_quote="Belajar Golang"), routine_intent(weekdays=[2, 2]),
                    routine_intent(start_time="23:30", duration_minutes=60), routine_intent(ends_on="2020-01-01")):
            with self.subTest(bad.model_dump_json()[:60]), self.assertRaises(RetryStep):
                self.infer({**plan().model_dump(), "routines": [bad.model_dump()]})

    def test_the_model_cannot_add_occurrences_or_too_many_schedules(self):
        occurrence = occurrence_schedule(ROUTINE, date(2026, 10, 20)).model_dump()
        with self.assertRaises(RetryStep):
            self.infer({**plan().model_dump(), "schedules": [occurrence]})

    def test_saved_plans_without_routines_still_load(self):
        old = plan().model_dump(); old.pop("routines")
        self.assertEqual(WorkIntent.model_validate(old).routines, [])


class RoutineWorkflowTests(unittest.TestCase):
    def test_request_saves_the_routine_books_its_week_and_records_each_date(self):
        from test_unified_commands import UnifiedHarness
        h = UnifiedHarness().enter(); self.addCleanup(h.close)
        h.work_intent = WorkIntent.model_validate({**plan().model_dump(), "routines": [routine_intent().model_dump()]})
        tomorrow = NOW.astimezone(ZONE).date().replace(day=NOW.astimezone(ZONE).day + 1)
        occurrence = occurrence_schedule({**ROUTINE, "start_minute": 780}, tomorrow)  # 13:00-14:00, inside the harness window
        mapping = [{"routine_id": ROUTINE["id"], "date": tomorrow.isoformat(), "index": 0}]
        with patch("focusos_api.unified_commands.routine_rules.save_routine", return_value=ROUTINE) as save,              patch("focusos_api.unified_commands.routine_rules.plan_occurrences", return_value=([occurrence], mapping)),              patch("focusos_api.unified_commands.routine_rules.finish_occurrences") as finish:
            step, _ = h.drain(h.start(TEXT))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(step.result["routines_saved"], 1)
        self.assertEqual(step.result["blocks_scheduled"], 1)
        save.assert_called_once()
        self.assertEqual(finish.call_args.args[2], mapping)
        self.assertEqual(finish.call_args.args[3][0]["status"], "scheduled")


class TopUpTests(unittest.TestCase):
    def test_books_only_unbooked_occurrences_in_one_prepared_request(self):
        listed = [{**ROUTINE, "active": True, "upcoming": [{"date": "2026-10-20", "status": "booked"}]}]
        rpc = MagicMock(return_value={"id": str(uuid4()), "status": "pending", "version": 1})
        checkpoint = MagicMock(return_value=True)
        with patch.object(rules, "list_routines", return_value=listed), patch.object(rules, "read_profile", return_value=PROFILE), \
             patch.object(rules, "_rpc", rpc), patch.object(rules, "_checkpoint", checkpoint), \
             patch.object(rules, "claim", side_effect=lambda token, routine_id, dates, run_id: [d for d in dates if d.isoformat() != "2026-10-20"]), \
             patch.object(rules, "enqueue_job", return_value=SimpleNamespace(model_dump=lambda **_: {"id": "job"})):
            result = rules.start_top_up("session", uuid4(), FRIDAY_NOON)
        saved = checkpoint.call_args.args[5]
        self.assertEqual(result["booking"], 1)
        self.assertEqual([item["date"] for item in saved["routine_occurrences"]], ["2026-10-22"])
        self.assertIn('"Belajar Python"', rpc.call_args.args[2]["p_command"])

    def test_nothing_to_book_starts_no_request(self):
        listed = [{**ROUTINE, "active": False, "upcoming": []}]
        with patch.object(rules, "list_routines", return_value=listed), patch.object(rules, "read_profile", return_value=PROFILE), \
             patch.object(rules, "_rpc") as rpc:
            self.assertEqual(rules.start_top_up("session", uuid4(), FRIDAY_NOON), {"booking": 0})
        rpc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
