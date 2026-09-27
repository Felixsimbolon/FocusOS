import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import httpx
from focusos_api.approval_payload import CalendarAction
from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.calendar_write import (CalendarWriteConflict, CalendarWriteDeferred,
    CalendarWriteUnknown, insert_or_reconcile)

START=datetime(2026,9,28,10,tzinfo=timezone.utc)

def approval():
    approval_id=uuid4(); action=CalendarAction(run_id=uuid4(),block_index=0,task_id=uuid4(),task_version=1,
        connection_id=uuid4(),event_id="f"+approval_id.hex,title="Write report",start=START,
        end=START+timedelta(hours=1),timezone="UTC")
    return ApprovalRecord(id=approval_id,run_id=action.run_id,block_index=0,task_id=action.task_id,
        connection_id=action.connection_id,calendar_id="primary",event_id=action.event_id,payload=action,
        payload_hash="a"*64,status="executing",status_version=3,
        expires_at=START+timedelta(hours=2),created_at=START,updated_at=START)

def provider_event(a):
    return {"id":a.event_id,"summary":a.payload.title,
        "start":{"dateTime":a.payload.start.isoformat()},"end":{"dateTime":a.payload.end.isoformat()},
        "extendedProperties":{"private":{"focusos_payload_hash":a.payload_hash}},
        "htmlLink":"https://www.google.com/calendar/event?eid=test"}

class CalendarWriteTests(unittest.TestCase):
    def test_insert_uses_fixed_shape_no_attendees(self):
        a=approval(); calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(404) if request.method=="GET" else httpx.Response(200,json=provider_event(a))
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result=insert_or_reconcile(a,"token",http_client=client)
        self.assertFalse(result.reconciled)
        self.assertEqual([c.method for c in calls],["GET","POST"])
        self.assertNotIn("attendees",calls[1].content.decode())
        self.assertEqual(calls[1].url.params["sendUpdates"],"none")
    def test_lost_response_reconciles_matching_event(self):
        a=approval(); calls=[]
        def handler(request):
            calls.append(request.method)
            if len(calls)==1: return httpx.Response(404)
            if len(calls)==2: raise httpx.ReadTimeout("lost")
            return httpx.Response(200,json=provider_event(a))
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result=insert_or_reconcile(a,"token",http_client=client)
        self.assertTrue(result.reconciled)
        self.assertEqual(calls,["GET","POST","GET"])
    def test_409_with_matching_marker_reconciles(self):
        a=approval(); calls=[]
        def handler(request):
            calls.append(request.method)
            if len(calls)==1:return httpx.Response(404)
            if len(calls)==2:return httpx.Response(409)
            return httpx.Response(200,json=provider_event(a))
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            self.assertTrue(insert_or_reconcile(a,"token",http_client=client).reconciled)
    def test_409_mismatched_marker_is_conflict(self):
        a=approval(); calls=[]
        def handler(request):
            calls.append(request.method)
            if len(calls)==1:return httpx.Response(404)
            if len(calls)==2:return httpx.Response(409)
            event=provider_event(a); event["extendedProperties"]["private"]["focusos_payload_hash"]="wrong"
            return httpx.Response(200,json=event)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(CalendarWriteConflict): insert_or_reconcile(a,"token",http_client=client)
    def test_timeout_then_404_is_unknown_and_429_is_deferred(self):
        a=approval(); calls=[]
        def handler(request):
            calls.append(request.method)
            if len(calls)==1:return httpx.Response(404)
            if len(calls)==2:raise httpx.ReadTimeout("lost")
            return httpx.Response(404)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(CalendarWriteUnknown): insert_or_reconcile(a,"token",http_client=client)
        with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(429))) as client:
            with self.assertRaises(CalendarWriteDeferred): insert_or_reconcile(a,"token",http_client=client)
