import unittest
from datetime import datetime
from uuid import uuid4
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient
from focusos_api.main import app
from focusos_api.sources import SourceEnvelope, SourceRecord

from focusos_api.auto_capture import capture_ready, task_input
from focusos_api.extraction_contracts import ExtractionEnvelope
from focusos_api.extractions import ExtractionEnvelopeResponse, ExtractionRecord
from test_extraction_contracts import sample


class AutoCaptureTests(unittest.TestCase):
    def test_unresolved_deadline_is_not_guessed(self):
        payload = sample()
        payload["tasks"][0]["deadline"].update(kind="unresolved", value=None, timezone=None, relation=None)
        task = task_input(ExtractionEnvelope.model_validate(payload).tasks[0])
        self.assertEqual(task.due_kind, "none")
        self.assertIsNone(task.due_at)

    def test_ready_extraction_saves_task_and_fact_with_stable_key(self):
        payload = sample()
        payload["facts"] = [{"text": "Presentation is Friday", "kind": "fact",
                             "evidence": [{"source_ref": "source-1",
                                           "quote": "The final presentation is Friday September 25"}]}]
        now = datetime.fromisoformat("2026-09-27T10:00:00+07:00")
        record = ExtractionRecord(
            id=uuid4(), source_id=uuid4(), content_hash="a" * 64,
            schema_version="1", prompt_version="1", model_version="gemini",
            status="ready", validated_payload=payload, safe_error=None,
            run_id=None, created_at=now, updated_at=now, reviewed_at=None)
        response = ExtractionEnvelopeResponse(extraction=record, replayed=False)
        with patch("focusos_api.auto_capture.confirm_candidate") as task, \
             patch("focusos_api.auto_capture.confirm_memory", return_value=Mock(id=uuid4())) as memory:
            first = capture_ready("token", response)
            second = capture_ready("token", response)
        self.assertEqual((first["tasks_saved"], first["memories_saved"]), (1, 1))
        self.assertEqual(first["task_failures"] + first["memory_failures"], 0)
        self.assertEqual(memory.call_args_list[0].args[1].request_key,
                         memory.call_args_list[1].args[1].request_key)
        self.assertEqual(task.call_args.args[2].task.due_date.isoformat(), "2026-09-24")

    def test_manual_source_route_processes_and_captures_immediately(self):
        now = datetime.fromisoformat("2026-09-27T10:00:00+07:00")
        source = SourceRecord(
            id=uuid4(), kind="manual", title="Project note", source_ref="source-1",
            normalized_body="Send a brief.", body_hash="a" * 64,
            normalization_version="1", body_truncated=False,
            received_at=now, created_at=now, body_expires_at=now)
        extraction = ExtractionRecord(
            id=uuid4(), source_id=source.id, content_hash=source.body_hash,
            schema_version="1", prompt_version="1", model_version="gemini",
            status="ready", validated_payload=sample(), safe_error=None,
            run_id=None, created_at=now, updated_at=now, reviewed_at=None)
        outcome = ExtractionEnvelopeResponse(extraction=extraction, replayed=False,
                                             capture={"tasks_saved": 1, "memories_saved": 0})
        with patch("focusos_api.main.create_manual_source",
                   return_value=SourceEnvelope(source=source, replayed=False)), \
             patch("focusos_api.main.process_and_capture", return_value=outcome) as process:
            response = TestClient(app).post("/sources/manual",
                json={"title": "Project note", "text": "Send a brief."},
                headers={"Authorization": "Bearer test-token",
                         "Idempotency-Key": str(uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["extraction"]["capture"]["tasks_saved"], 1)
        process.assert_called_once_with("test-token", source.id)

    def test_failed_extraction_does_not_save(self):
        now = datetime.fromisoformat("2026-09-27T10:00:00+07:00")
        record = ExtractionRecord(
            id=uuid4(), source_id=uuid4(), content_hash="a" * 64,
            schema_version="1", prompt_version="1", model_version="gemini",
            status="failed", validated_payload=None, safe_error="timeout",
            run_id=None, created_at=now, updated_at=now, reviewed_at=None)
        with patch("focusos_api.auto_capture.confirm_candidate") as task:
            result = capture_ready("token", ExtractionEnvelopeResponse(extraction=record, replayed=False))
        self.assertEqual(result["tasks_saved"], 0)
        task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
