from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4
from fastapi.testclient import TestClient
from focusos_api.main import app
from focusos_api.memories import list_memories, MemoryList

class SourceMemoriesTests(TestCase):
    def test_source_filter_keeps_owner_and_active_status(self):
        source_id = uuid4()
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value.data = []
        client = MagicMock()
        client.table.return_value = query
        @contextmanager
        def scoped(_): yield "owner", client
        with patch("focusos_api.memories.scoped_client", scoped):
            self.assertEqual(list_memories("session", source_id).memories, [])
        self.assertEqual([call.args for call in query.eq.call_args_list],
            [("user_id", "owner"), ("status", "active"), ("source_id", str(source_id))])
        query.limit.assert_called_once_with(50)

    def test_route_validates_source_and_passes_filter(self):
        source_id = uuid4()
        headers = {"Authorization": "Bearer session"}
        with patch("focusos_api.main.list_memories", return_value=MemoryList(memories=[])) as read:
            response = TestClient(app).get(f"/memories?source_id={source_id}", headers=headers)
            self.assertEqual(response.status_code, 200)
            read.assert_called_once_with("session", source_id)
            self.assertEqual(TestClient(app).get("/memories?source_id=bad", headers=headers).status_code, 422)
            self.assertEqual(read.call_count, 1)
