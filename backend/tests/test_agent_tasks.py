import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from focusos_api.agent_model import AgentModelError, first_tasks_turn, finish_tasks_turn
from focusos_api.agent_tasks import CommandInput, run_tasks_command
from focusos_api.main import app


class AgentTasksTests(unittest.TestCase):
    def test_model_accepts_one_allowed_function(self):
        data = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"functionCall": {"name": "tasks_list", "id": "call1", "args": {"status": "open", "limit": 2}}}]}}]}
        with patch("focusos_api.agent_model._request", return_value=data):
            _, call_id, args, _ = first_tasks_turn("What is due?")
        self.assertEqual(call_id, "call1")
        self.assertEqual(args["limit"], 2)

    def test_unknown_model_function_rejected(self):
        data = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"functionCall": {"name": "calendar_create_event", "id": "call1", "args": {}}}]}}]}
        with patch("focusos_api.agent_model._request", return_value=data):
            with self.assertRaises(AgentModelError):
                first_tasks_turn("Create event")

    def test_roundtrip_uses_actual_owned_task_data(self):
        run_id = uuid4()
        task = Mock(id=uuid4(), title="Submit slides", due_kind="date",
                    due_date=None, due_at=None, source_id=None)
        with patch("focusos_api.agent_tasks._rpc", return_value={"id": str(run_id), "status": "pending", "version": 1}), \
             patch("focusos_api.agent_tasks._checkpoint", return_value=True) as checkpoint, \
             patch("focusos_api.agent_tasks._log") as log, \
             patch("focusos_api.agent_tasks.first_tasks_turn",
                   return_value=("response1", "call1", {"status": "open", "limit": 2}, [])), \
             patch("focusos_api.agent_tasks.list_tasks", return_value=Mock(tasks=[task], truncated=False)), \
             patch("focusos_api.agent_tasks.finish_tasks_turn") as finish:
            result = run_tasks_command("session", CommandInput(request_key=uuid4(), command="What is due?"))
        self.assertEqual(result.tasks[0]["title"], "Submit slides")
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(log.call_count, 2)
        self.assertEqual(finish.call_args.args[3]["tasks"][0]["title"], "Submit slides")
        self.assertEqual(checkpoint.call_args.args[3], "succeeded")

    def test_gemini_tool_roundtrip_preserves_thought_signature(self):
        first = Mock(content=b"{}")
        signed_part = {"functionCall": {"name": "tasks_list", "id": "call1",
                        "args": {"status": "open", "limit": 2}},
                       "thoughtSignature": "synthetic-signature"}
        first.json.return_value = {"candidates": [{"finishReason": "STOP",
                                   "content": {"parts": [signed_part]}}]}
        second = Mock(content=b"{}")
        second.json.return_value = {"candidates": [{"finishReason": "STOP",
                                    "content": {"parts": [{"text": "Two tasks"}]}}]}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "synthetic-key"}), patch(
            "focusos_api.gemini.httpx.post", side_effect=[first, second]
        ) as post:
            _, call_id, args, output = first_tasks_turn("What is due?")
            finish_tasks_turn("What is due?", output, call_id, {"tasks": []})
        self.assertEqual(args["limit"], 2)
        payload = post.call_args_list[1].kwargs["json"]
        self.assertEqual(payload["contents"][1]["parts"][0], signed_part)
        self.assertEqual(payload["contents"][2]["parts"][0]["functionResponse"]["id"], call_id)
        self.assertEqual(payload["toolConfig"]["functionCallingConfig"]["mode"], "NONE")

    def test_anonymous_route_denied(self):
        self.assertEqual(TestClient(app).post("/agent/runs/tasks",
            json={"request_key": str(uuid4()), "command": "What tasks are due?"}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
