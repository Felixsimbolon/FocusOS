import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from focusos_api.approval_audit import _state
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

    def test_anonymous_audit_is_denied(self):
        self.assertEqual(TestClient(app).get(f"/agent/runs/{uuid4()}/audit").status_code, 401)
