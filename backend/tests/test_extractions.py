import unittest
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from focusos_api.main import app
from focusos_api.extractions import process_extraction, read_extraction, ExtractionRecord

class ExtractionRouteTests(unittest.TestCase):
    def test_anonymous_extraction_denied(self):
        response = TestClient(app).post("/sources/" + str(uuid4()) + "/extract")
        self.assertEqual(response.status_code, 401)

    def test_saved_confirmation_is_returned_after_extraction_reload(self):
        source_id, result_id = uuid4(), uuid4()
        source = Mock(id=source_id, body_hash="a" * 64)
        now = datetime.fromisoformat("2026-09-27T10:00:00+07:00")
        record = ExtractionRecord(id=result_id, source_id=source_id, content_hash="a" * 64,
            schema_version="1", prompt_version="1", model_version="gemini-3.5-flash-lite",
            status="ready", validated_payload={}, safe_error=None, run_id=None,
            created_at=now, updated_at=now, reviewed_at=now)
        extraction_query, task_query = Mock(), Mock()
        for query in (extraction_query, task_query):
            query.select.return_value = query
            query.eq.return_value = query
            query.limit.return_value = query
        extraction_query.execute.return_value = Mock(data=[record.model_dump(mode="json")])
        task_query.execute.return_value = Mock(data=[{"extraction_item_key": "task-1"}])
        db = Mock()
        db.table.side_effect = lambda name: extraction_query if name == "extraction_results" else task_query

        @contextmanager
        def client(_):
            yield ("owner", db)

        with patch("focusos_api.extractions.get_source", return_value=source), patch(
            "focusos_api.extractions.scoped_client", client
        ):
            loaded = read_extraction("token", source_id)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.confirmed_item_keys, ["task-1"])
        task_query.eq.assert_any_call("user_id", "owner")
        task_query.eq.assert_any_call("extraction_result_id", str(result_id))

    def test_completed_claim_replays_without_model_call(self):
        source_id, result_id = uuid4(), uuid4()
        source = Mock(id=source_id, normalized_body="text", body_hash="a"*64)
        @contextmanager
        def client(_):
            class DB:
                def rpc(self, name, args):
                    return Mock(execute=lambda: Mock(data={"state":"ready","id":str(result_id)}))
            yield ("owner", DB())
        now = datetime.fromisoformat("2026-09-27T10:00:00+07:00")
        record = ExtractionRecord(id=result_id, source_id=source_id, content_hash="a"*64,
            schema_version="1", prompt_version="1", model_version="gpt-4.1-mini",
            status="ready", validated_payload={}, safe_error=None, run_id=None,
            created_at=now, updated_at=now, reviewed_at=None)
        with patch("focusos_api.extractions.get_source", return_value=source), patch("focusos_api.extractions.scoped_client", client), patch("focusos_api.extractions._read_result", return_value=record), patch("focusos_api.extractions.recorded_extraction") as model:
            response = process_extraction("token", source_id)
        self.assertTrue(response.replayed)
        self.assertEqual(response.extraction, record)
        model.assert_not_called()

if __name__ == "__main__":
    unittest.main()
