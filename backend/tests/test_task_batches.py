"""Multi-task source parsing, completeness and persistence; simulated boundaries only."""
import hashlib
import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from focusos_api.auto_capture import capture_ready
from focusos_api.extraction_contracts import ExtractionEnvelope, validate_grounding
from focusos_api.extractions import ExtractionEnvelopeResponse
from focusos_api.extractor import ExtractionFailure, extract_structured
from focusos_api.jobs import _capture_step
from focusos_api.memory_embeddings import embed_memory
from focusos_api.task_batches import TaskBatchIncomplete, explicit_task_items, validate_task_batch
from focusos_api.unified_commands import WorkIntent, infer_work
from test_capture_persistence import NOW, Store
from test_unified_commands import UnifiedHarness, intent

SOURCE = "source-batch"
DETAILS = [
    ("Siapkan outline presentasi", "13 Oktober 2026", "2026-10-13", 30, "normal"),
    ("Review desain web", "14 Oktober 2026", "2026-10-14", 60, "high"),
    ("Buat halaman web", "18 Oktober 2026", "2026-10-18", 120, "low"),
]
ITEMS = [f"{title}, deadline {raw}, estimasi {minutes} menit, prioritas {priority}."
         for title, raw, day, minutes, priority in DETAILS]
BODY = "Buat task berikut:\n" + "\n".join(f"{i}. {item}" for i, item in enumerate(ITEMS, 1))


def payload(source=SOURCE, details=DETAILS, items=ITEMS):
    return {"schema_version": "1", "source_ref": source, "tasks": [
        {"schema_version": "1", "local_ref": f"task-{i}", "title": title, "description": "",
         "deadline": {"kind": "date", "value": day, "timezone": "Asia/Jakarta",
             "raw_text": raw, "reference_time": NOW.isoformat(), "relation": None},
         "estimate_minutes": minutes, "estimate_origin": "explicit", "priority_hint": priority,
         "project_candidate": None, "confidence": 0.95,
         "evidence": [{"source_ref": source, "quote": quote}], "uncertainties": []}
        for i, ((title, raw, day, minutes, priority), quote) in enumerate(zip(details, items), 1)],
        "facts": [], "events": [], "requests": [], "project_candidates": [], "uncertainties": []}


def provider_response(value):
    result = Mock(content=b"synthetic")
    result.json.return_value = {"candidates": [{"finishReason": "STOP",
        "content": {"parts": [{"text": json.dumps(value)}]}}]}
    return result


class TaskBatchContractTests(unittest.TestCase):
    def test_numbered_list_keeps_all_source_items_in_order(self):
        items = explicit_task_items(BODY)
        self.assertEqual(len(items), 3)
        self.assertTrue(all(quote in item for quote, item in zip(ITEMS, items)))
        result = ExtractionEnvelope.model_validate(payload())
        validate_grounding(result, SOURCE, BODY, NOW)
        validate_task_batch(result, items)

    def test_markdown_checkboxes_and_continuation_lines_are_kept(self):
        body = "**Buat task berikut:**\n- [ ] Siapkan outline.\n  Deadline 13 Oktober.\n- [x] Review desain.\n\nFacts:\nThe demo code is Nusa."
        items = explicit_task_items(body)
        self.assertEqual(len(items), 2)
        self.assertIn("  Deadline 13 Oktober.", items[0])
        self.assertNotIn("Nusa", "".join(items))
        self.assertTrue(all(item in body for item in items))

    def test_ordinary_email_bullets_and_facts_do_not_force_task_creation(self):
        for body in ("Facts:\n- Demo code is Nusa.\n- Office is Jakarta.",
                     "Remember:\n1. Aurora is the code name.\n2. Monday is review day.",
                     "Prepare a checklist covering web, API, and deployment."):
            self.assertEqual(explicit_task_items(body), [])

    def test_missing_or_merged_list_item_is_rejected(self):
        case = payload()
        case["tasks"] = case["tasks"][:2]
        with self.assertRaises(TaskBatchIncomplete):
            validate_task_batch(ExtractionEnvelope.model_validate(case), explicit_task_items(BODY))

    def test_repeated_evidence_cannot_cover_a_different_item(self):
        case = payload()
        case["tasks"][2]["evidence"] = case["tasks"][0]["evidence"]
        with self.assertRaises(TaskBatchIncomplete):
            validate_task_batch(ExtractionEnvelope.model_validate(case), explicit_task_items(BODY))

    def test_deadline_from_another_list_item_cannot_be_attached_to_the_task(self):
        case = payload()
        case["tasks"][0]["deadline"] = case["tasks"][1]["deadline"]
        with self.assertRaises(TaskBatchIncomplete):
            validate_task_batch(ExtractionEnvelope.model_validate(case), explicit_task_items(BODY))

    def test_explicit_shared_deadline_outside_items_is_allowed(self):
        items = [row[0] + "." for row in DETAILS]
        body = "Buat task berikut, semua deadline 18 Oktober 2026:\n" + "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
        details = [(row[0], "18 Oktober 2026", "2026-10-18", row[3], row[4]) for row in DETAILS]
        result = ExtractionEnvelope.model_validate(payload(details=details, items=items))
        validate_grounding(result, SOURCE, body, NOW)
        validate_task_batch(result, explicit_task_items(body))

    def test_task_order_from_model_does_not_change_item_completeness(self):
        case = payload()
        case["tasks"].reverse()
        validate_task_batch(ExtractionEnvelope.model_validate(case), explicit_task_items(BODY))

    def test_multiple_explicit_lists_are_counted_without_signature_lines(self):
        body = "Tasks:\n1) Prepare outline.\n2) Review design.\n\nThanks!\n\nTugas berikut:\n* Create page."
        self.assertEqual(len(explicit_task_items(body)), 3)


class BatchExtractorTests(unittest.TestCase):
    def test_one_model_call_preserves_all_task_specific_fields(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "synthetic-key"}), patch(
            "focusos_api.gemini.httpx.post", return_value=provider_response(payload())) as provider:
            result = extract_structured(SOURCE, BODY, NOW, "Asia/Jakarta")
        self.assertEqual(provider.call_count, 1)
        self.assertEqual([t.deadline.value for t in result.result.tasks], [d[2] for d in DETAILS])
        self.assertEqual([t.estimate_minutes for t in result.result.tasks], [30, 60, 120])
        self.assertEqual([t.priority_hint for t in result.result.tasks], ["normal", "high", "low"])

    def test_incomplete_batch_gets_one_repair_before_any_capture(self):
        incomplete = payload()
        incomplete["tasks"] = incomplete["tasks"][:1]
        with patch.dict("os.environ", {"GEMINI_API_KEY": "synthetic-key"}), patch(
            "focusos_api.gemini.httpx.post", side_effect=[provider_response(incomplete), provider_response(payload())]) as provider:
            result = extract_structured(SOURCE, BODY, NOW, "Asia/Jakarta")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(result.result.tasks), 3)
        self.assertEqual(provider.call_args.kwargs["json"]["contents"], provider.call_args_list[0].kwargs["json"]["contents"])

    def test_persistent_incomplete_batch_returns_specific_failure(self):
        case = payload()
        case["tasks"] = case["tasks"][:1]
        with patch.dict("os.environ", {"GEMINI_API_KEY": "synthetic-key"}), patch(
            "focusos_api.gemini.httpx.post", return_value=provider_response(case)) as provider:
            with self.assertRaises(ExtractionFailure) as caught:
                extract_structured(SOURCE, BODY, NOW, "Asia/Jakarta")
        self.assertEqual(caught.exception.kind, "batch_incomplete")
        self.assertEqual(provider.call_count, 2)

    def test_ten_task_list_fits_the_existing_candidate_limit(self):
        details = [(f"Prepare deliverable {i}", "18 Oktober 2026", "2026-10-18", 30, "normal") for i in range(1, 11)]
        items = [f"{row[0]}, deadline {row[1]}, estimasi 30 menit." for row in details]
        body = "Buat task berikut:\n" + "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
        with patch.dict("os.environ", {"GEMINI_API_KEY": "synthetic-key"}), patch(
            "focusos_api.gemini.httpx.post", return_value=provider_response(payload(details=details, items=items))):
            result = extract_structured(SOURCE, body, NOW, "Asia/Jakarta")
        self.assertEqual(len(result.result.tasks), 10)

    def test_over_limit_list_is_rejected_without_spending_model_calls(self):
        body = "Buat task berikut:\n" + "\n".join(f"{i}. Prepare deliverable {i}." for i in range(1, 12))
        with patch.dict("os.environ", {"GEMINI_API_KEY": "synthetic-key"}), patch("focusos_api.gemini.httpx.post") as provider:
            with self.assertRaises(ExtractionFailure) as caught:
                extract_structured(SOURCE, body, NOW, "Asia/Jakarta")
        self.assertEqual(caught.exception.kind, "batch_limit_exceeded")
        provider.assert_not_called()

    def test_batch_capture_intent_does_not_request_calendar_without_reservation(self):
        value = WorkIntent.model_validate({**intent("capture").model_dump(),
            "selection": {**intent().selection.model_dump(), "task_refs": [], "duration_minutes": None,
                "day": "any", "date": None, "start_time": None, "end_time": None}})
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": value.model_dump_json()}]}}]}
        with patch("focusos_api.unified_commands.api_key", return_value="synthetic"), patch("focusos_api.unified_commands.request", return_value=response):
            parsed = infer_work(BODY, [], NOW.isoformat(), "Asia/Jakarta")
        self.assertEqual(parsed.action, "capture")
        self.assertEqual(parsed.selection.task_refs, [])


class BatchPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        body_hash = hashlib.sha256(BODY.encode()).hexdigest()
        self.store.source = self.store.source.model_copy(update={"kind": "manual", "normalized_body": BODY, "body_hash": body_hash})
        self.store.record = self.store.record.model_copy(update={"content_hash": body_hash,
            "validated_payload": payload(self.store.source.source_ref)})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in ("confirmation", "memories", "memory_embeddings"):
            self.stack.enter_context(patch(f"focusos_api.{module}.scoped_client", self.store.scoped))
        for module in ("confirmation", "memories"):
            self.stack.enter_context(patch(f"focusos_api.{module}.get_source", return_value=self.store.source))
        self.stack.enter_context(patch("focusos_api.memory_embeddings.embed_text", return_value=[0.1] * 256))

    def response(self):
        return ExtractionEnvelopeResponse(extraction=self.store.record, replayed=False)

    def test_batch_persists_three_independent_tasks_and_searchable_memories(self):
        first = capture_ready("synthetic", self.response())
        self.assertEqual((first["tasks_saved"], first["memories_saved"]), (3, 3))
        self.assertEqual([row["due_date"] for row in self.store.tasks.values()], [d[2] for d in DETAILS])
        self.assertEqual([row["estimate_minutes"] for row in self.store.tasks.values()], [30, 60, 120])
        self.assertEqual([row["priority"] for row in self.store.tasks.values()], ["normal", "high", "low"])
        self.assertEqual({row["evidence_quote"] for row in self.store.memories.values()}, set(ITEMS))
        for memory in self.store.memories.values():
            self.assertEqual(embed_memory("synthetic", UUID(memory["id"])).state, "ready")
        self.assertTrue(all(row["embedding_status"] == "ready" for row in self.store.memories.values()))
        replay = capture_ready("synthetic", self.response())
        self.assertEqual((replay["tasks_saved"], replay["memories_saved"]), (3, 3))
        self.assertEqual((len(self.store.tasks), len(self.store.memories)), (3, 3))

    def test_partial_write_retry_preserves_saved_tasks_and_finishes_remaining_item(self):
        original = self.store.rpc
        failed = False
        def rpc(name, args):
            nonlocal failed
            if name == "focusos_confirm_extraction_task" and args["p_local_ref"] == "task-2" and not failed:
                failed = True
                from focusos_api.database import DatabaseUnavailable
                raise DatabaseUnavailable("synthetic temporary failure")
            return original(name, args)
        with patch.object(self.store, "rpc", side_effect=rpc):
            partial = capture_ready("synthetic", self.response())
        self.assertEqual((partial["tasks_saved"], partial["task_failures"]), (2, 1))
        self.store.tasks["task-1"]["title"] = "User edited title"
        self.store.record = self.store.record.model_copy(update={"confirmed_item_keys": ["task-1", "task-3"]})
        recovered = capture_ready("synthetic", self.response())
        self.assertEqual((recovered["tasks_saved"], recovered["task_failures"]), (3, 0))
        self.assertEqual(self.store.tasks["task-1"]["title"], "User edited title")
        self.assertEqual((len(self.store.tasks), len(self.store.memories)), (3, 3))

    def test_nonready_batch_never_saves_any_task(self):
        record = self.store.record.model_copy(update={"status": "failed", "validated_payload": None, "safe_error": "batch_incomplete"})
        with patch("focusos_api.auto_capture.confirm_candidate") as confirm:
            result = capture_ready("synthetic", ExtractionEnvelopeResponse(extraction=record, replayed=False))
        self.assertEqual(result["tasks_saved"], 0)
        confirm.assert_not_called()
        step = _capture_step("synthetic", {"checkpoint": {}, "result": {}}, SimpleNamespace(extraction=record))
        self.assertEqual(step.status, "failed")
        self.assertIn("every task", step.result["message"])


class BatchCommandTests(unittest.TestCase):
    def setUp(self):
        self.h = UnifiedHarness().enter()
        self.addCleanup(self.h.close)
        self.h.work_intent = intent("capture")

    def test_one_request_captures_and_indexes_all_memories_without_calendar_writes(self):
        captured = SimpleNamespace(extraction=SimpleNamespace(status="ready"),
            capture={"tasks_saved": 3, "memories_saved": 3, "memory_ids": [str(uuid4()) for _ in range(3)]})
        with patch("focusos_api.unified_commands.create_manual_source", return_value=SimpleNamespace(source=SimpleNamespace(id=self.h.source_id))) as source, patch(
            "focusos_api.unified_commands.process_and_capture", return_value=captured), patch(
            "focusos_api.unified_commands.embed_memory", return_value=SimpleNamespace(state="ready")) as embed:
            first, job = self.h.drain(self.h.start(BODY))
            self.assertEqual(first.status, "succeeded")
            self.assertEqual((first.result["tasks_saved"], first.result["memories_saved"]), (3, 3))
            self.assertEqual((source.call_count, embed.call_count, self.h.insert_count), (1, 3, 0))
            replay, _ = self.h.drain(job)
            self.assertEqual(replay.result["tasks_saved"], 3)
            self.assertEqual(source.call_count, 1)

    def test_batch_limit_is_explained_before_capture_or_intent_call(self):
        body = "Buat task berikut:\n" + "\n".join(f"{i}. Deliverable {i}." for i in range(1, 12))
        with patch("focusos_api.unified_commands.infer_work") as infer, patch("focusos_api.unified_commands.create_manual_source") as source:
            step, _ = self.h.drain(self.h.start(body))
        self.assertEqual(step.status, "failed")
        self.assertIn("at most 10", step.result["message"])
        infer.assert_not_called()
        source.assert_not_called()

    def test_incomplete_batch_gives_clear_alert_without_repeating_provider_retries(self):
        response = SimpleNamespace(extraction=SimpleNamespace(status="failed", safe_error="batch_incomplete"))
        with patch("focusos_api.unified_commands.create_manual_source", return_value=SimpleNamespace(source=SimpleNamespace(id=self.h.source_id))), patch(
            "focusos_api.unified_commands.process_and_capture", return_value=response) as process:
            step, _ = self.h.drain(self.h.start(BODY))
        self.assertEqual(step.status, "failed")
        self.assertIn("every task", step.result["message"])
        self.assertEqual(process.call_count, 1)
        self.assertEqual(self.h.insert_count, 0)
