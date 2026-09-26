import unittest
from datetime import datetime
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from focusos_api.main import app
from focusos_api.sources import ManualSourceInput, normalize_source


class SourceValidationTests(unittest.TestCase):
    def test_normalizes_line_endings_and_rejects_oversize_utf8(self):
        self.assertEqual(normalize_source(" A  \r\n B \x00"), "A\n B")
        with self.assertRaises(ValueError):
            normalize_source("é" * 10241)

    def test_requires_aware_received_at(self):
        with self.assertRaises(ValidationError):
            ManualSourceInput(title="Test", text="body", received_at=datetime(2026, 9, 27))

    def test_anonymous_route_denied_and_no_database_access(self):
        client = TestClient(app)
        with patch("focusos_api.main.create_manual_source") as create:
            response = client.post("/sources/manual", json={"title": "Synthetic", "text": "Finish slides"}, headers={"Idempotency-Key": str(uuid4())})
        self.assertEqual(response.status_code, 401)
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
