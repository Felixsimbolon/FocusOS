import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from focusos_api.automatic_calendar import AutomaticCalendarUnavailable, schedule_automatic_block
from focusos_api.main import app


class AutomaticCalendarTests(unittest.TestCase):
    def test_old_run_cannot_schedule_without_auto_consent(self):
        run_id = uuid4()
        run = SimpleNamespace(checkpoint={}, status="succeeded", result={"status": "proposed", "blocks": [{}]})
        with patch("focusos_api.automatic_calendar.load_command_run", return_value=run), \
             patch("focusos_api.automatic_calendar.propose_calendar_event") as propose:
            with self.assertRaises(AutomaticCalendarUnavailable):
                schedule_automatic_block("session", run_id, 0)
        propose.assert_not_called()

    def test_invalid_block_cannot_reach_proposal(self):
        run_id = uuid4()
        run = SimpleNamespace(checkpoint={"auto_calendar": True}, status="succeeded",
                              result={"status": "proposed", "blocks": [{}]})
        with patch("focusos_api.automatic_calendar.load_command_run", return_value=run), \
             patch("focusos_api.automatic_calendar.propose_calendar_event") as propose:
            with self.assertRaises(AutomaticCalendarUnavailable):
                schedule_automatic_block("session", run_id, 1)
        propose.assert_not_called()

    def test_automatic_replay_uses_existing_approval_without_new_authorization(self):
        run_id = uuid4()
        run = SimpleNamespace(checkpoint={"auto_calendar": True}, status="succeeded",
                              result={"status": "proposed", "blocks": [{}]})
        approval = SimpleNamespace(id=uuid4(), run_id=run_id, block_index=0,
                                   authorization_mode="automatic", status="succeeded")
        with patch("focusos_api.automatic_calendar.load_command_run", return_value=run), \
             patch("focusos_api.automatic_calendar.propose_calendar_event", return_value=approval), \
             patch("focusos_api.automatic_calendar._rpc") as authorize, \
             patch("focusos_api.automatic_calendar.execute_approval") as execute:
            result = schedule_automatic_block("session", run_id, 0)
        self.assertIs(result, approval)
        authorize.assert_not_called()
        execute.assert_not_called()

    def test_anonymous_auto_route_is_denied(self):
        run_id = uuid4()
        result = TestClient(app).post(f"/agent/runs/{run_id}/blocks/0/auto")
        self.assertEqual(result.status_code, 401)


if __name__ == "__main__":
    unittest.main()