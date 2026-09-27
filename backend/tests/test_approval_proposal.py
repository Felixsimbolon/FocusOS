import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from focusos_api.approval_proposal import ProposalInput, ProposalRejected, propose_calendar_event
from focusos_api.database import DatabaseUnavailable
from focusos_api.approval_decisions import DecisionInput
from focusos_api.main import app

class ApprovalProposalTests(unittest.TestCase):
    def test_rejects_model_controlled_guests_and_approval_flag(self):
        from pydantic import ValidationError
        for value in ({"block_index":0,"guests":["a@example.com"]},{"block_index":0,"approved":True}):
            with self.assertRaises(ValidationError): ProposalInput.model_validate(value)
    def test_proposal_dispatch_is_database_only(self):
        run_id, task_id, connection_id, approval_id=uuid4(),uuid4(),uuid4(),uuid4()
        now=datetime.now(timezone.utc)+timedelta(hours=2)
        payload={"schema_version":"1","tool":"calendar.create_event","run_id":str(run_id),"block_index":0,
            "task_id":str(task_id),"task_version":1,"connection_id":str(connection_id),"calendar_id":"primary",
            "event_id":"f"+approval_id.hex,"title":"Report","start":now.isoformat(),
            "end":(now+timedelta(hours=1)).isoformat(),"timezone":"UTC","source_id":None,
            "guests":[],"send_updates":"none"}
        row={"id":str(approval_id),"run_id":str(run_id),"block_index":0,"task_id":str(task_id),
            "connection_id":str(connection_id),"calendar_id":"primary","event_id":payload["event_id"],
            "payload":payload,"payload_hash":"a"*64,"status":"pending","status_version":1,
            "expires_at":(now+timedelta(hours=1)).isoformat(),"created_at":now.isoformat(),
            "updated_at":now.isoformat()}
        with patch("focusos_api.approval_proposal._rpc",return_value=row) as rpc,patch("httpx.post") as provider:
            result=propose_calendar_event("session",run_id,ProposalInput(block_index=0))
        self.assertEqual(result.status,"pending")
        self.assertEqual(rpc.call_args.args[1],"focusos_propose_calendar_action")
        provider.assert_not_called()
    def test_calendar_write_failure_gets_safe_reason(self):
        class RemoteError(Exception):
            message = "Calendar grant unavailable"

        def fail(*_args):
            raise DatabaseUnavailable("Restricted database operation failed") from RemoteError()

        with patch("focusos_api.approval_proposal._rpc", side_effect=fail):
            with self.assertRaises(ProposalRejected) as caught:
                propose_calendar_event("session", uuid4(), ProposalInput(block_index=0))
        self.assertEqual(caught.exception.code, "calendar_write_required")

    def test_unknown_database_failure_is_not_exposed(self):
        with patch("focusos_api.main.propose_calendar_event",
                   side_effect=DatabaseUnavailable("private database detail")):
            result = TestClient(app).post(f"/agent/runs/{uuid4()}/propose-event",
                json={"block_index": 0}, headers={"Authorization": "Bearer session"})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private database detail", result.text)

    def test_decision_body_cannot_replace_action(self):
        from pydantic import ValidationError
        for body in ({"decision":"approve","title":"Other"},{"decision":"approved"}):
            with self.assertRaises(ValidationError): DecisionInput.model_validate(body)
    def test_anonymous_proposal_is_denied(self):
        self.assertEqual(TestClient(app).post(f"/agent/runs/{uuid4()}/propose-event",json={"block_index":0}).status_code,401)
        self.assertEqual(TestClient(app).get(f"/approvals?run_id={uuid4()}").status_code,401)
        self.assertEqual(TestClient(app).post(f"/approvals/{uuid4()}/decision",json={"decision":"approve"}).status_code,401)
