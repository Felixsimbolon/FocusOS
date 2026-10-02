import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

from focusos_api.agent_continuation import AgentRunState, _planning_step
from focusos_api.agent_planner import PlanningModelError, select_planning_intent
from test_planning_compiler import NOW, PROFILE, TASK, checkpoint, selection


def run():
    return AgentRunState(id=uuid4(), command="Schedule the checklist for 30 minutes tomorrow",
        status="waiting", stage="planning", version=2, model_turns=0, tool_calls_count=4,
        checkpoint={**checkpoint(), "tasks": [TASK]},
        expires_at=datetime.now(timezone.utc)+timedelta(minutes=10), updated_at=datetime.now(timezone.utc))


class PlannerTests(unittest.TestCase):
    def select(self):
        return select_planning_intent("Schedule for 30 minutes tomorrow", [TASK], {"matches": []},
            reference_time=NOW.isoformat(), timezone_name="Asia/Jakarta", duration_minutes=None, allow_split=False)

    def test_model_receives_bounded_handles_without_slot_arithmetic_or_tools(self):
        response = Mock(content=b"ok")
        response.json.return_value = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(selection())}]}}]}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), patch("focusos_api.gemini.httpx.post", return_value=response) as post:
            self.assertEqual(self.select(), selection())
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["generationConfig"]["responseFormat"]["text"]["mimeType"], "APPLICATION_JSON")
        self.assertNotIn("tools", payload)
        context = json.loads(payload["contents"][0]["parts"][0]["text"])
        self.assertEqual(context["form_duration_minutes"], None)
        self.assertEqual(context["timezone"], "Asia/Jakarta")
        self.assertEqual(context["tasks"][0]["ref"], "task-1")
        self.assertNotIn("slots", context)
        schema = payload["generationConfig"]["responseFormat"]["text"]["schema"]
        for field in ("blocks", "scheduled_minutes", "shortfall_minutes", "summary"):
            self.assertNotIn(field, schema["properties"])

    def test_missing_key_fails_closed(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}), patch("focusos_api.gemini.httpx.post") as post:
            with self.assertRaises(PlanningModelError):
                self.select()
        post.assert_not_called()

    def test_timeout_and_malformed_json_have_distinct_safe_errors(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), patch("focusos_api.gemini.httpx.post", side_effect=httpx.ReadTimeout("secret request")):
            with self.assertRaises(PlanningModelError) as caught:
                self.select()
        self.assertEqual(caught.exception.code, "planning_timeout")
        response = Mock(content=b"ok")
        response.json.return_value = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not json"}]}}]}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), patch("focusos_api.gemini.httpx.post", return_value=response):
            with self.assertRaises(PlanningModelError) as caught:
                self.select()
        self.assertEqual(caught.exception.code, "invalid_plan_schema")

    def test_success_checkpoint_contains_the_same_server_slots_as_result(self):
        initial = run()
        leased = initial.model_copy(update={"version": 3, "status": "running"})
        done = leased.model_copy(update={"version": 4, "status": "succeeded"})
        with patch("focusos_api.agent_continuation.load_command_run", side_effect=[leased, done]), \
             patch("focusos_api.agent_continuation._checkpoint", return_value=True) as save, \
             patch("focusos_api.agent_continuation.read_profile", return_value=PROFILE), \
             patch("focusos_api.agent_continuation.select_planning_intent", return_value=selection()), \
             patch("focusos_api.planning_compiler.datetime") as clock:
            clock.now.return_value = NOW
            clock.fromisoformat.side_effect = datetime.fromisoformat
            self.assertEqual(_planning_step("session", initial), done)
        final = save.call_args_list[-1].args
        self.assertEqual(final[3], "succeeded")
        self.assertFalse(final[6]["actionable"])
        self.assertEqual(final[5]["resolved_duration_minutes"], 30)
        self.assertEqual(datetime.fromisoformat(final[5]["free_time"]["slots"][0]["start"]),
                         datetime.fromisoformat(final[6]["blocks"][0]["start"]))

    def test_bad_task_reference_is_saved_as_specific_failure(self):
        initial = run()
        leased = initial.model_copy(update={"version": 3, "status": "running"})
        done = leased.model_copy(update={"version": 4, "status": "failed"})
        with patch("focusos_api.agent_continuation.load_command_run", side_effect=[leased, done]), \
             patch("focusos_api.agent_continuation._checkpoint", return_value=True) as save, \
             patch("focusos_api.agent_continuation.read_profile", return_value=PROFILE), \
             patch("focusos_api.agent_continuation.select_planning_intent", return_value=selection(task_refs=["task-999"])):
            self.assertEqual(_planning_step("session", initial), done)
        final = save.call_args_list[-1].args
        self.assertEqual(final[3], "failed")
        self.assertEqual(final[6], None)
        self.assertEqual(final[9], "unknown_task_reference")

    def test_no_active_tasks_is_clarification_without_model_call(self):
        initial = run()
        initial.checkpoint["tasks"] = []
        leased = initial.model_copy(update={"version": 3, "status": "running"})
        done = leased.model_copy(update={"version": 4, "status": "clarify"})
        with patch("focusos_api.agent_continuation.load_command_run", side_effect=[leased, done]), \
             patch("focusos_api.agent_continuation._checkpoint", return_value=True) as save, \
             patch("focusos_api.agent_continuation.read_profile", return_value=PROFILE), \
             patch("focusos_api.agent_continuation.select_planning_intent") as model:
            _planning_step("session", initial)
        model.assert_not_called()
        self.assertEqual(save.call_args_list[-1].args[6]["safe_code"], "task_required")


if __name__ == "__main__":
    unittest.main()
