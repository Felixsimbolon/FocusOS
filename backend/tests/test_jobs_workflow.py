"""Worker steps use real planning/compiler/Calendar adapters; boundaries remain synthetic."""
import unittest
from focusos_api.jobs import _step
from test_planning_workflow import WorkflowHarness

class JobsWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.h=WorkflowHarness().enter();self.addCleanup(self.h.close);self.h.extract_and_capture()
  response=self.h.client.post("/agent/runs",headers={"Authorization":"Bearer synthetic-session"},json={"request_key":str(self.h.request_key),"command":"Schedule the FocusOS demo checklist for 30 minutes tomorrow","auto_calendar":True})
  self.assertEqual(response.status_code,200)
  self.row={"kind":"planning","subject_id":str(self.h.run.id),"checkpoint":{},"result":None}
 def test_worker_completes_planning_and_one_calendar_event(self):
  for _ in range(12):
   step=_step("session",self.row)
   self.row.update(checkpoint=step.checkpoint,result=step.result)
   if step.status=="succeeded":break
  self.assertEqual(step.status,"succeeded");self.assertEqual(self.h.run.result["scheduled_minutes"],30)
  self.assertEqual(self.h.insert_count,1)
  replay=_step("session",self.row)
  self.assertEqual(replay.status,"succeeded");self.assertEqual(self.h.insert_count,1)
 def test_crash_after_provider_accepts_replays_same_event_without_duplication(self):
  while self.h.approval is None:
   old=dict(self.row)
   step=_step("session",self.row)
   self.row.update(checkpoint=step.checkpoint,result=step.result)
  self.assertEqual(self.h.insert_count,1)
  # Lose the successful worker checkpoint and replay its prior durable state.
  step=_step("session",old)
  self.assertEqual(self.h.insert_count,1);self.assertEqual(step.checkpoint["block_index"],1)
