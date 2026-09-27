import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import observation
from validate import load_cases


class RunnerTests(unittest.TestCase):
    def test_dry_run_does_not_call_provider_or_claim_success(self):
        row = load_cases()[0]
        with patch("run.extract_structured") as provider:
            record = observation(row, False)
        provider.assert_not_called()
        self.assertEqual(record["status"], "skipped")
        self.assertNotIn(row["body"], str(record))

    def test_missing_provider_is_recorded_as_failure(self):
        from focusos_api.extractor import ExtractionFailure
        row = load_cases()[0]
        with patch("run.extract_structured", side_effect=ExtractionFailure("provider_unconfigured")):
            record = observation(row, True)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["failure_code"], "provider_unconfigured")
        self.assertEqual(record["tasks"], [])


if __name__ == "__main__":
    unittest.main()
