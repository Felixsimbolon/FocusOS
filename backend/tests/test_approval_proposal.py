import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from focusos_api.approval_proposal import ProposalInput, propose_calendar_event
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
    def test_anonymous_proposal_is_denied(self):
        self.assertEqual(TestClient(app).post(f"/agent/runs/{uuid4()}/propose-event",json={"block_index":0}).status_code,401)
