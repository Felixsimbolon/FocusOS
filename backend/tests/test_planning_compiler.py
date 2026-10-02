import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from focusos_api.planning_compiler import START_BUFFER_MINUTES, compile_plan
from focusos_api.planning_contract import PlanningValidationError
from focusos_api.profiles import ProfileRecord, WorkingHours

NOW = datetime(2026, 10, 2, 1, tzinfo=timezone.utc)
ZONE = ZoneInfo("Asia/Jakarta")
PROFILE = ProfileRecord(id=uuid4(), timezone="Asia/Jakarta",
    working_hours=WorkingHours(days=[1, 2, 3, 4, 5, 6, 7], start_minute=540, end_minute=1020))
TASK = {"id": str(uuid4()), "title": "Prepare the FocusOS demo checklist", "due_kind": "none",
        "due_at": None, "due_date": None, "estimate_minutes": 30}


def selection(**changes):
    return {"status": "selected", "task_refs": ["task-1"], "duration_minutes": 30,
            "day": "tomorrow", "date": None, "start_time": None, "end_time": None,
            "evidence_refs": [], "questions": [], **changes}


def checkpoint(**changes):
    return {"duration_minutes": None, "allow_split": False, "window_start": NOW.isoformat(),
            "timezone": PROFILE.timezone, "calendar": {"complete": True, "timezone": PROFILE.timezone,
            "start": NOW.isoformat(), "end": (NOW + timedelta(days=7)).isoformat(),
            "fetched_at": NOW.isoformat(), "events": []},
            "memory_search": {"mode": "semantic_enabled", "matches": []}, **changes}


def busy(start_hour, start_minute, end_hour, end_minute, day=2):
    return {"id": str(uuid4()), "title": "Busy",
        "start": datetime(2026, 10, day, start_hour, start_minute, tzinfo=ZONE).isoformat(),
        "end": datetime(2026, 10, day, end_hour, end_minute, tzinfo=ZONE).isoformat()}


class PlanningCompilerTests(unittest.TestCase):
    def compile(self, intent=None, tasks=None, options=None, profile=PROFILE, now=NOW):
        return compile_plan(intent or selection(), tasks or [TASK], options or checkpoint(), profile, now=now)

    def test_explicit_command_duration_and_day_override_a_misread_model(self):
        result, _ = compile_plan(selection(duration_minutes=60, day="any"), [TASK], checkpoint(), PROFILE,
            now=NOW, command='Schedule the task "Prepare the FocusOS demo checklist" for 30 minutes tomorrow.')
        self.assertEqual(result["scheduled_minutes"], 30)
        self.assertEqual(datetime.fromisoformat(result["blocks"][0]["start"]).astimezone(ZONE).day, 3)

    def test_conflicting_explicit_command_durations_ask_for_clarification(self):
        for command in ("Schedule for 30 to 60 minutes tomorrow", "Schedule for 30 minutes today and 60 minutes tomorrow"):
            result, free = compile_plan(selection(), [TASK], checkpoint(), PROFILE, now=NOW, command=command)
            self.assertEqual(result["safe_code"], "request_ambiguous")
            self.assertEqual(free.slots, [])

    def test_quoted_titles_do_not_override_explicit_scheduling_day(self):
        task = {**TASK, "title": "Tomorrow 60 minutes review"}
        result, _ = compile_plan(selection(), [task], checkpoint(), PROFILE, now=NOW,
            command='Schedule "Tomorrow 60 minutes review" for 30 minutes today.')
        self.assertEqual(result["scheduled_minutes"], 30)
        self.assertEqual(datetime.fromisoformat(result["blocks"][0]["start"]).astimezone(ZONE).day, 2)

    def test_explicit_indonesian_hour_and_iso_date_are_grounded(self):
        result, _ = compile_plan(selection(), [TASK], checkpoint(), PROFILE, now=NOW,
            command="Jadwalkan selama setengah jam pada 2026-10-04.")
        self.assertEqual(result["scheduled_minutes"], 30)
        self.assertEqual(datetime.fromisoformat(result["blocks"][0]["start"]).astimezone(ZONE).day, 4)

    def test_30_and_60_minutes_are_computed_by_backend(self):
        for minutes in (30, 60):
            with self.subTest(minutes=minutes):
                result, free = self.compile(selection(duration_minutes=minutes))
                self.assertEqual(result["status"], "proposed")
                block = result["blocks"][0]
                self.assertEqual((datetime.fromisoformat(block["end"]) - datetime.fromisoformat(block["start"])).total_seconds(), minutes * 60)
                self.assertEqual(result["scheduled_minutes"], minutes)
                self.assertEqual(free.allocated_minutes, minutes)
                self.assertEqual(block["title"], TASK["title"])

    def test_tomorrow_is_in_user_timezone(self):
        result, _ = self.compile()
        start = datetime.fromisoformat(result["blocks"][0]["start"]).astimezone(ZONE)
        self.assertEqual(start.isoformat(), "2026-10-03T09:00:00+07:00")

    def test_saved_task_estimate_is_used_without_hidden_default(self):
        result, _ = self.compile(selection(duration_minutes=None))
        self.assertEqual(result["requested_minutes"], 30)
        self.assertIn("saved task estimates", result["assumptions"][0])

    def test_explicit_form_duration_and_command_must_agree(self):
        result, free = self.compile(options=checkpoint(duration_minutes=60))
        self.assertEqual(result["safe_code"], "duration_conflict")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["blocks"], [])
        self.assertEqual(free.slots, [])
        result, _ = self.compile(selection(duration_minutes=None), options=checkpoint(duration_minutes=60))
        self.assertEqual(result["scheduled_minutes"], 60)

    def test_missing_or_invalid_duration_asks_a_question(self):
        result, _ = self.compile(selection(duration_minutes=None), [{**TASK, "estimate_minutes": None}])
        self.assertEqual(result["safe_code"], "duration_required")
        for duration in (0, 14, 481):
            result, _ = self.compile(selection(duration_minutes=duration))
            self.assertEqual(result["safe_code"], "duration_out_of_range")

    def test_title_up_to_task_limit_does_not_depend_on_model_copying(self):
        task = {**TASK, "title": "A" * 200}
        result, _ = self.compile(tasks=[task])
        self.assertEqual(result["blocks"][0]["title"], task["title"])

    def test_today_slots_have_write_buffer_and_whole_minute_boundaries(self):
        now = NOW.replace(hour=3, second=17, microsecond=800)
        result, _ = self.compile(selection(day="today"), now=now)
        start = datetime.fromisoformat(result["blocks"][0]["start"])
        self.assertGreaterEqual(start, now + timedelta(minutes=START_BUFFER_MINUTES))
        self.assertEqual((start.second, start.microsecond), (0, 0))

    def test_iso_day_and_clock_range_are_applied_before_slot_selection(self):
        result, _ = self.compile(selection(day="date", date="2026-10-04", start_time="14:00", end_time="15:00"))
        block = result["blocks"][0]
        self.assertEqual(datetime.fromisoformat(block["start"]).astimezone(ZONE).isoformat(), "2026-10-04T14:00:00+07:00")

    def test_busy_time_is_subtracted_inside_requested_day(self):
        options = checkpoint()
        options["calendar"]["events"] = [busy(9, 0, 10, 0, day=3)]
        result, _ = self.compile(options=options)
        self.assertEqual(datetime.fromisoformat(result["blocks"][0]["start"]).astimezone(ZONE).hour, 10)

    def test_full_day_calendar_returns_shortfall_not_invalid_plan(self):
        options = checkpoint()
        options["calendar"]["events"] = [busy(9, 0, 17, 0, day=3)]
        result, free = self.compile(options=options)
        self.assertEqual(result["status"], "insufficient_time")
        self.assertEqual(result["blocks"], [])
        self.assertEqual(free.slots, [])
        self.assertEqual(result["shortfall_minutes"], 30)

    def test_timed_deadline_clips_window_before_allocation(self):
        due = datetime(2026, 10, 3, 9, 20, tzinfo=ZONE)
        task = {**TASK, "due_kind": "datetime", "due_at": due.isoformat()}
        result, _ = self.compile(tasks=[task])
        self.assertEqual(result["status"], "insufficient_time")
        task["due_at"] = due.replace(hour=10).isoformat()
        result, _ = self.compile(tasks=[task])
        self.assertLessEqual(datetime.fromisoformat(result["blocks"][0]["end"]), datetime.fromisoformat(task["due_at"]))

    def test_date_only_and_past_deadlines_are_actionable_clarifications(self):
        result, _ = self.compile(tasks=[{**TASK, "due_kind": "date", "due_date": "2026-10-04"}])
        self.assertEqual(result["safe_code"], "timed_deadline_required")
        result, _ = self.compile(tasks=[{**TASK, "due_kind": "datetime", "due_at": (NOW-timedelta(minutes=1)).isoformat()}])
        self.assertEqual(result["safe_code"], "deadline_passed")

    def test_unknown_task_and_evidence_are_rejected(self):
        for changes, code in (({"task_refs": ["task-999"]}, "unknown_task_reference"),
                              ({"evidence_refs": ["source-999"]}, "unknown_memory_reference")):
            with self.assertRaises(PlanningValidationError) as caught:
                self.compile(selection(**changes))
            self.assertEqual(caught.exception.code, code)

    def test_duplicate_task_refs_are_rejected(self):
        with self.assertRaises(PlanningValidationError):
            self.compile(selection(task_refs=["task-1", "task-1"]))

    def test_extra_model_fields_and_coerced_durations_are_rejected(self):
        for intent in (selection(blocks=[]), selection(duration_minutes="30"), selection(duration_minutes=True)):
            with self.assertRaises(PlanningValidationError) as caught:
                self.compile(intent)
            self.assertEqual(caught.exception.code, "invalid_plan_schema")

    def test_explicit_clock_needs_day_and_valid_range(self):
        result, _ = self.compile(selection(day="any", start_time="14:00"))
        self.assertEqual(result["safe_code"], "scheduling_day_required")
        result, _ = self.compile(selection(start_time="15:00", end_time="14:00"))
        self.assertEqual(result["safe_code"], "invalid_time_constraint")
        with self.assertRaises(PlanningValidationError):
            self.compile(selection(start_time="25:00"))

    def test_past_or_out_of_horizon_dates_are_not_silently_changed(self):
        for value, code in (("2026-10-01", "scheduling_day_passed"), ("2026-10-20", "scheduling_window_exceeded")):
            result, _ = self.compile(selection(day="date", date=value))
            self.assertEqual(result["safe_code"], code)
            self.assertEqual(result["blocks"], [])

    def test_incomplete_calendar_and_changed_timezone_fail_closed(self):
        options = checkpoint()
        options["calendar"]["complete"] = False
        with self.assertRaises(PlanningValidationError) as caught:
            self.compile(options=options)
        self.assertEqual(caught.exception.code, "calendar_snapshot_incomplete")
        options = checkpoint(timezone="UTC")
        with self.assertRaises(PlanningValidationError) as caught:
            self.compile(options=options)
        self.assertEqual(caught.exception.code, "profile_changed")

    def test_multiple_tasks_use_estimates_and_cannot_overlap(self):
        task2 = {**TASK, "id": str(uuid4()), "title": "Read demo notes", "estimate_minutes": 60}
        result, free = self.compile(selection(task_refs=["task-1", "task-2"], duration_minutes=90), [TASK, task2])
        self.assertEqual(result["scheduled_minutes"], 90)
        first, second = result["blocks"]
        self.assertLessEqual(datetime.fromisoformat(first["end"]), datetime.fromisoformat(second["start"]))
        self.assertEqual(len(free.slots), 2)
        result, _ = self.compile(selection(task_refs=["task-1", "task-2"], duration_minutes=30), [TASK, task2])
        self.assertEqual(result["safe_code"], "task_duration_conflict")

    def test_split_blocks_are_each_at_least_15_minutes(self):
        profile = PROFILE.model_copy(update={"working_hours": WorkingHours(days=[5], start_minute=540, end_minute=660)})
        options = checkpoint(allow_split=True)
        options["calendar"]["events"] = [busy(9, 20, 10, 0), busy(10, 15, 11, 0)]
        result, _ = self.compile(selection(day="today"), options=options, profile=profile)
        self.assertEqual(result["status"], "proposed")
        lengths = [(datetime.fromisoformat(block["end"])-datetime.fromisoformat(block["start"])).total_seconds()/60 for block in result["blocks"]]
        self.assertEqual(lengths, [15, 15])
        options["allow_split"] = False
        result, _ = self.compile(selection(day="today"), options=options, profile=profile)
        self.assertEqual(result["status"], "insufficient_time")

    def test_model_clarification_has_no_slots_or_blocks(self):
        result, free = self.compile(selection(status="needs_clarification", task_refs=[], questions=["Which demo task?"]))
        self.assertEqual(result["questions"], ["Which demo task?"])
        self.assertEqual(result["blocks"], [])
        self.assertEqual(free.slots, [])


if __name__ == "__main__":
    unittest.main()
