"""Bounded spaced-session regressions. Providers/DB are simulated; no live writes."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from focusos_api.approval_payload import CalendarAction, canonical_action_hash
from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.calendar_fetch import CalendarWindow
from focusos_api.planning_compiler import compile_plan
from focusos_api.planning_contract import PlanningValidationError, validate_planning_response
from focusos_api.planning_selection import SessionSelection
from focusos_api.profiles import WorkingHours
from focusos_api.session_constraints import grounded_sessions
from focusos_api.unified_commands import WorkIntent, infer_work
from test_planning_compiler import NOW as WORKER_NOW, PROFILE, TASK, selection
from test_unified_commands import UnifiedHarness, intent


def session_intent(**changes):
    base = intent()
    return WorkIntent.model_validate({**base.model_dump(), "selection": {**base.selection.model_dump(), **changes}})

NOW = datetime(2026, 10, 9, 1, tzinfo=timezone.utc)
ZONE = ZoneInfo("Asia/Jakarta")
COMMAND = ("aku ada tugas buat bikin web ya dl tanggal 18 bulan ini , aku mau kamu schedule 2 hari "
    "di span tanggal 13-16 bikin tiap hari schedule nya 2 jam untuk ngerjain tugas ini, "
    "aku gamau ada schedule ngerjain web ini di 2 hari yang berturut turut minimal longkap satu hari")
REQUEST = {"count": 2, "minutes": 120, "date_start": "2026-10-13", "date_end": "2026-10-16", "min_days_between": 2}


def blocked(day, start=9, end=17):
    return {"id": f"busy-{day}-{start}", "title": "Busy",
        "start": datetime(2026, 10, day, start, tzinfo=ZONE).isoformat(),
        "end": datetime(2026, 10, day, end, tzinfo=ZONE).isoformat()}


def checkpoint(events=(), end_day=17):
    return {"duration_minutes": None, "allow_split": False, "window_start": NOW.isoformat(),
        "timezone": PROFILE.timezone, "memory_search": {"matches": []},
        "calendar": {"complete": True, "timezone": PROFILE.timezone,
            "start": datetime(2026, 10, 13, tzinfo=ZONE).isoformat(),
            "end": datetime(2026, 10, end_day, tzinfo=ZONE).isoformat(),
            "fetched_at": NOW.isoformat(), "events": list(events)}}


class SpacedSessionTests(unittest.TestCase):
    def plan(self, events=(), request=None, task=None, profile=PROFILE, command=None, options=None):
        return compile_plan(selection(day="any", duration_minutes=120, sessions=request or REQUEST),
            [task or {**TASK, "title": "Build the website", "due_kind": "date", "due_date": "2026-10-18"}],
            options or checkpoint(events), profile, now=NOW, command=command)

    def days(self, result):
        return [datetime.fromisoformat(b["start"]).astimezone(ZONE).day for b in result["blocks"]]

    def test_actual_user_command_is_grounded_with_per_session_duration_and_gap(self):
        self.assertEqual(grounded_sessions(COMMAND, NOW.isoformat(), PROFILE.timezone).model_dump(), REQUEST)
        result, _ = compile_plan(selection(day="tomorrow", duration_minutes=30), [TASK], checkpoint(), PROFILE, now=NOW, command=COMMAND)
        self.assertEqual(self.days(result), [13, 15])
        self.assertEqual(result["scheduled_minutes"], 240)

    def test_two_full_sessions_use_earliest_nonconsecutive_dates(self):
        result, free = self.plan()
        self.assertEqual(self.days(result), [13, 15])
        self.assertEqual((result["requested_minutes"], free.allocated_minutes, free.shortfall_minutes), (240, 240, 0))
        self.assertNotIn("warning", result)
        for block in result["blocks"]:
            self.assertEqual((datetime.fromisoformat(block["end"]) - datetime.fromisoformat(block["start"])).total_seconds(), 7200)

    def test_blocked_first_date_uses_fourteenth_and_sixteenth(self):
        result, _ = self.plan([blocked(13)])
        self.assertEqual(self.days(result), [14, 16])

    def test_only_adjacent_days_available_creates_one_and_warns(self):
        result, free = self.plan([blocked(15), blocked(16)])
        self.assertEqual(self.days(result), [13])
        self.assertEqual(result["status"], "proposed")
        self.assertEqual((result["requested_sessions"], result["planned_sessions"], free.shortfall_minutes), (2, 1, 120))
        self.assertIn("Only 1 of 2", result["warning"])

    def test_only_last_date_available_is_still_saved(self):
        result, _ = self.plan([blocked(d) for d in (13, 14, 15)])
        self.assertEqual(self.days(result), [16])
        self.assertEqual(result["shortfall_minutes"], 120)

    def test_no_full_slot_returns_zero_blocks(self):
        result, free = self.plan([blocked(d) for d in range(13, 17)])
        self.assertEqual(result["status"], "insufficient_time")
        self.assertEqual(result["blocks"], [])
        self.assertEqual(free.shortfall_minutes, 240)

    def test_short_fragments_are_not_combined_across_days(self):
        result, _ = self.plan([blocked(d, 10, 17) for d in range(13, 17)])
        self.assertEqual(result["status"], "insufficient_time")
        self.assertEqual(result["blocks"], [])

    def test_task_deadline_limits_sessions(self):
        result, _ = self.plan(task={**TASK, "due_kind": "date", "due_date": "2026-10-14"})
        self.assertEqual(self.days(result), [13])
        self.assertEqual(result["shortfall_minutes"], 120)

    def test_working_days_and_hours_are_respected(self):
        profile = PROFILE.model_copy(update={"working_hours": WorkingHours(days=[2, 4], start_minute=780, end_minute=960)})
        result, _ = self.plan(profile=profile)
        self.assertEqual(self.days(result), [13, 15])
        self.assertTrue(all(datetime.fromisoformat(b["start"]).astimezone(ZONE).hour == 13 for b in result["blocks"]))

    def test_incomplete_range_cannot_be_presented_as_partial_availability(self):
        with self.assertRaises(PlanningValidationError) as caught:
            self.plan(options=checkpoint(end_day=16))
        self.assertEqual(caught.exception.code, "calendar_snapshot_incomplete")

    def test_larger_day_gap_is_supported(self):
        result, _ = self.plan(request={**REQUEST, "min_days_between": 3})
        self.assertEqual(self.days(result), [13, 16])

    def test_iso_range_is_not_mistaken_for_single_day(self):
        command = "schedule 2 sessions tanggal 2026-10-13 - 2026-10-16 each session 2 hours skip one day"
        result, _ = self.plan(command=command)
        self.assertEqual(self.days(result), [13, 15])

    def test_schema_rejects_invalid_unbounded_and_coerced_values(self):
        for change in ({"count": 0}, {"count": 8}, {"minutes": 14}, {"minutes": True},
                       {"min_days_between": 0}, {"date_end": "2026-10-12"},
                       {"date_end": "2026-11-01"}, {"date_start": "2026-02-30"},
                       {"count": 7, "minutes": 480}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                SessionSelection.model_validate({**REQUEST, **change})

    def test_numeric_month_uses_reference_and_different_month_is_not_forced(self):
        value = grounded_sessions(COMMAND, "2026-11-09T01:00:00+00:00", PROFILE.timezone)
        self.assertEqual(value.date_start, "2026-11-13")
        self.assertIsNone(grounded_sessions(COMMAND.replace("bulan ini", "bulan depan"), NOW.isoformat(), PROFILE.timezone))

    def test_intent_provider_cannot_drop_explicit_spaced_session_details(self):
        value = session_intent(day="any", duration_minutes=120, start_time=None, end_time=None).model_dump()
        value["title_quote"] = "bikin web"
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]}
        with patch("focusos_api.unified_commands.api_key", return_value="synthetic-key"), patch("focusos_api.unified_commands.request", return_value=response):
            result = infer_work(COMMAND, [], NOW.isoformat(), PROFILE.timezone)
        self.assertEqual(result.selection.sessions.model_dump(), REQUEST)

    def test_partial_validation_requires_explicit_opt_in(self):
        result, free = self.plan([blocked(15), blocked(16)])
        candidate = {key: result[key] for key in ("schema_version", "status", "task_refs", "requested_minutes",
            "scheduled_minutes", "shortfall_minutes", "assumptions", "questions", "summary")}
        candidate["blocks"] = [{key: block[key] for key in ("slot_ref", "task_ref", "title", "reason", "evidence_refs")} for block in result["blocks"]]
        tasks = [{**TASK, "title": "Build the website", "due_kind": "date", "due_date": "2026-10-18"}]
        with self.assertRaises(PlanningValidationError):
            validate_planning_response(candidate, tasks, free)
        self.assertEqual(validate_planning_response(candidate, tasks, free, allow_partial=True)["scheduled_minutes"], 120)


class MultiBlockHarness(UnifiedHarness):
    def __init__(self):
        super().__init__()
        self.approvals = {}
        self.busy_days = []

    def calendar(self, _, start, end):
        events = tuple({"id": f"busy-{d}", "summary": "Busy", "status": "confirmed",
            "start": {"dateTime": datetime(2026, 10, d, 9, tzinfo=ZONE).isoformat()},
            "end": {"dateTime": datetime(2026, 10, d, 17, tzinfo=ZONE).isoformat()}} for d in self.busy_days)
        return CalendarWindow(start, end, WORKER_NOW + timedelta(seconds=1), "primary", PROFILE.timezone, events)

    def proposal_rpc(self, _, name, args):
        index = args["p_block_index"]
        if index not in self.approvals:
            block = self.run.result["blocks"][index]
            aid = uuid4()
            action = CalendarAction(run_id=self.run.id, block_index=index, task_id=None, task_version=None,
                connection_id=self.connection.id, event_id="f" + aid.hex, title=block["title"],
                start=block["start"], end=block["end"], timezone=PROFILE.timezone)
            self.approvals[index] = ApprovalRecord(id=aid, run_id=self.run.id, block_index=index,
                task_id=None, connection_id=self.connection.id, calendar_id="primary", event_id=action.event_id,
                payload=action, payload_hash=canonical_action_hash(action), status="approved", authorization_mode="automatic",
                status_version=1, expires_at=WORKER_NOW + timedelta(minutes=20), created_at=WORKER_NOW, updated_at=WORKER_NOW)
        self.approval = self.approvals[index]
        return self.approval.model_dump(mode="json")

    def service_rpc(self, name, args):
        result = super().service_rpc(name, args)
        self.approvals[self.approval.block_index] = self.approval
        return result


class MultiSessionWorkerTests(unittest.TestCase):
    def setUp(self):
        self.h = MultiBlockHarness().enter()
        self.addCleanup(self.h.close)
        clock = self.h.stack.enter_context(patch("focusos_api.unified_commands.datetime"))
        clock.now.return_value = WORKER_NOW
        clock.fromisoformat.side_effect = datetime.fromisoformat
        self.h.work_intent = session_intent(day="any", duration_minutes=120, start_time=None, end_time=None,
            sessions={**REQUEST, "date_start": "2026-10-03", "date_end": "2026-10-06"})

    def test_worker_writes_each_session_once_and_replay_does_not_duplicate(self):
        step, job = self.h.drain(self.h.start("Schedule learning Python in two spaced sessions"))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(step.result["blocks_scheduled"], 2)
        self.assertEqual(self.h.insert_count, 2)
        self.assertEqual([datetime.fromisoformat(b["start"]).astimezone(ZONE).day for b in step.result["blocks"]], [3, 5])
        self.assertTrue(all(b["link"] for b in step.result["blocks"]))
        replay, _ = self.h.drain(job)
        self.assertEqual(replay.status, "succeeded")
        self.assertEqual(self.h.insert_count, 2)

    def test_worker_creates_available_session_and_preserves_shortfall_warning(self):
        self.h.busy_days = [5, 6]
        step, _ = self.h.drain(self.h.start("Schedule learning Python in two spaced sessions"))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(self.h.insert_count, 1)
        self.assertEqual(step.result["blocks_scheduled"], 1)
        self.assertIn("Only 1 of 2", step.result["warning"])
        self.assertEqual(step.result["shortfall_minutes"], 120)

    def test_worker_explains_session_dates_outside_supported_horizon(self):
        self.h.work_intent = session_intent(day="any", duration_minutes=120, start_time=None, end_time=None,
            sessions={**REQUEST, "date_start": "2026-10-20", "date_end": "2026-10-22"})
        step, _ = self.h.drain(self.h.start("Schedule learning Python in two spaced sessions"))
        self.assertEqual(step.status, "failed")
        self.assertIn("fourteen days", step.result["message"])
        self.assertEqual(self.h.insert_count, 0)

    def test_worker_without_available_session_never_writes_calendar(self):
        self.h.busy_days = [3, 4, 5, 6]
        step, _ = self.h.drain(self.h.start("Schedule learning Python in two spaced sessions"))
        self.assertEqual(step.status, "failed")
        self.assertEqual(self.h.insert_count, 0)
