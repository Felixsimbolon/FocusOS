import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from uuid import uuid4
from focusos_api.agent_continuation import AgentRunState, _planning_step
from focusos_api.agent_planner import PlanningModelError, propose_plan
from focusos_api.calendar_free_time import FreeTimeResult, Interval

START=datetime(2026,9,28,9,tzinfo=timezone.utc)
TASK={"id":str(uuid4()),"title":"Write report","due_kind":"instant","due_at":(START+timedelta(hours=3)).isoformat()}
FREE=FreeTimeResult(timezone="UTC",requested_minutes=60,available_minutes=60,allocated_minutes=60,
    shortfall_minutes=0,allow_split=False,slots=[Interval(start=START,end=START+timedelta(hours=1))],
    free_intervals=[Interval(start=START,end=START+timedelta(hours=1))])
RAW={"schema_version":"1","status":"proposed","task_refs":["task-1"],"blocks":[{"slot_ref":"slot-1","task_ref":"task-1","title":"Write report","reason":"Before due","evidence_refs":[]}],"requested_minutes":60,"scheduled_minutes":60,"shortfall_minutes":0,"assumptions":[],"questions":[],"summary":"Proposed hour"}

def run():
    return AgentRunState(id=uuid4(),command="Find one hour",status="waiting",stage="planning",version=2,
        model_turns=0,tool_calls_count=4,checkpoint={"tasks":[TASK],"free_time":FREE.model_dump(mode="json"),
        "memory_search":{"mode":"lexical_fallback","matches":[]},"calendar":{"fetched_at":START.isoformat()}},
        expires_at=datetime.now(timezone.utc)+timedelta(minutes=10),updated_at=datetime.now(timezone.utc))

class PlannerTests(unittest.TestCase):
    def test_model_receives_bounded_handles_and_no_tools(self):
        response=Mock(); response.content=b"{}"; response.json.return_value={"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":json.dumps(RAW)}]}]}
        with patch.dict("os.environ",{"FOCUSOS_OPENAI_API_KEY":"test"}),patch("focusos_api.agent_planner.httpx.post",return_value=response) as post:
            self.assertEqual(propose_plan("Find one hour",[TASK],FREE,{"matches":[]},START.isoformat()),RAW)
        payload=post.call_args.kwargs["json"]
        self.assertFalse(payload["store"])
        self.assertNotIn("tools",payload)
        self.assertIn("task-1",payload["input"][1]["content"])
    def test_missing_key_fails_closed(self):
        with patch.dict("os.environ",{"FOCUSOS_OPENAI_API_KEY":""}):
            with self.assertRaises(PlanningModelError): propose_plan("x",[TASK],FREE,{},START.isoformat())
    def test_success_checkpoint_is_proposal_only(self):
        initial=run(); leased=initial.model_copy(update={"version":3,"status":"running"}); done=leased.model_copy(update={"version":4,"status":"succeeded"})
        with patch("focusos_api.agent_continuation.load_command_run",side_effect=[leased,done]),patch("focusos_api.agent_continuation._checkpoint",return_value=True) as save,patch("focusos_api.agent_continuation.propose_plan",return_value=RAW):
            self.assertEqual(_planning_step("session",initial),done)
        final=save.call_args_list[-1].args
        self.assertEqual(final[3],"succeeded")
        self.assertFalse(final[6]["actionable"])
    def test_bad_model_plan_is_saved_as_safe_failure(self):
        initial=run(); leased=initial.model_copy(update={"version":3,"status":"running"}); done=leased.model_copy(update={"version":4,"status":"failed"})
        bad={**RAW,"blocks":[{**RAW["blocks"][0],"slot_ref":"slot-999"}]}
        with patch("focusos_api.agent_continuation.load_command_run",side_effect=[leased,done]),patch("focusos_api.agent_continuation._checkpoint",return_value=True) as save,patch("focusos_api.agent_continuation.propose_plan",return_value=bad):
            self.assertEqual(_planning_step("session",initial),done)
        self.assertEqual(save.call_args_list[-1].args[3],"failed")
        self.assertEqual(save.call_args_list[-1].args[6],None)
