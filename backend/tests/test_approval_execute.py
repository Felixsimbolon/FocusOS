import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from focusos_api.approval_execute import execute_approval
from focusos_api.approval_payload import CalendarAction
from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.calendar_write import CalendarWriteResult, CalendarWriteUnknown
from focusos_api.main import app

NOW=datetime(2026,9,28,8,tzinfo=timezone.utc)

def fixture():
    approval_id=uuid4(); action=CalendarAction(run_id=uuid4(),block_index=0,task_id=uuid4(),task_version=1,
        connection_id=uuid4(),event_id="f"+approval_id.hex,title="Report",start=NOW+timedelta(hours=2),
        end=NOW+timedelta(hours=3),timezone="UTC")
    return ApprovalRecord(id=approval_id,run_id=action.run_id,block_index=0,task_id=action.task_id,
        connection_id=action.connection_id,calendar_id="primary",event_id=action.event_id,payload=action,
        payload_hash="a"*64,status="approved",status_version=2,expires_at=NOW+timedelta(hours=1),
        created_at=NOW,updated_at=NOW,decided_at=NOW)

@contextmanager
def owner(*_):
    yield str(uuid4()),object()

class ExecuteTests(unittest.TestCase):
    def test_only_claim_winner_calls_provider_and_persists_proof(self):
        before=fixture(); claimed=before.model_copy(update={"status":"executing","status_version":3})
        done=claimed.model_copy(update={"status":"succeeded","provider_event_id":before.event_id})
        with patch("focusos_api.approval_execute.scoped_client",owner),\
             patch("focusos_api.approval_execute.load_approval",side_effect=[before,done]),\
             patch("focusos_api.approval_execute._service_rpc",side_effect=[{"claimed":True,"approval":claimed.model_dump(mode="json")},True]) as rpc,\
             patch("focusos_api.approval_execute._get_bearer",return_value="token"),\
             patch("focusos_api.approval_execute.insert_or_reconcile",return_value=CalendarWriteResult(before.event_id,None,False)) as provider:
            result=execute_approval("session",before.id)
        self.assertEqual(result.status,"succeeded")
        provider.assert_called_once()
        self.assertEqual(rpc.call_args_list[-1].args[1]["p_provider_event_id"],before.event_id)
    def test_second_request_does_not_call_provider(self):
        before=fixture(); claimed=before.model_copy(update={"status":"executing","status_version":3})
        with patch("focusos_api.approval_execute.scoped_client",owner),\
             patch("focusos_api.approval_execute.load_approval",return_value=before),\
             patch("focusos_api.approval_execute._service_rpc",return_value={"claimed":False,"approval":claimed.model_dump(mode="json")}),\
             patch("focusos_api.approval_execute._get_bearer") as bearer:
            self.assertEqual(execute_approval("session",before.id).status,"executing")
        bearer.assert_not_called()
    def test_unknown_provider_result_is_not_success(self):
        before=fixture(); claimed=before.model_copy(update={"status":"executing","status_version":3})
        unknown=claimed.model_copy(update={"status":"unknown"})
        with patch("focusos_api.approval_execute.scoped_client",owner),\
             patch("focusos_api.approval_execute.load_approval",side_effect=[before,unknown]),\
             patch("focusos_api.approval_execute._service_rpc",side_effect=[{"claimed":True,"approval":claimed.model_dump(mode="json")},True]) as rpc,\
             patch("focusos_api.approval_execute._get_bearer",return_value="token"),\
             patch("focusos_api.approval_execute.insert_or_reconcile",side_effect=CalendarWriteUnknown()):
            self.assertEqual(execute_approval("session",before.id).status,"unknown")
        self.assertEqual(rpc.call_args_list[-1].args[1]["p_status"],"unknown")
        self.assertIsNone(rpc.call_args_list[-1].args[1]["p_provider_event_id"])
    def test_anonymous_execution_is_denied(self):
        self.assertEqual(TestClient(app).post(f"/approvals/{uuid4()}/execute").status_code,401)
