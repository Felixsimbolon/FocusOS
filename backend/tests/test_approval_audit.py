import unittest
from uuid import uuid4
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch, call

from fastapi.testclient import TestClient

from focusos_api.approval_audit import _state, read_run_action_audit
from focusos_api.agent_continuation import CommandRunNotFound
from focusos_api.database import DatabaseUnavailable
from focusos_api.main import app


class ActionAuditTests(unittest.TestCase):
    def test_state_uses_persisted_outcomes(self):
        cases = [
            (0, [], "no_proposal"),
            (2, [], "awaiting_proposals"),
            (2, ["pending", "approved"], "approved_not_executed"),
            (2, ["succeeded", "pending"], "partially_completed"),
            (2, ["succeeded", "unknown"], "unknown"),
            (2, ["succeeded", "executing"], "executing"),
            (2, ["rejected", "pending"], "blocked"),
            (2, ["succeeded", "failed"], "partially_completed"),
            (2, ["succeeded", "succeeded"], "completed"),
        ]
        for expected, statuses, result in cases:
            with self.subTest(statuses=statuses):
                self.assertEqual(_state(expected, statuses), result)

    def test_audit_uses_owned_run_and_rls_without_ungranted_user_id_filter(self):
        run_id = uuid4()
        client = Mock()
        query = client.table.return_value.select.return_value
        query.eq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value.data = []
        @contextmanager
        def scoped(_token):
            yield ("owner", client)
        with patch("focusos_api.approval_audit.load_command_run",
                   return_value=SimpleNamespace(status="succeeded", result={"status": "proposed", "blocks": [{}]})), \
             patch("focusos_api.approval_audit.list_approvals", return_value=[]), \
             patch("focusos_api.approval_audit.list_run_tools", return_value=[]), \
             patch("focusos_api.approval_audit.scoped_client", scoped):
            result = read_run_action_audit("session", run_id)
        self.assertEqual(result.action_status, "awaiting_proposals")
        self.assertEqual(query.eq.call_args_list, [call("run_id", str(run_id))])

    def test_audit_distinguishes_missing_run_from_database_failure(self):
        run_id = uuid4()
        for failure, status in ((CommandRunNotFound("missing"), 404),
                                (DatabaseUnavailable("private failure"), 503)):
            with self.subTest(status=status), patch(
                "focusos_api.main.read_run_action_audit", side_effect=failure):
                response = TestClient(app).get(f"/agent/runs/{run_id}/audit",
                    headers={"Authorization": "Bearer session"})
            self.assertEqual(response.status_code, status)
            self.assertNotIn("private failure", response.text)

    def test_anonymous_audit_is_denied(self):
        self.assertEqual(TestClient(app).get(f"/agent/runs/{uuid4()}/audit").status_code, 401)
