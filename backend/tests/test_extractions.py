import unittest
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from focusos_api.main import app
from focusos_api.extractions import process_extraction, ExtractionRecord

class ExtractionRouteTests(unittest.TestCase):
    def test_anonymous_extraction_denied(self):
        response = TestClient(app).post("/sources/" + str(uuid4()) + "/extract")
        self.assertEqual(response.status_code, 401)

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
