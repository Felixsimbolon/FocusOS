import unittest
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import Mock,patch
from fastapi.testclient import TestClient

from focusos_api.gmail_processing import process_one_gmail_source
from focusos_api.main import app

class HandoffTests(unittest.TestCase):
    def test_no_pending_does_not_call_model(self):
        @contextmanager
        def client(_):
            yield ("owner",Mock(rpc=lambda name,args:Mock(execute=lambda:Mock(data=None))))
        with patch("focusos_api.gmail_processing.scoped_client",client), patch("focusos_api.gmail_processing.process_and_capture") as extract:
            result=process_one_gmail_source("token")
        self.assertEqual(result.state,"no_pending")
        extract.assert_not_called()

    def test_uses_existing_extraction_service(self):
        source_id=uuid4()
        @contextmanager
        def client(_):
            yield ("owner",Mock(rpc=lambda name,args:Mock(execute=lambda:Mock(data=str(source_id)))))
        from focusos_api.extractions import ExtractionEnvelopeResponse,ExtractionRecord
        from datetime import datetime
        now=datetime.fromisoformat("2026-09-27T10:00:00+07:00")
        record=ExtractionRecord(id=uuid4(),source_id=source_id,content_hash="a"*64,
          schema_version="1",prompt_version="1",model_version="gpt-4.1-mini",
          status="ready",validated_payload={"tasks":[]},safe_error=None,
          run_id=None,created_at=now,updated_at=now,reviewed_at=None)
        with patch("focusos_api.gmail_processing.scoped_client",client), patch("focusos_api.gmail_processing.process_and_capture",return_value=ExtractionEnvelopeResponse(extraction=record,replayed=False)) as extract:
            result=process_one_gmail_source("token")
        self.assertEqual(result.state,"ready")
        extract.assert_called_once_with("token",source_id)

    def test_anonymous_route(self):
        self.assertEqual(TestClient(app).post("/connections/google/gmail/process-one").status_code,401)

if __name__=="__main__": unittest.main()
