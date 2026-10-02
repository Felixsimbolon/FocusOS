"""Automatic API workflow with provider/DB boundaries simulated; no real Google writes."""
import hashlib
import json
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from fastapi.testclient import TestClient

from focusos_api.agent_continuation import AgentRunState
from focusos_api.approval_payload import CalendarAction, canonical_action_hash
from focusos_api.approval_proposal import ApprovalRecord
from focusos_api.auto_capture import capture_ready
from focusos_api.calendar_fetch import CalendarWindow
from focusos_api.calendar_write import insert_or_reconcile
from focusos_api.connections import GoogleConnection
from focusos_api.extractions import ExtractionEnvelopeResponse, ExtractionRecord
from focusos_api.extractor import extract_structured
from focusos_api.google_calendar import CALENDAR_READ_SCOPE
from focusos_api.google_oauth import GOOGLE_CALENDAR_WRITE_SCOPE
from focusos_api.main import app
from focusos_api.memory_embeddings import embed_memory
from focusos_api.memory_search import MemorySearchInput, search_memories
from focusos_api.sources import SourceRecord
from test_planning_compiler import NOW, PROFILE, selection

BODY = ("Please prepare the FocusOS demo checklist by Monday, October 5, 2026 at 5:00 PM Jakarta time. "
        "It should take about 30 minutes. This is for the FocusOS Demo project.\n"
        "The audience for the FocusOS Demo project is backend engineers.")
FACT = "The audience for the FocusOS Demo project is backend engineers."
TASK_QUOTE = "Please prepare the FocusOS demo checklist by Monday, October 5, 2026 at 5:00 PM Jakarta time."


class WorkflowHarness:
    def __init__(self):
        self.owner = str(uuid4())
        self.source_id, self.task_id, self.memory_id = uuid4(), uuid4(), uuid4()
        self.source = SourceRecord(id=self.source_id, kind="gmail", title="FocusOS demo - prepare checklist",
            source_ref="gmail:synthetic-demo", normalized_body=BODY,
            body_hash=hashlib.sha256(BODY.encode()).hexdigest(), normalization_version="1",
            body_truncated=False, received_at=NOW, created_at=NOW, body_expires_at=NOW+timedelta(days=30))
        self.task = None
        self.memory = None
        self.vector = None
        self.run = None
        self.request_key = uuid4()
        self.started_request_key = None
        self.approval = None
        self.events = {}
        self.insert_count = 0
        self.new_busy = False
        self.timeout_after_insert = False
        self.intent = selection()
        self.client = TestClient(app)
        self.google = httpx.Client(transport=httpx.MockTransport(self.google_request))
        self.stack = ExitStack()

    def provider(self, url, **kwargs):
        request = httpx.Request("POST", url)
        payload = kwargs["json"]
        if url.endswith(":embedContent"):
            return httpx.Response(200, request=request, json={"embedding": {"values": [0.1]*256}})
        instruction = payload["systemInstruction"]["parts"][0]["text"]
        if "Extract only grounded" in instruction:
            value = {"schema_version": "1", "source_ref": self.source.source_ref,
                "tasks": [{"schema_version": "1", "local_ref": "checklist", "title": "Prepare the FocusOS demo checklist",
                    "description": "", "deadline": {"kind": "datetime", "value": "2026-10-05T17:00:00+07:00",
                    "timezone": "Asia/Jakarta", "raw_text": "Monday, October 5, 2026 at 5:00 PM Jakarta time",
                    "reference_time": NOW.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Jakarta")).isoformat(), "relation": None},
                    "estimate_minutes": 30, "estimate_origin": "explicit", "priority_hint": "unspecified",
                    "project_candidate": "FocusOS Demo", "confidence": 0.95,
                    "evidence": [{"source_ref": self.source.source_ref, "quote": TASK_QUOTE}], "uncertainties": []}],
                "facts": [{"text": FACT, "kind": "fact", "evidence": [{"source_ref": self.source.source_ref, "quote": FACT}]}],
                "events": [], "requests": [], "project_candidates": ["FocusOS Demo"], "uncertainties": []}
        elif "Choose the single confirmed fact" in instruction:
            value = {"index": 0}
        elif "Interpret the user's scheduling request" in instruction:
            value = self.intent
        else:
            raise AssertionError("Unexpected provider request")
        return httpx.Response(200, request=request, json={"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": json.dumps(value)}]}}]})

    @contextmanager
    def scoped(self, *_):
        yield self.owner, self

    def table(self, *_):
        self.table_mode = True
        return self

    def select(self, *_): return self
    def eq(self, *_): return self
    def limit(self, *_): return self
    def execute(self): return SimpleNamespace(data=[self.memory])

    def rpc(self, name, args):
        if name == "focusos_confirm_memory":
            self.memory = {"id": str(self.memory_id), "source_id": str(self.source_id), "project_id": None,
                "source_hash": self.source.body_hash, "text": args["p_text"], "evidence_quote": args["p_quote"],
                "status": "active", "embedding_status": "pending", "created_at": NOW.isoformat()}
            data = self.memory
        elif name == "focusos_claim_memory_embedding":
            data = {"state": "claimed", "lease_token": "synthetic-lease", "text": self.memory["text"], "quote": self.memory["evidence_quote"]}
        elif name == "focusos_finish_memory_embedding":
            self.vector = json.loads(args["p_vector"])
            self.memory["embedding_status"] = "ready"
            data = True
        elif name == "focusos_search_memories":
            data = [{**self.memory, "source_ref": self.source.source_ref, "match_kind": "semantic", "score": 0.99}]
        else:
            raise AssertionError(name)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=data))

    def save_task(self, _, extraction_id, request):
        task = request.task
        self.task = SimpleNamespace(id=self.task_id, title=task.title, due_kind=task.due_kind,
            due_at=task.due_at, due_date=task.due_date, estimate_minutes=task.estimate_minutes,
            source_id=self.source_id, status="open", version=1)

    def start_rpc(self, _, name, args):
        assert name == "focusos_start_command_run"
        if self.run is None or self.started_request_key != args["p_request_key"]:
            self.started_request_key = args["p_request_key"]
            self.run = AgentRunState(id=uuid4(), command=args["p_command"], status="pending", stage="start",
                version=1, model_turns=0, tool_calls_count=0, checkpoint={},
                expires_at=NOW+timedelta(hours=1), updated_at=NOW)
        return self.run.model_dump(mode="json")

    def save_run(self, _, run_id, version, status, stage, checkpoint, result, turns, calls, error=None):
        if version != self.run.version:
            return False
        self.run = self.run.model_copy(update={"version": version+1, "status": status, "stage": stage,
            "checkpoint": checkpoint, "result": result, "model_turns": turns,
            "tool_calls_count": calls, "safe_error": error, "updated_at": NOW})
        return True

    def calendar(self, _, start, end):
        events = ()
        if self.new_busy and self.run and self.run.result:
            block = self.run.result["blocks"][0]
            events = ({"id": "new-busy-event", "status": "confirmed", "summary": "Busy",
                "start": {"dateTime": block["start"]}, "end": {"dateTime": block["end"]}},)
        return CalendarWindow(start, end, NOW+timedelta(seconds=1), "primary", PROFILE.timezone, events)

    def proposal_rpc(self, _, name, args):
        if name == "focusos_propose_calendar_action":
            if self.approval is None:
                block = self.run.result["blocks"][0]
                approval_id = uuid4()
                action = CalendarAction(run_id=self.run.id, block_index=0, task_id=self.task_id,
                    task_version=1, connection_id=self.connection.id, event_id="f"+approval_id.hex,
                    title=block["title"], start=datetime.fromisoformat(block["start"]),
                    end=datetime.fromisoformat(block["end"]), timezone=PROFILE.timezone, source_id=self.source_id)
                self.approval = ApprovalRecord(id=approval_id, run_id=self.run.id, block_index=0,
                    task_id=self.task_id, connection_id=self.connection.id, event_id=action.event_id,
                    calendar_id="primary", payload=action, payload_hash=canonical_action_hash(action),
                    status="approved", authorization_mode="automatic", status_version=1,
                    expires_at=NOW+timedelta(minutes=20), created_at=NOW, updated_at=NOW)
            return self.approval.model_dump(mode="json")
        raise AssertionError(name)

    def service_rpc(self, name, args):
        if name == "focusos_claim_approval_execution":
            claimed = self.approval.status in ("approved", "unknown")
            if claimed:
                self.approval = self.approval.model_copy(update={"status": "executing", "status_version": self.approval.status_version+1})
            return {"claimed": claimed, "approval": self.approval.model_dump(mode="json")}
        if name == "focusos_finish_approval_execution":
            self.approval = self.approval.model_copy(update={"status": args["p_status"],
                "provider_event_id": args["p_provider_event_id"], "provider_link": args["p_provider_link"],
                "safe_code": args["p_safe_code"], "status_version": self.approval.status_version+1})
            return True
        raise AssertionError(name)

    def google_request(self, request):
        if request.method == "GET":
            event = self.events.get(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200 if event else 404, json=event or {})
        if request.method == "POST":
            self.insert_count += 1
            event = json.loads(request.content)
            event["htmlLink"] = "https://calendar.google.com/calendar/event?eid=synthetic"
            self.events[event["id"]] = event
            if self.timeout_after_insert:
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            return httpx.Response(200, json=event)
        raise AssertionError("Unexpected Google request")

    def enter(self):
        self.connection = GoogleConnection(id=uuid4(), provider="google", display_email=None,
            granted_scopes=[CALENDAR_READ_SCOPE, GOOGLE_CALENDAR_WRITE_SCOPE], status="connected", last_refresh_at=None)
        patches = {
            "focusos_api.gemini.httpx.post": self.provider,
            "focusos_api.auto_capture.confirm_candidate": self.save_task,
            "focusos_api.memories.get_source": lambda *_: self.source,
            "focusos_api.memories.scoped_client": self.scoped,
            "focusos_api.memory_embeddings.scoped_client": self.scoped,
            "focusos_api.memory_search.scoped_client": self.scoped,
            "focusos_api.agent_continuation._rpc": self.start_rpc,
            "focusos_api.agent_continuation._checkpoint": self.save_run,
            "focusos_api.agent_continuation._log": lambda *args, **kwargs: None,
            "focusos_api.agent_continuation.load_command_run": lambda *_: self.run.model_copy(deep=True),
            "focusos_api.agent_continuation.read_profile": lambda *_: PROFILE,
            "focusos_api.agent_continuation.list_tasks": lambda *args, **kwargs: SimpleNamespace(tasks=[self.task], truncated=False),
            "focusos_api.agent_continuation.fetch_calendar_window": self.calendar,
            "focusos_api.automatic_calendar.load_command_run": lambda *_: self.run.model_copy(deep=True),
            "focusos_api.approval_proposal._rpc": self.proposal_rpc,
            "focusos_api.approval_execute.scoped_client": self.scoped,
            "focusos_api.approval_execute._service_rpc": self.service_rpc,
            "focusos_api.approval_execute.load_approval": lambda *_: self.approval,
            "focusos_api.approval_execute._get_bearer": lambda *_: "synthetic-google-token",
            "focusos_api.approval_execute.insert_or_reconcile": lambda *args, **kwargs: insert_or_reconcile(*args, **kwargs, http_client=self.google),
            "focusos_api.approval_preflight._load_current_task": lambda *_: {
                "id": str(self.task_id), "title": self.task.title, "status": self.task.status,
                "version": self.task.version, "due_kind": self.task.due_kind,
                "due_at": self.task.due_at.isoformat() if self.task.due_at else None, "source_id": str(self.source_id)},
            "focusos_api.approval_preflight.read_profile": lambda *_: PROFILE,
            "focusos_api.approval_preflight.read_google_connection": lambda *_: self.connection,
            "focusos_api.approval_preflight.fetch_calendar_window": self.calendar,
        }
        for target, fake in patches.items():
            self.stack.enter_context(patch(target, side_effect=fake))
        for module in ("agent_continuation", "planning_compiler", "approval_execute", "approval_preflight"):
            clock = self.stack.enter_context(patch(f"focusos_api.{module}.datetime"))
            clock.now.return_value = NOW
            clock.fromisoformat.side_effect = datetime.fromisoformat
        self.stack.enter_context(patch.dict("os.environ", {"GEMINI_API_KEY": "synthetic-no-network-key"}))
        return self

    def close(self):
        self.stack.close()
        self.google.close()
        self.client.close()

    def extract_and_capture(self):
        extracted = extract_structured(self.source.source_ref, BODY, NOW, PROFILE.timezone)
        record = ExtractionRecord(id=uuid4(), source_id=self.source_id, content_hash=self.source.body_hash,
            schema_version="1", prompt_version="2", model_version="synthetic-provider", status="ready",
            validated_payload=extracted.result.model_dump(mode="json"), safe_error=None, run_id=None,
            created_at=NOW, updated_at=NOW, reviewed_at=None)
        return capture_ready("session", ExtractionEnvelopeResponse(extraction=record, replayed=False))

    def plan(self, duration=None):
        response = self.client.post("/agent/runs", headers={"Authorization": "Bearer synthetic-session"},
            json={"request_key": str(self.request_key), "command": "Schedule the FocusOS demo checklist for 30 minutes tomorrow",
                  "duration_minutes": duration, "auto_calendar": True})
        assert response.status_code == 200, response.text
        for _ in range(6):
            if self.run.status in ("succeeded", "clarify", "failed"):
                return self.run
            response = self.client.post(f"/agent/runs/{self.run.id}/continue", headers={"Authorization": "Bearer synthetic-session"})
            assert response.status_code == 200, response.text
        raise AssertionError("Run did not finish")

    def auto(self):
        return self.client.post(f"/agent/runs/{self.run.id}/blocks/0/auto", headers={"Authorization": "Bearer synthetic-session"})


class PlanningWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.h = WorkflowHarness().enter()
        self.addCleanup(self.h.close)
        self.h.extract_and_capture()

    def test_email_extraction_embedding_search_planning_and_calendar_with_replay(self):
        state = embed_memory("session", self.h.memory_id)
        self.assertEqual(state.state, "ready")
        self.assertEqual(len(self.h.vector), 256)
        answer = search_memories("session", MemorySearchInput(query="Who is the audience for the FocusOS Demo project?", answer=True))
        self.assertEqual(answer.answer.text, FACT)
        self.assertEqual(answer.answer.evidence_quote, FACT)
        self.assertEqual(answer.mode, "semantic_enabled")
        run = self.h.plan()
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.tool_calls_count, 4)
        self.assertEqual(run.result["scheduled_minutes"], 30)
        self.assertEqual(datetime.fromisoformat(run.result["blocks"][0]["start"]).astimezone(__import__("zoneinfo").ZoneInfo(PROFILE.timezone)).date().isoformat(), "2026-10-03")
        first, replay = self.h.auto(), self.h.auto()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "succeeded")
        self.assertEqual(first.json()["provider_link"], "https://calendar.google.com/calendar/event?eid=synthetic")
        self.assertEqual(first.json()["id"], replay.json()["id"])
        self.assertEqual((self.h.insert_count, len(self.h.events)), (1, 1))

    def test_repeating_same_start_returns_existing_run_without_extra_model_calls(self):
        first = self.h.plan()
        replay = self.h.plan()
        self.assertEqual(replay.id, first.id)
        self.assertEqual(replay.model_turns, first.model_turns)
        self.assertEqual(replay.version, first.version)

    def test_new_busy_event_blocks_calendar_insertion(self):
        self.h.plan()
        self.h.new_busy = True
        response = self.h.auto()
        self.assertEqual(response.json()["status"], "stale")
        self.assertEqual(response.json()["safe_code"], "slot_conflict")
        self.assertEqual(self.h.insert_count, 0)

    def test_changed_task_blocks_calendar_insertion(self):
        self.h.plan()
        self.h.proposal_rpc("session", "focusos_propose_calendar_action", {})
        self.h.task.version = 2
        response = self.h.auto()
        self.assertEqual(response.json()["safe_code"], "task_changed")
        self.assertEqual(self.h.insert_count, 0)

    def test_timeout_after_google_accepts_is_reconciled_without_duplicate(self):
        self.h.plan()
        self.h.timeout_after_insert = True
        self.assertEqual(self.h.auto().json()["status"], "succeeded")
        self.assertEqual(self.h.auto().json()["status"], "succeeded")
        self.assertEqual(self.h.insert_count, 1)

    def test_duration_conflict_cannot_create_any_event(self):
        run = self.h.plan(duration=60)
        self.assertEqual(run.status, "clarify")
        self.assertEqual(run.result["safe_code"], "duration_conflict")
        self.assertEqual(self.h.auto().status_code, 409)
        self.assertEqual(self.h.insert_count, 0)

    def test_bad_model_reference_cannot_create_any_event(self):
        self.h.intent = selection(task_refs=["task-999"])
        run = self.h.plan()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.safe_error, "unknown_task_reference")
        self.assertEqual(self.h.auto().status_code, 409)
        self.assertEqual(self.h.insert_count, 0)

    def test_reusing_request_with_changed_options_returns_conflict(self):
        self.h.plan()
        response = self.h.client.post("/agent/runs", headers={"Authorization": "Bearer synthetic-session"},
            json={"request_key": str(self.h.request_key), "command": self.h.run.command,
                  "duration_minutes": 60, "auto_calendar": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "request_options_changed")


if __name__ == "__main__":
    unittest.main()
