"""Real capture/confirmation/memory/index/search with only DB/provider boundaries simulated."""
import hashlib
import json
import unittest
from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from focusos_api.main import app
from focusos_api.jobs import _step
from focusos_api.sources import SourceRecord
from focusos_api.extractions import ExtractionRecord, ExtractionEnvelopeResponse
from focusos_api.memory_search import search_memories, MemorySearchInput

BODY = "Prepare the checklist for 30 minutes by October 12, 2026 at 5 PM Jakarta time. The FocusOS demo code is Nusa."
FACT = "The FocusOS demo code is Nusa."
NOW = datetime(2026, 10, 8, 9, tzinfo=timezone.utc)

class Query:
    def __init__(self, store, table): self.store, self.name, self.filters = store, table, {}
    def select(self, *_): return self
    def eq(self, key, value): self.filters[key] = str(value); return self
    def limit(self, *_): return self
    def execute(self):
        rows = [{**self.store.record.model_dump(mode="json"), "user_id": self.store.owner}] if self.name == "extraction_results" else list(self.store.memories.values())
        return SimpleNamespace(data=[r for r in rows if all(str(r.get(k)) == v for k,v in self.filters.items())])

class Store:
    def __init__(self):
        self.owner, source_id, result_id = str(uuid4()), uuid4(), uuid4()
        self.source = SourceRecord(id=source_id, kind="gmail", title="Nusa demo", source_ref="gmail:synthetic",
            normalized_body=BODY, body_hash=hashlib.sha256(BODY.encode()).hexdigest(), normalization_version="1",
            body_truncated=False, received_at=NOW, created_at=NOW, body_expires_at=NOW+timedelta(days=30))
        payload = {"schema_version":"1", "source_ref":self.source.source_ref,
            "tasks":[{"schema_version":"1","local_ref":"checklist","title":"Prepare checklist","description":"",
            "deadline":{"kind":"datetime","value":"2026-10-12T17:00:00+07:00","timezone":"Asia/Jakarta",
                "raw_text":"October 12, 2026 at 5 PM Jakarta time", "reference_time":NOW.isoformat(),"relation":None},
            "estimate_minutes":30,"estimate_origin":"explicit","priority_hint":"unspecified","project_candidate":None,
            "confidence":0.95,"evidence":[{"source_ref":self.source.source_ref,"quote":BODY.split(". ")[0]+"."}],"uncertainties":[]}],
            "facts":[{"text":FACT,"kind":"fact","evidence":[{"source_ref":self.source.source_ref,"quote":FACT}]}],
            "events":[],"requests":[],"project_candidates":[],"uncertainties":[]}
        self.record = ExtractionRecord(id=result_id, source_id=source_id, content_hash=self.source.body_hash,
            schema_version="1", prompt_version="2", model_version="gemini", status="ready", validated_payload=payload,
            safe_error=None, run_id=None, created_at=NOW, updated_at=NOW, reviewed_at=None)
        self.tasks, self.memories, self.calls = {}, {}, []
    @contextmanager
    def scoped(self, *_): yield self.owner, self
    def table(self, name): return Query(self, name)
    def rpc(self, name, args):
        self.calls.append(name)
        if name == "focusos_confirm_extraction_task":
            key = args["p_local_ref"]
            replayed = key in self.tasks
            self.tasks.setdefault(key, {"id":str(uuid4()),"title":args["p_title"],"description":args["p_description"],
                "status":"open","priority":args["p_priority"],"due_kind":args["p_due_kind"],"due_date":args["p_due_date"],
                "due_at":args["p_due_at"],"due_timezone":args["p_due_timezone"],"estimate_minutes":args["p_estimate_minutes"],
                "estimate_origin":"explicit","project_id":None,"source_id":str(self.source.id),"extraction_result_id":str(self.record.id),
                "extraction_item_key":key,"evidence":args["p_evidence"],"confidence":args["p_confidence"],"version":1,
                "created_at":NOW.isoformat(),"updated_at":NOW.isoformat()})
            data = {"outcome":"confirmed","task":self.tasks[key],"replayed":replayed}
        elif name == "focusos_confirm_memory":
            key = args["p_request_key"]
            self.memories.setdefault(key, {"id":str(uuid4()),"user_id":self.owner,"source_id":str(self.source.id),
                "project_id":None,"source_hash":self.source.body_hash,"text":args["p_text"],"evidence_quote":args["p_quote"],
                "status":"active","embedding_status":"pending","created_at":NOW.isoformat()})
            data = self.memories[key]
        elif name == "focusos_claim_memory_embedding":
            row = next(r for r in self.memories.values() if r["id"] == args["p_memory_id"])
            data = {"state":"reused"} if row["embedding_status"] == "ready" else {"state":"claimed","lease_token":str(uuid4()),"text":row["text"],"quote":row["evidence_quote"]}
        elif name == "focusos_finish_memory_embedding":
            row = next(r for r in self.memories.values() if r["id"] == args["p_memory_id"])
            row["embedding_status"] = "ready"; data = True
        elif name == "focusos_search_memories":
            rows = sorted(self.memories.values(), key=lambda r: r["text"] != FACT)
            data = [{**r,"source_ref":self.source.source_ref,"match_kind":"semantic","score":0.95} for r in rows]
        else: raise AssertionError(name)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=data))

class CapturePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(); self.stack = ExitStack(); self.addCleanup(self.stack.close)
        for module in ("confirmation", "memories", "memory_embeddings", "memory_search"):
            self.stack.enter_context(patch("focusos_api."+module+".scoped_client", self.store.scoped))
        for module in ("confirmation", "memories"):
            self.stack.enter_context(patch("focusos_api."+module+".get_source", return_value=self.store.source))
        self.stack.enter_context(patch("focusos_api.auto_capture.process_extraction", return_value=ExtractionEnvelopeResponse(extraction=self.store.record, replayed=True)))
        self.stack.enter_context(patch("focusos_api.memory_embeddings.embed_text", return_value=[0.1]*256))
        self.stack.enter_context(patch("focusos_api.memory_search.embed_text", return_value=[0.1]*256))
    def test_cached_extraction_saves_real_task_and_memories_then_indexes_and_answers(self):
        job = {"kind":"source","subject_id":str(self.store.source.id),"checkpoint":{},"result":None}
        for _ in range(6):
            step = _step("synthetic-session",job)
            job.update(checkpoint=step.checkpoint, result=step.result)
            if step.status == "succeeded": break
        self.assertEqual(step.status,"succeeded")
        self.assertEqual((step.result["tasks_saved"],step.result["memories_saved"]),(1,2))
        self.assertEqual(len(self.store.tasks),1); self.assertEqual(len(self.store.memories),2)
        self.assertTrue(all(m["embedding_status"] == "ready" for m in self.store.memories.values()))
        with patch("focusos_api.memory_search._select_answer_index",return_value=0):
            answer = search_memories("synthetic-session",MemorySearchInput(query="What is the FocusOS demo code?",answer=True))
        self.assertEqual(answer.answer_status,"found"); self.assertEqual(answer.answer.text,FACT)
        self.assertEqual(answer.answer.evidence_quote,FACT)
        replay = _step("synthetic-session", {"kind":"source","subject_id":str(self.store.source.id),"checkpoint":{},"result":None})
        self.assertEqual(replay.result["memories_saved"],2)
        self.assertEqual(len(self.store.tasks),1); self.assertEqual(len(self.store.memories),2)
    def test_confirmation_route_has_its_own_response_contract_without_memory_id(self):
        response = TestClient(app).post(f"/extractions/{self.store.record.id}/confirm",
            headers={"Authorization":"Bearer synthetic-session"},
            json={"local_ref":"checklist","task":{"title":"Prepare checklist","estimate_minutes":30}})
        self.assertEqual(response.status_code,200)
        self.assertEqual(set(response.json()),{"task","replayed"})
        required = app.openapi()["components"]["schemas"]["TaskCreateEnvelope"]["required"]
        self.assertIn("memory_id",required)
