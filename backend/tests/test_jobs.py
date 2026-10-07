import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import unittest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi.testclient import TestClient
from focusos_api.main import app
from focusos_api import jobs
from focusos_api.database import InvalidSession
from focusos_api.token_crypto import TokenCipher, TokenCipherError

NOW = datetime.now(timezone.utc)
OWNER = str(uuid4())
TOKEN = "x." + base64.urlsafe_b64encode(json.dumps({"exp": int((NOW + timedelta(hours=1)).timestamp())}).encode()).decode().rstrip("=") + ".x"
@contextmanager
def scoped(_): yield OWNER, MagicMock()

def claimed(cipher, job_id):
    encrypted = cipher.encrypt(job_id, "job", TOKEN)
    return {"id": str(job_id), "user_id": OWNER, "kind": "planning", "subject_id": str(uuid4()), "checkpoint": {}, "result": None, "failures": 0,
      "ciphertext": base64.b64encode(encrypted.ciphertext).decode(), "key_version": 1, "lease_token": str(uuid4())}

class JobsTests(unittest.TestCase):
    def test_subject_shape_and_unknown_fields_rejected(self):
        for value in ({"kind":"gmail","subject_id":str(uuid4())}, {"kind":"source"}, {"kind":"planning","subject_id":str(uuid4()),"owner":OWNER}):
            with self.assertRaises(ValueError): jobs.JobInput(request_key=uuid4(), **value)
        jobs.JobInput(request_key=uuid4(),kind="gmail")
    def test_sessions_are_capped_and_near_expiry_rejected(self):
        self.assertEqual(jobs.session_expiry(TOKEN,NOW), NOW+timedelta(minutes=15))
        for token in ("bad", "x.e30.x", "x."+base64.urlsafe_b64encode(json.dumps({"exp":0}).encode()).decode()+".x"):
            with self.assertRaises(InvalidSession): jobs.session_expiry(token,NOW)
    def test_cipher_domain_and_job_identity_are_bound(self):
        cipher=TokenCipher({1:b"k"*32},1); ident=uuid4(); enc=cipher.encrypt(ident,"job",TOKEN)
        self.assertEqual(cipher.decrypt(ident,"job",enc.ciphertext,1), TOKEN)
        with self.assertRaises(TokenCipherError): cipher.decrypt(ident,"access",enc.ciphertext,1)
        with self.assertRaises(TokenCipherError): cipher.decrypt(uuid4(),"job",enc.ciphertext,1)
    def test_owned_work_checks_ownership_before_service_claim(self):
        with patch.object(jobs,"get_job",side_effect=jobs.JobNotFound()), patch.object(jobs,"_service_rpc") as rpc:
            with self.assertRaises(jobs.JobNotFound): jobs.work_owned(TOKEN,uuid4())
            rpc.assert_not_called()
    def run_worker(self, outcome, finish=True, owner=OWNER):
        cipher=TokenCipher({1:b"k"*32},1); row=claimed(cipher,uuid4())
        @contextmanager
        def auth(_): yield owner, MagicMock()
        with patch.object(jobs,"_service_rpc",side_effect=[row,finish]) as rpc, patch.object(jobs,"scoped_client",auth), patch.object(jobs.TokenCipher,"from_environment",return_value=cipher), patch.object(jobs,"_step") as step:
            if isinstance(outcome,Exception): step.side_effect=outcome
            else: step.return_value=outcome
            result=jobs.work_one()
        return result, rpc.call_args_list[-1].args[1], step
    def test_success_fenced_and_no_secret_returned(self):
        result,args,_=self.run_worker(jobs.Step("succeeded",result={"blocks_scheduled":1}))
        self.assertEqual(result["state"],"advanced"); self.assertEqual(args["p_status"],"succeeded")
        self.assertNotIn(TOKEN,json.dumps(result)); self.assertNotIn("ciphertext",result)
    def test_lost_lease_does_not_claim_success(self):
        result,_,_=self.run_worker(jobs.Step("succeeded"),finish=False)
        self.assertEqual(result["state"],"lease_lost")
    def test_retry_backoff_is_persisted(self):
        _,args,_=self.run_worker(jobs.RetryStep("calendar_pending",60))
        self.assertEqual(args["p_status"],"queued"); self.assertEqual(args["p_delay"],60); self.assertTrue(args["p_failure"])
    def test_owner_mismatch_never_calls_existing_tools(self):
        _,args,step=self.run_worker(jobs.Step("succeeded"),owner=str(uuid4()))
        self.assertEqual(args["p_status"],"expired"); step.assert_not_called()
    def test_exception_text_is_not_exposed(self):
        _,args,_=self.run_worker(RuntimeError("private session and email"))
        self.assertEqual(args["p_error"],"worker_error"); self.assertNotIn("private",json.dumps(args))
    def test_idle_has_no_provider_call(self):
        with patch.object(jobs,"_service_rpc",return_value=None),patch.object(jobs,"_step") as step:
            self.assertEqual(jobs.work_one(),{"state":"idle"}); step.assert_not_called()
    def test_anonymous_routes_rejected(self):
        client=TestClient(app)
        for url in ("/jobs",f"/jobs/{uuid4()}"):
            self.assertEqual(client.get(url).status_code,401)
        self.assertEqual(client.post("/jobs",json={"kind":"gmail","request_key":str(uuid4())}).status_code,401)
    def test_scheduler_requires_configured_matching_secret(self):
        client=TestClient(app)
        with patch.dict(os.environ,{"FOCUSOS_WORKER_SECRET":""}): self.assertEqual(client.get("/internal/jobs/tick").status_code,503)
        with patch.dict(os.environ,{"FOCUSOS_WORKER_SECRET":"w"*32}),patch("focusos_api.job_routes.work_one",return_value={"state":"idle"}) as step:
            self.assertEqual(client.get("/internal/jobs/tick",headers={"Authorization":"Bearer wrong"}).status_code,401);step.assert_not_called()
            self.assertEqual(client.get("/internal/jobs/tick",headers={"Authorization":"Bearer "+"w"*32}).status_code,200)
    def test_planning_step_waits_without_creating_events(self):
        run=MagicMock(status="waiting",stage="calendar")
        with patch("focusos_api.agent_continuation.load_command_run",return_value=run),patch("focusos_api.agent_continuation.continue_staged_run",return_value=run),patch("focusos_api.automatic_calendar.schedule_automatic_block") as insert:
            result=jobs._step(TOKEN,{"kind":"planning","subject_id":str(uuid4())})
            self.assertEqual(result.status,"queued");insert.assert_not_called()
    def test_confirmed_calendar_block_advances_once(self):
        run=MagicMock(status="succeeded",result={"status":"proposed","blocks":[{}]},checkpoint={"auto_calendar":True})
        with patch("focusos_api.agent_continuation.load_command_run",return_value=run),patch("focusos_api.automatic_calendar.schedule_automatic_block",return_value=MagicMock(status="succeeded")) as insert:
            result=jobs._step(TOKEN,{"kind":"planning","subject_id":str(uuid4()),"checkpoint":{}})
            self.assertEqual(result.checkpoint,{"block_index":1});self.assertEqual(insert.call_count,1)
    def test_unknown_calendar_outcome_keeps_same_index(self):
        run=MagicMock(status="succeeded",result={"status":"proposed","blocks":[{}]},checkpoint={"auto_calendar":True})
        with patch("focusos_api.agent_continuation.load_command_run",return_value=run),patch("focusos_api.automatic_calendar.schedule_automatic_block",return_value=MagicMock(status="unknown")):
            with self.assertRaises(jobs.RetryStep): jobs._step(TOKEN,{"kind":"planning","subject_id":str(uuid4()),"checkpoint":{}})
    def test_gmail_busy_does_not_process_sources(self):
        with patch("focusos_api.gmail_sync.run_one_sync_page",return_value=MagicMock(state="retry_wait")),patch("focusos_api.gmail_processing.process_one_gmail_source") as process:
            with self.assertRaises(jobs.RetryStep): jobs._step(TOKEN,{"kind":"gmail"})
            process.assert_not_called()
    def test_capture_failures_not_reported_complete(self):
        response=MagicMock(extraction=MagicMock(status="ready"),capture={"task_failures":1})
        with self.assertRaises(jobs.RetryStep):jobs._capture_step(TOKEN,{},response)

    def test_gmail_pagination_preserves_totals_until_organization_finishes(self):
        previous = {"imported": 4, "tasks_saved": 3, "memories_saved": 2}
        with patch("focusos_api.gmail_sync.run_one_sync_page", return_value=MagicMock(state="complete", imported=1)):
            step = jobs._step(TOKEN, {"kind": "gmail", "checkpoint": {"phase": "sync"}, "result": previous})
        self.assertEqual(step.result, {"imported": 5, "tasks_saved": 3, "memories_saved": 2})
        self.assertEqual(step.checkpoint["phase"], "process")
        self.assertNotEqual(step.status, "succeeded")

    def test_source_is_not_complete_until_memory_indexing_finishes(self):
        source = uuid4()
        response = MagicMock(extraction=MagicMock(status="ready", source_id=source),
            capture={"tasks_saved": 1, "memories_saved": 1, "memory_ids": [str(uuid4())]})
        step = jobs._capture_step(TOKEN, {}, response)
        self.assertEqual(step.status, "queued")
        self.assertEqual(step.checkpoint["phase"], "embedding")
        self.assertEqual(step.result["source_id"], str(source))
        self.assertEqual(step.result["tasks_saved"], 1)

    def test_gmail_persists_source_before_capture_and_retries_same_source(self):
        source = uuid4()
        with patch("focusos_api.gmail_processing.next_gmail_source", return_value=source), patch("focusos_api.auto_capture.process_and_capture") as capture:
            selected = jobs._step(TOKEN, {"kind": "gmail", "checkpoint": {"phase": "process"}})
            capture.assert_not_called()
        self.assertEqual(selected.checkpoint, {"phase": "capture", "source_id": str(source)})
        response = MagicMock(extraction=MagicMock(status="ready", source_id=source), capture={"task_failures": 1})
        with patch("focusos_api.gmail_processing.next_gmail_source") as next_source, patch("focusos_api.auto_capture.process_and_capture", return_value=response) as capture:
            with self.assertRaises(jobs.RetryStep):
                jobs._step(TOKEN, {"kind": "gmail", "checkpoint": selected.checkpoint})
            next_source.assert_not_called()
            capture.assert_called_once_with(TOKEN, source)
