import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from focusos_api.agent_continuation import AgentRunState, continue_staged_run, list_run_tools
from focusos_api.main import app


def state(stage="start", count=0):
    return AgentRunState(id=uuid4(), command="Find work time", status="waiting", stage=stage, version=2,
        model_turns=0, tool_calls_count=count, checkpoint={"duration_minutes": 60, "allow_split": False},
        expires_at=datetime.now(timezone.utc)+timedelta(minutes=10),
        updated_at=datetime.now(timezone.utc))


class ContinuationTests(unittest.TestCase):
    def test_one_stage_advances_and_persists_count(self):
        run = state()
        next_run = run.model_copy(update={"stage": "tasks", "version": 3, "tool_calls_count": 1})
        with patch("focusos_api.agent_continuation.load_command_run", side_effect=[run, next_run]), \
             patch("focusos_api.agent_continuation._task_step",
                   return_value=({"duration_minutes": 60, "tasks": []}, 1)), \
             patch("focusos_api.agent_continuation._checkpoint", return_value=True) as save:
            result = continue_staged_run("session", run.id)
        self.assertEqual(result.stage, "tasks")
        self.assertEqual(save.call_args.args[4], "tasks")
        self.assertEqual(save.call_args.args[8], 1)

    def test_calendar_error_marks_run_failed_without_fake_slots(self):
        run = state("tasks", 1)
        with patch("focusos_api.agent_continuation.load_command_run", return_value=run), \
             patch("focusos_api.agent_continuation._calendar_step",
                   side_effect=__import__("focusos_api.calendar_fetch", fromlist=["CalendarFetchError"]).CalendarFetchError()), \
             patch("focusos_api.agent_continuation._checkpoint", return_value=True) as save:
            with self.assertRaises(Exception):
                continue_staged_run("session", run.id)
        self.assertEqual(save.call_args.args[3], "failed")
        self.assertEqual(save.call_args.args[6], None)

    def test_planning_stage_does_not_run_another_tool(self):
        run = state("planning", 3)
        with patch("focusos_api.agent_continuation.load_command_run", return_value=run), \
             patch("focusos_api.agent_continuation._planning_step", return_value=run) as plan:
            self.assertEqual(continue_staged_run("session", run.id), run)
        plan.assert_called_once()

    def test_tool_trace_requires_owned_run_before_query(self):
        run = state()
        with patch("focusos_api.agent_continuation.load_command_run", side_effect=__import__("focusos_api.database", fromlist=["DatabaseUnavailable"]).DatabaseUnavailable("missing")), \
             patch("focusos_api.agent_continuation.scoped_client") as scoped:
            with self.assertRaises(Exception): list_run_tools("session", run.id)
        scoped.assert_not_called()

    def test_anonymous_run_routes(self):
        client = TestClient(app)
        run_id = uuid4()
        self.assertEqual(client.post("/agent/runs", json={"request_key": str(uuid4()), "command": "Plan"}).status_code, 401)
        self.assertEqual(client.get(f"/agent/runs/{run_id}").status_code, 401)
        self.assertEqual(client.post(f"/agent/runs/{run_id}/continue").status_code, 401)
        self.assertEqual(client.get(f"/agent/runs/{run_id}/tools").status_code, 401)


if __name__ == "__main__":
    unittest.main()
