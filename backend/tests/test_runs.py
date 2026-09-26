import unittest
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4
from unittest.mock import Mock, patch

from focusos_api.extractor import ExtractionFailure, ModelCall
from focusos_api.runs import recorded_extraction

class RunLogTests(unittest.TestCase):
    def test_failure_log_stores_only_safe_code(self):
        run_id = uuid4()
        calls = []
        @contextmanager
        def client(_):
            class DB:
                def rpc(self, name, args):
                    calls.append((name, args))
                    return Mock(execute=lambda: Mock(data=str(run_id) if name == "focusos_start_extraction_run" else True))
            yield ("owner", DB())
        with patch("focusos_api.runs.scoped_client", client), patch("focusos_api.runs.extract_structured", side_effect=ExtractionFailure("timeout")):
            with self.assertRaises(ExtractionFailure):
                recorded_extraction("secret-token", uuid4(), "source-1", "body",
                    datetime.fromisoformat("2026-09-21T09:00:00+07:00"), "Asia/Jakarta")
        outcome = calls[1][1]
        self.assertEqual(outcome["p_safe_error"], "timeout")
        self.assertEqual(outcome["p_status"], "failed")
        self.assertNotIn("secret-token", str(calls))
        self.assertNotIn("body", str(calls))

if __name__ == "__main__":
    unittest.main()
