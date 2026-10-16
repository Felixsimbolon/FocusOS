"""Conflict detection and moving a block. Calendar and database are simulated."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from focusos_api.calendar_conflicts import RescheduleUnavailable, overlaps, start_reschedule
from focusos_api.unified_commands import WorkIntent

NOW = datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)


def block(start_hours, minutes=60, task_id=None, title="Write report"):
    start = NOW + timedelta(hours=start_hours)
    end = start + timedelta(minutes=minutes)
    return {"id": str(uuid4()), "task_id": task_id, "event_id": "focusos" + uuid4().hex[:8], "provider_event_id": None,
            "status": "succeeded", "cancellation_status": None, "start": start, "end": end,
            "payload": {"title": title, "start": start.isoformat(), "end": end.isoformat(), "timezone": "Asia/Jakarta"}}


def event(provider_id, start_hours, minutes=30, kind="timed"):
    start = NOW + timedelta(hours=start_hours)
    return SimpleNamespace(provider_id=provider_id, kind=kind, start_at=start, end_at=start + timedelta(minutes=minutes),
                           start_date=None, end_date_exclusive=None, timezone=None)


class OverlapTests(unittest.TestCase):
    def test_only_other_timed_events_that_overlap_are_conflicts(self):
        clashing, clear = block(2), block(5)
        own = {clashing["event_id"], clear["event_id"]}
        found = overlaps([clashing, clear], [
            event("meeting", 2.5),                       # overlaps the first block
            event(clashing["event_id"], 2),              # the block itself
            event("lunch", 4),                           # ends before the second block
            event("touching", 3),                        # starts exactly when the first block ends
        ], own)
        self.assertEqual([item["id"] for item in found], [clashing["id"]])
        self.assertEqual(len(found[0]["conflicts"]), 1)

    def test_all_day_events_are_not_conflicts(self):
        item = block(2)
        holiday = event("holiday", 0, kind="all_day")
        with patch("focusos_api.calendar_conflicts.occurrence_interval", return_value=(NOW, NOW + timedelta(days=1))):
            self.assertEqual(overlaps([item], [holiday], {item["event_id"]}), [])


class RescheduleTests(unittest.TestCase):
    def start(self, upcoming, task=None):
        rpc = MagicMock(return_value={"id": str(uuid4()), "status": "pending", "version": 1})
        checkpoint = MagicMock(return_value=True)
        with patch("focusos_api.calendar_conflicts._upcoming", return_value=upcoming), \
             patch("focusos_api.calendar_conflicts._task", return_value=task), \
             patch("focusos_api.calendar_conflicts._rpc", rpc), patch("focusos_api.calendar_conflicts._checkpoint", checkpoint), \
             patch("focusos_api.calendar_conflicts.enqueue_job", return_value=SimpleNamespace(model_dump=lambda **_: {"id": "job"})):
            result = start_reschedule("session", upcoming[0]["id"] if upcoming else uuid4(), uuid4(), NOW)
        return result, rpc.call_args.args[2], checkpoint.call_args.args[5]

    def test_activity_block_is_moved_with_a_prepared_plan_and_no_model_call(self):
        item = block(2, 45, title="Belajar Python 13:00")
        _, run, saved = self.start([item])
        intent = WorkIntent.model_validate(saved["work_plan"])
        schedule = intent.schedules[0]
        self.assertEqual((schedule.target, schedule.title_quote), ("activity", "Belajar Python 13:00"))
        self.assertIn("Belajar Python 13:00", run["p_command"])
        self.assertEqual(schedule.selection.duration_minutes, 45)
        self.assertEqual(saved["replaces_approval_id"], item["id"])
        # A clock time in the title must not become a scheduling limit.
        self.assertEqual(saved["constraint_override"], "45 minutes")

    def test_task_block_is_moved_as_the_saved_task(self):
        task = {"id": str(uuid4()), "title": "Write report", "due_kind": "none", "due_date": None, "due_at": None,
                "estimate_minutes": 60, "source_id": None, "priority": "high", "project_id": None}
        item = block(2, task_id=task["id"])
        _, _, saved = self.start([item], task)
        schedule = WorkIntent.model_validate(saved["work_plan"]).schedules[0]
        self.assertEqual((schedule.target, schedule.selection.task_refs), ("existing", ["task-1"]))
        self.assertEqual(saved["intent_tasks"], [task])

    def test_only_upcoming_blocks_of_a_movable_length_can_move(self):
        with self.assertRaises(RescheduleUnavailable):
            self.start([])
        with self.assertRaises(RescheduleUnavailable):
            self.start([block(2, minutes=10)])


class ReplaceAfterSuccessTests(unittest.TestCase):
    def test_old_block_is_removed_only_after_a_new_one_exists(self):
        from focusos_api.unified_commands import _finalize
        run = SimpleNamespace(id=uuid4(), version=1, status="succeeded", model_turns=0,
                              checkpoint={"replaces_approval_id": str(uuid4())})
        intent = WorkIntent(capture=False, questions=[], schedules=[], clarification=None, explanation="Move.")
        with patch("focusos_api.unified_commands.cancel_focus_block", return_value={"status": "cancelled"}) as cancel:
            step = _finalize("session", run, intent, {}, {"blocks": [{"title": "x"}], "schedules": [{"title": "x", "status": "scheduled"}]})
        cancel.assert_called_once()
        self.assertEqual(step.result["replaced"], "cancelled")
        with patch("focusos_api.unified_commands.cancel_focus_block") as never:
            failed = _finalize("session", run, intent, {}, {"blocks": [], "schedules": [{"title": "x", "status": "failed", "code": "insufficient_time", "message": "No time."}]})
        never.assert_not_called()
        self.assertEqual(failed.status, "failed")
        with patch("focusos_api.unified_commands.cancel_focus_block", side_effect=RuntimeError("provider")):
            kept = _finalize("session", run, intent, {}, {"blocks": [{"title": "x"}], "schedules": [{"title": "x", "status": "scheduled"}]})
        self.assertEqual(kept.result["replaced"], "unknown")
        self.assertIn("could not be removed", kept.result["warning"])


if __name__ == "__main__":
    unittest.main()
