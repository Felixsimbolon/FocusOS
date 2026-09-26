import unittest
from uuid import uuid4
from unittest.mock import patch
from fastapi.testclient import TestClient
from pydantic import ValidationError

from focusos_api.main import app
from focusos_api.confirmation import ConfirmInput


class ConfirmTests(unittest.TestCase):
    def test_anonymous_confirmation_is_denied(self):
        result = TestClient(app).post("/extractions/" + str(uuid4()) + "/confirm",
            json={"local_ref":"task-1","task":{"title":"Submit slides"}})
        self.assertEqual(result.status_code, 401)

    def test_review_requires_valid_task_date(self):
        with self.assertRaises(ValidationError):
            ConfirmInput.model_validate({"local_ref":"task-1",
                "task":{"title":"Submit slides","due_kind":"date","due_date":"2026-09-31"}})

    def test_conflict_is_safe(self):
        from focusos_api.confirmation import ConfirmConflict
        with patch("focusos_api.main.confirm_candidate", side_effect=ConfirmConflict()):
            result = TestClient(app).post("/extractions/" + str(uuid4()) + "/confirm",
                json={"local_ref":"task-1","task":{"title":"Submit slides"}},
                headers={"Authorization":"Bearer test-token"})
        self.assertEqual(result.status_code, 409)
        self.assertNotIn("test-token", result.text)

if __name__ == "__main__":
    unittest.main()
