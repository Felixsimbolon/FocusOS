import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from focusos_api.agent_model import AgentModelError, first_tasks_turn
from focusos_api.agent_tasks import CommandInput, run_tasks_command
from focusos_api.main import app


class AgentTasksTests(unittest.TestCase):
    def test_model_accepts_one_allowed_function(self):
        data = {"id": "response1", "status": "completed", "output": [
            {"type": "function_call", "name": "tasks_list", "call_id": "call1",
             "arguments": '{"status":"open","limit":2}'}]}
        with patch("focusos_api.agent_model._request", return_value=data):
            _, call_id, args, _ = first_tasks_turn("What is due?")
        self.assertEqual(call_id, "call1")
        self.assertEqual(args["limit"], 2)

    def test_unknown_model_function_rejected(self):
        data = {"status": "completed", "output": [
            {"type": "function_call", "name": "calendar_create_event", "call_id": "call1",
             "arguments": "{}"}]}
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

    def test_anonymous_route_denied(self):
        self.assertEqual(TestClient(app).post("/agent/runs/tasks",
            json={"request_key": str(uuid4()), "command": "What tasks are due?"}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
