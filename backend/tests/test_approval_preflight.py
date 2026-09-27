import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from focusos_api.approval_payload import CalendarAction
from focusos_api.approval_preflight import ApprovalStale, check_approval_preflight
from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.calendar_fetch import CalendarWindow
from focusos_api.connections import GoogleConnection
from focusos_api.google_calendar import CALENDAR_READ_SCOPE
from focusos_api.google_oauth import GOOGLE_CALENDAR_WRITE_SCOPE
from focusos_api.profiles import ProfileRecord, WorkingHours

NOW=datetime(2026,9,28,8,tzinfo=timezone.utc)

def fixture():
    task_id,connection_id,run_id,approval_id=uuid4(),uuid4(),uuid4(),uuid4()
    action=CalendarAction(run_id=run_id,block_index=0,task_id=task_id,task_version=1,
        connection_id=connection_id,event_id="f"+approval_id.hex,title="Write report",
        start=NOW+timedelta(hours=2),end=NOW+timedelta(hours=3),timezone="UTC")
    approval=ApprovalRecord(id=approval_id,run_id=run_id,block_index=0,task_id=task_id,
        connection_id=connection_id,calendar_id="primary",event_id=action.event_id,
        payload=action,payload_hash="a"*64,status="approved",status_version=2,
        expires_at=NOW+timedelta(minutes=20),created_at=NOW,updated_at=NOW,decided_at=NOW)
    task={"id":str(task_id),"title":"Write report","status":"open","version":1,
        "due_kind":"datetime","due_at":(NOW+timedelta(hours=4)).isoformat(),"source_id":None}
    connection=GoogleConnection(id=connection_id,provider="google",display_email=None,
        granted_scopes=[CALENDAR_READ_SCOPE,GOOGLE_CALENDAR_WRITE_SCOPE],status="connected",last_refresh_at=None)
    profile=ProfileRecord(id=uuid4(),timezone="UTC",working_hours=WorkingHours(days=[1,2,3,4,5,6,7],start_minute=0,end_minute=1440))
    window=CalendarWindow(NOW,action.end,NOW+timedelta(seconds=1),"primary","UTC",())
    return approval,task,connection,profile,window

class PreflightTests(unittest.TestCase):
    def check(self, approval,task,connection,profile,window):
        with patch("focusos_api.approval_preflight._load_current_task",return_value=task),\
             patch("focusos_api.approval_preflight.read_google_connection",return_value=connection),\
             patch("focusos_api.approval_preflight.read_profile",return_value=profile),\
             patch("focusos_api.approval_preflight.fetch_calendar_window",return_value=window):
            return check_approval_preflight("session",approval,now=NOW)
    def test_clean_slot_passes(self):
        self.assertEqual(self.check(*fixture()).busy_event_count,0)
    def test_changed_task_or_rejected_or_expired_blocks(self):
        a,t,c,p,w=fixture()
        for changed in ({**t,"version":2},{**t,"due_at":(NOW+timedelta(hours=2,minutes=30)).isoformat()}):
            with self.assertRaises(ApprovalStale): self.check(a,changed,c,p,w)
        for status in ("rejected","expired"):
            with self.assertRaises(ApprovalStale): self.check(a.model_copy(update={"status":status}),t,c,p,w)
    def test_revoked_grant_or_new_busy_event_blocks(self):
        a,t,c,p,w=fixture()
        with self.assertRaises(ApprovalStale): self.check(a,t,c.model_copy(update={"granted_scopes":[CALENDAR_READ_SCOPE]}),p,w)
        busy={"id":"busy","summary":"Private","status":"confirmed","start":{"dateTime":a.payload.start.isoformat()},
              "end":{"dateTime":a.payload.end.isoformat()}}
        with self.assertRaises(ApprovalStale): self.check(a,t,c,p,CalendarWindow(w.start,w.end,w.fetched_at,"primary","UTC",(busy,)))
