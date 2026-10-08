"""One natural-language request through capture, slots and safe provider writes."""
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from contextlib import contextmanager
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError
from focusos_api.unified_commands import WorkInput, WorkIntent, infer_work, advance_work
from focusos_api.jobs import _step, RetryStep
from focusos_api.approval_payload import CalendarAction, canonical_action_hash
from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.planning_compiler import compile_plan
from test_planning_compiler import NOW, PROFILE, TASK, checkpoint, selection, busy
from test_planning_workflow import WorkflowHarness

TEXT = "Cari waktu besok antara jam 13 sampai 16 untuk belajar Python selama 45 menit."

def intent(action="schedule", **changes):
    return WorkIntent(action=action, title_quote="belajar Python", explanation="Reserve time for studying.",
        selection=selection(task_refs=[], day="tomorrow", duration_minutes=45, start_time="13:00", end_time="16:00", **changes))

class UnifiedHarness(WorkflowHarness):
    def enter(self):
        super().enter()
        self.work_intent = intent()
        self.stack.enter_context(patch("focusos_api.unified_commands._checkpoint", side_effect=self.save_run))
        self.stack.enter_context(patch("focusos_api.unified_commands.infer_work", side_effect=lambda *_: self.work_intent))
        self.stack.enter_context(patch("focusos_api.unified_commands.read_profile", return_value=PROFILE))
        self.stack.enter_context(patch("focusos_api.unified_commands.list_tasks", side_effect=lambda *a, **k: SimpleNamespace(tasks=[self.task] if self.task else [], truncated=False)))
        self.stack.enter_context(patch("focusos_api.agent_continuation.list_tasks", side_effect=lambda *a, **k: SimpleNamespace(tasks=[self.task] if self.task else [], truncated=False)))
        self.stack.enter_context(patch("focusos_api.agent_continuation.search_memories", return_value=SimpleNamespace(model_dump=lambda **_: {"mode":"none","matches":[]})))
        return self
    def proposal_rpc(self, _, name, args):
        if self.run.checkpoint.get("standalone_title"):
            if self.approval is None:
                block = self.run.result["blocks"][0]; aid = uuid4()
                action = CalendarAction(run_id=self.run.id, block_index=0, task_id=None, task_version=None,
                    connection_id=self.connection.id, event_id="f"+aid.hex, title=block["title"],
                    start=block["start"], end=block["end"], timezone=PROFILE.timezone)
                self.approval = ApprovalRecord(id=aid, run_id=self.run.id, block_index=0, task_id=None,
                    connection_id=self.connection.id, calendar_id="primary", event_id=action.event_id,
                    payload=action, payload_hash=canonical_action_hash(action), status="approved", authorization_mode="automatic",
                    status_version=1, expires_at=NOW+timedelta(minutes=20), created_at=NOW, updated_at=NOW)
            return self.approval.model_dump(mode="json")
        return super().proposal_rpc(_, name, args)
    def start(self, text=TEXT):
        self.start_rpc("session", "focusos_start_command_run", {"p_command":text, "p_request_key":str(uuid4())})
        self.save_run("session", self.run.id, self.run.version, "waiting", "start",
            {"entrypoint":"unified","window_start":NOW.isoformat()}, None, 0, 0)
        return {"kind":"planning", "subject_id":str(self.run.id), "checkpoint":{}}
    def drain(self, job):
        for _ in range(24):
            step = _step("session", job)
            job = {**job,"checkpoint":step.checkpoint,"result":step.result}
            if step.status in ("succeeded","failed"): return step, job
        raise AssertionError("Work did not finish")

class UnifiedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.h = UnifiedHarness().enter(); self.addCleanup(self.h.close)
    def test_standalone_schedule_needs_no_task_or_source_and_replay_inserts_once(self):
        with patch("focusos_api.unified_commands.create_manual_source") as create:
            step, job = self.h.drain(self.h.start())
            create.assert_not_called()
        self.assertEqual(step.status, "succeeded")
        self.assertIsNone(self.h.task)
        self.assertIsNone(self.h.approval.task_id)
        self.assertEqual(self.h.approval.payload.title, "belajar Python")
        self.assertEqual(self.h.approval.payload.start.astimezone(ZoneInfo(PROFILE.timezone)).hour, 13)
        self.assertEqual(step.result["blocks_scheduled"], 1)
        self.assertIn("calendar.google.com", step.result["blocks"][0]["link"])
        self.h.drain(job)
        self.assertEqual(self.h.insert_count, 1)
    def test_saved_task_is_scheduled_without_new_source_or_task(self):
        self.h.extract_and_capture()
        self.h.work_intent = intent().model_copy(update={"title_quote":None,"selection":intent().selection.model_copy(update={"task_refs":["task-1"],"duration_minutes":30})})
        with patch("focusos_api.unified_commands.create_manual_source") as create:
            step, _ = self.h.drain(self.h.start("Schedule the FocusOS demo checklist for 30 minutes tomorrow between 13 and 16"))
            create.assert_not_called()
        self.assertEqual(step.status,"succeeded")
        self.assertEqual(self.h.approval.task_id,self.h.task_id)
    def test_new_busy_event_at_execution_blocks_insertion(self):
        self.h.new_busy=True
        step, _ = self.h.drain(self.h.start())
        self.assertEqual(step.status,"failed")
        self.assertEqual(self.h.insert_count,0)
        self.assertEqual(self.h.approval.safe_code,"slot_conflict")
    def test_lost_provider_response_reconciles_standalone_event(self):
        self.h.timeout_after_insert=True
        step, job = self.h.drain(self.h.start())
        self.assertEqual(step.status,"succeeded")
        self.h.drain(job)
        self.assertEqual(self.h.insert_count,1)
    def test_insufficient_requested_window_has_no_calendar_write(self):
        self.h.work_intent = intent().model_copy(update={"selection":intent().selection.model_copy(update={"duration_minutes":240})})
        step, _ = self.h.drain(self.h.start(TEXT.replace("45 menit","240 menit")))
        self.assertEqual(step.status,"failed")
        self.assertIn("not enough",step.result["message"])
        self.assertEqual(self.h.insert_count,0)
    def test_capture_waits_for_embedding_and_replays_terminal_run(self):
        job=self.h.start("Prepare the demo checklist. The audience is backend engineers.")
        self.h.work_intent=intent("capture")
        response=SimpleNamespace(extraction=SimpleNamespace(status="ready"),capture={"tasks_saved":1,"memories_saved":2,"memory_ids":[str(uuid4()),str(uuid4())]})
        with patch("focusos_api.unified_commands.create_manual_source",return_value=SimpleNamespace(source=SimpleNamespace(id=self.h.source_id))) as source, patch("focusos_api.unified_commands.process_and_capture",return_value=response), patch("focusos_api.unified_commands.embed_memory",return_value=SimpleNamespace(state="ready")) as embed:
            step, saved=self.h.drain(job)
            self.assertEqual(step.status,"succeeded")
            self.assertEqual(embed.call_count,2)
            self.assertEqual(self.h.insert_count,0)
            self.assertEqual(step.result["tasks_saved"],1)
            # A crash after command success but before the job finish must still recover.
            recovered=_step("session",{**saved,"checkpoint":{"phase":"command_index"}})
            self.assertEqual(recovered.status,"succeeded")
    def test_partial_capture_persists_counts_and_retries_same_source_without_double_counting(self):
        job = self.h.start("Prepare the checklist.")
        self.h.work_intent = intent("capture")
        initial = _step("session", job)
        job.update(checkpoint=initial.checkpoint, result=initial.result)
        partial = SimpleNamespace(extraction=SimpleNamespace(status="ready"), capture={
            "tasks_saved": 1, "memories_saved": 0, "memory_failures": 1, "memory_ids": []})
        complete = SimpleNamespace(extraction=SimpleNamespace(status="ready"), capture={
            "tasks_saved": 1, "memories_saved": 1, "memory_ids": []})
        with patch("focusos_api.unified_commands.create_manual_source", return_value=SimpleNamespace(source=SimpleNamespace(id=self.h.source_id))) as source, patch("focusos_api.unified_commands.process_and_capture", side_effect=[partial, complete]):
            retry = _step("session", job)
            self.assertEqual(retry.error, "capture_incomplete")
            self.assertTrue(retry.failure)
            self.assertEqual(retry.result["tasks_saved"], 1)
            self.assertEqual(retry.checkpoint["phase"], "command_capture")
            job.update(checkpoint=retry.checkpoint, result=retry.result)
            finished, _ = self.h.drain(job)
            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(finished.result["tasks_saved"], 1)
            self.assertEqual(finished.result["memories_saved"], 1)
            self.assertTrue(all(call.args[1] == self.h.run.id for call in source.call_args_list))
        self.assertEqual(self.h.insert_count, 0)

    def test_capture_skips_inactive_memory_but_retries_busy_embedding(self):
        job = self.h.start("Prepare the checklist.")
        self.h.work_intent = intent("capture")
        response = SimpleNamespace(extraction=SimpleNamespace(status="ready"), capture={
            "tasks_saved": 1, "memories_saved": 1, "memory_ids": [str(uuid4())]})
        with patch("focusos_api.unified_commands.create_manual_source", return_value=SimpleNamespace(source=SimpleNamespace(id=self.h.source_id))), patch("focusos_api.unified_commands.process_and_capture", return_value=response):
            for _ in range(2):
                step = _step("session", job)
                job.update(checkpoint=step.checkpoint, result=step.result)
        with patch("focusos_api.unified_commands.embed_memory", return_value=SimpleNamespace(state="busy")):
            with self.assertRaises(RetryStep) as raised: _step("session", job)
            self.assertEqual(raised.exception.code, "embedding_busy")
        with patch("focusos_api.unified_commands.embed_memory", return_value=SimpleNamespace(state="unavailable")):
            finished, _ = self.h.drain(job)
            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(finished.result["tasks_saved"], 1)
        self.assertEqual(self.h.insert_count, 0)

    def test_both_captures_then_schedules_only_tasks_from_this_source(self):
        job=self.h.start("Create a task to prepare the FocusOS demo checklist and schedule it for 30 minutes tomorrow between 13 and 16.")
        self.h.work_intent=intent("both").model_copy(update={"selection":intent().selection.model_copy(update={"duration_minutes":30})})
        def capture(*_):
            result=self.h.extract_and_capture()
            return SimpleNamespace(extraction=SimpleNamespace(status="ready"),capture={**result,"memory_ids":[]})
        db=MagicMock(); query=db.table.return_value.select.return_value
        query.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data=[{
            "id":str(self.h.task_id),"title":"Prepare the FocusOS demo checklist","due_kind":"datetime",
            "due_at":"2026-10-05T17:00:00+07:00","due_date":None,"estimate_minutes":30,"source_id":str(self.h.source_id)}]
        @contextmanager
        def scoped(*_): yield self.h.owner,db
        with patch("focusos_api.unified_commands.create_manual_source",return_value=SimpleNamespace(source=SimpleNamespace(id=self.h.source_id))), patch("focusos_api.unified_commands.process_and_capture",side_effect=capture),patch("focusos_api.database.scoped_client",scoped):
            step,_=self.h.drain(job)
        self.assertEqual(step.status,"succeeded")
        self.assertEqual(step.result["tasks_saved"],1)
        self.assertEqual(step.result["blocks_scheduled"],1)
        self.assertEqual(self.h.approval.task_id,self.h.task_id)
        query.eq.assert_called_once_with("user_id",self.h.owner)
        query.eq.return_value.eq.assert_called_once_with("status","open")
        query.eq.return_value.eq.return_value.eq.assert_called_once_with("source_id",str(self.h.source_id))

    def test_both_preserves_saved_results_when_scheduling_cannot_start(self):
        job=self.h.start("Create a task to prepare the checklist and schedule it tomorrow.")
        self.h.work_intent=intent("both")
        response=SimpleNamespace(extraction=SimpleNamespace(status="ready"),capture={"tasks_saved":1,"memories_saved":1,"memory_ids":[]})
        with patch("focusos_api.unified_commands.create_manual_source",return_value=SimpleNamespace(source=SimpleNamespace(id=self.h.source_id))), patch("focusos_api.unified_commands.process_and_capture",return_value=response), patch("focusos_api.unified_commands.read_profile",return_value=None):
            step,_=self.h.drain(job)
        self.assertEqual(step.status,"failed")
        self.assertEqual(step.result["tasks_saved"],1)
        self.assertIn("Preferences",step.result["message"])
    def test_ambiguity_is_terminal_without_any_capture_or_write(self):
        self.h.work_intent=intent("clarify").model_copy(update={"selection":intent().selection.model_copy(update={"status":"needs_clarification","questions":["Which activity do you mean?"]})})
        with patch("focusos_api.unified_commands.create_manual_source") as source:
            step,_=self.h.drain(self.h.start())
            source.assert_not_called()
        self.assertEqual(step.result["message"],"Which activity do you mean?")
        self.assertEqual(self.h.run.status,"clarify")

class WorkValidationTests(unittest.TestCase):
    def provider_result(self,value):
        return {"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":json.dumps(value)}]}}]}
    def test_model_cannot_invent_activity_task_or_evidence(self):
        valid=intent().model_dump()
        for value in ({**valid,"title_quote":"invented meeting"}, {**valid,"selection":{**valid["selection"],"task_refs":["task-999"]}}, {**valid,"selection":{**valid["selection"],"evidence_refs":["source-forged"]}}):
            with patch("focusos_api.unified_commands.api_key",return_value="synthetic"),patch("focusos_api.unified_commands.request",return_value=self.provider_result(value)):
                with self.assertRaises(RetryStep):infer_work(TEXT,[],NOW.isoformat(),PROFILE.timezone)
    def test_provider_contract_accepts_capture_schedule_and_both_with_indonesian_requests(self):
        # Model output is simulated: this covers validation, not live intent accuracy.
        cases = [
            ("capture", "Tolong buat tugas matematika dengan deadline 15 Oktober 2026 jam 23:00 WIB."),
            ("schedule", TEXT),
            ("both", "Buat tugas belajar Python dan jadwalkan besok antara jam 13 sampai 16 selama 45 menit."),
        ]
        for action, text in cases:
            with self.subTest(action=action), patch("focusos_api.unified_commands.api_key", return_value="synthetic"), patch("focusos_api.unified_commands.request", return_value=self.provider_result(intent(action).model_dump())):
                result = infer_work(text, [], NOW.isoformat(), PROFILE.timezone)
                self.assertEqual(result.action, action)
                self.assertEqual(result.selection.task_refs, [])

    def test_capture_and_both_cannot_bind_an_unrelated_existing_task(self):
        for action in ("capture", "both"):
            invalid = intent(action).model_dump()
            invalid["selection"]["task_refs"] = ["task-1"]
            with self.subTest(action=action), patch("focusos_api.unified_commands.api_key", return_value="synthetic"), patch("focusos_api.unified_commands.request", return_value=self.provider_result(invalid)):
                with self.assertRaises(RetryStep) as raised:
                    infer_work("Buat tugas matematika", [TASK], NOW.isoformat(), PROFILE.timezone)
                self.assertEqual(raised.exception.code, "intent_invalid")

    def test_unconfigured_provider_does_not_make_an_external_request(self):
        with patch("focusos_api.unified_commands.api_key", return_value=None), patch("focusos_api.unified_commands.request") as provider:
            with self.assertRaises(RetryStep) as raised:
                infer_work(TEXT, [], NOW.isoformat(), PROFILE.timezone)
        self.assertEqual(raised.exception.code, "provider_unconfigured")
        provider.assert_not_called()

    def test_inference_context_hides_database_ids(self):
        with patch("focusos_api.unified_commands.api_key",return_value="synthetic"),patch("focusos_api.unified_commands.request",return_value=self.provider_result(intent().model_dump())) as provider:
            self.assertEqual(infer_work(TEXT,[TASK],NOW.isoformat(),PROFILE.timezone).action,"schedule")
        context=json.loads(provider.call_args.args[0]["contents"][0]["parts"][0]["text"])
        self.assertNotIn("id",context["tasks"][0])
        self.assertNotIn("source_id",context["tasks"][0])
    def test_model_cannot_drop_explicit_clock_range(self):
        task={**TASK,"id":None,"title":"belajar Python"}
        result,_=compile_plan(selection(day="any",start_time=None,end_time=None,duration_minutes=30),[task],checkpoint(),PROFILE,now=NOW,command=TEXT)
        start=datetime.fromisoformat(result["blocks"][0]["start"]).astimezone(ZoneInfo(PROFILE.timezone))
        self.assertEqual((start.day,start.hour),(3,13))
        self.assertEqual(result["scheduled_minutes"],45)
    def test_standalone_payload_cannot_claim_task_version_or_source(self):
        base={"run_id":uuid4(),"block_index":0,"task_id":None,"task_version":None,"connection_id":uuid4(),"event_id":"f"+uuid4().hex,"title":"Study","start":NOW,"end":NOW+timedelta(minutes=30),"timezone":"UTC"}
        CalendarAction(**base)
        for changes in ({"task_version":1},{"source_id":uuid4()}):
            with self.assertRaises(ValidationError):CalendarAction(**{**base,**changes})
    def test_input_rejects_manual_type_switch_or_blank(self):
        for values in ({"request_key":uuid4(),"text":"   "},{"request_key":uuid4(),"text":"Work","type":"schedule"}):
            with self.assertRaises(ValidationError):WorkInput(**values)
