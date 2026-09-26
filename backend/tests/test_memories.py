import unittest
from uuid import uuid4
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from focusos_api.memories import MemoryInput, confirm_memory, supersede_memory
from focusos_api.main import app


class MemoryTests(unittest.TestCase):
    def test_contract_rejects_blank_or_oversize(self):
        with self.assertRaises(Exception):
            MemoryInput(request_key=uuid4(), source_id=uuid4(), text="", evidence_quote="quote")
        with self.assertRaises(Exception):
            MemoryInput(request_key=uuid4(), source_id=uuid4(), text="Fact", evidence_quote="x" * 501)

    def test_confirm_uses_owner_scoped_rpc(self):
        memory_id, source_id = uuid4(), uuid4()
        data = {"id": str(memory_id), "source_id": str(source_id), "project_id": None,
                "source_hash": "a" * 64, "text": "Confirmed fact", "evidence_quote": "Exact quote",
                "status": "active", "created_at": "2026-09-27T00:00:00Z"}
        client = Mock()
        client.rpc.return_value.execute.return_value.data = data
        context = Mock()
        context.__enter__ = Mock(return_value=("owner", client))
        context.__exit__ = Mock(return_value=False)
        with patch("focusos_api.memories.get_source", return_value=Mock(normalized_body="Exact quote here")), \
             patch("focusos_api.memories.scoped_client", return_value=context):
            result = confirm_memory("session", MemoryInput(
                request_key=uuid4(), source_id=source_id,
                text="Confirmed fact", evidence_quote="Exact quote"))
        self.assertEqual(result.id, memory_id)
        self.assertEqual(client.rpc.call_args.args[0], "focusos_confirm_memory")

    def test_anonymous_routes(self):
        client = TestClient(app)
        self.assertEqual(client.get("/memories").status_code, 401)
        self.assertEqual(client.post("/memories", json={
            "request_key": str(uuid4()), "source_id": str(uuid4()),
            "text": "Fact", "evidence_quote": "Quote"}).status_code, 401)
        self.assertEqual(client.post(f"/memories/{uuid4()}/supersede").status_code, 401)


if __name__ == "__main__":
    unittest.main()
