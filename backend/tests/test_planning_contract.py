import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from focusos_api.calendar_free_time import FreeTimeResult, Interval
from focusos_api.planning_contract import PlanningValidationError, validate_planning_response

START = datetime(2026, 9, 28, 9, tzinfo=timezone.utc)
TASK = {"id": str(uuid4()), "title": "Write report", "due_kind": "instant", "due_at": (START+timedelta(hours=4)).isoformat()}
FREE = FreeTimeResult(timezone="UTC", requested_minutes=60, available_minutes=120, allocated_minutes=60,
    shortfall_minutes=0, allow_split=False, slots=[Interval(start=START,end=START+timedelta(hours=1))],
    free_intervals=[Interval(start=START,end=START+timedelta(hours=2))])

def plan():
    return {"schema_version":"1", "status":"proposed", "task_refs":["task-1"],
        "blocks":[{"slot_ref":"slot-1","task_ref":"task-1","title":"Write report","reason":"Before due time","evidence_refs":[]}],
        "requested_minutes":60,"scheduled_minutes":60,"shortfall_minutes":0,"assumptions":[],"questions":[],"summary":"One hour proposed"}

class PlanningContractTests(unittest.TestCase):
    def test_valid_plan_resolves_server_owned_ids(self):
        result=validate_planning_response(plan(),[TASK],FREE)
        self.assertEqual(result["blocks"][0]["task_id"],TASK["id"])
        self.assertFalse(result["actionable"])
        self.assertNotEqual(result["blocks"][0]["reason"], plan()["blocks"][0]["reason"])
    def test_reject_unknown_slot_and_wrong_total(self):
        value=plan(); value["blocks"][0]["slot_ref"]="slot-999"
        with self.assertRaises(PlanningValidationError): validate_planning_response(value,[TASK],FREE)
        value=plan(); value["scheduled_minutes"]=59
        with self.assertRaises(PlanningValidationError): validate_planning_response(value,[TASK],FREE)
    def test_deadline_and_date_only_are_enforced(self):
        task={**TASK,"due_at":(START+timedelta(minutes=30)).isoformat()}
        with self.assertRaises(PlanningValidationError): validate_planning_response(plan(),[task],FREE)
        task={**TASK,"due_kind":"date","due_date":"2026-09-28","due_at":None}
        self.assertEqual(validate_planning_response(plan(),[task],FREE)["status"],"proposed")
        with self.assertRaises(PlanningValidationError): validate_planning_response(plan(),[{**task,"due_date":"2026-09-27"}],FREE)
    def test_shortfall_and_clarification(self):
        value=plan(); value.update(status="needs_clarification", blocks=[], scheduled_minutes=0,shortfall_minutes=60,questions=["Which task?"])
        self.assertEqual(validate_planning_response(value,[TASK],FREE)["status"],"needs_clarification")
        short=FREE.model_copy(update={"slots":[],"allocated_minutes":0,"shortfall_minutes":60})
        value.update(status="insufficient_time", questions=[])
        self.assertEqual(validate_planning_response(value,[TASK],short)["status"],"insufficient_time")
    def test_reject_overlapping_slots(self):
        second=Interval(start=START+timedelta(minutes=30),end=START+timedelta(minutes=90))
        free=FREE.model_copy(update={"slots":[FREE.slots[0],second],"requested_minutes":120})
        value=plan(); value["blocks"].append({**value["blocks"][0],"slot_ref":"slot-2"})
        value.update(requested_minutes=120,scheduled_minutes=120,shortfall_minutes=0)
        with self.assertRaises(PlanningValidationError): validate_planning_response(value,[TASK],free)
    def test_reject_invented_evidence(self):
        value=plan(); value["blocks"][0]["evidence_refs"]=["source-fake"]
        with self.assertRaises(PlanningValidationError): validate_planning_response(value,[TASK],FREE)
