import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from focusos_api.memory_embeddings import EmbeddingError
from focusos_api.memory_search import MemorySearchInput, search_memories


class MemorySearchTests(unittest.TestCase):
    def _client(self, data):
        client = Mock()
        client.rpc.return_value.execute.return_value.data = data
        context = Mock()
        context.__enter__ = Mock(return_value=("owner", client))
        context.__exit__ = Mock(return_value=False)
        return client, context

    def test_lexical_fallback_is_explicit(self):
        client, context = self._client([])
        with patch("focusos_api.memory_search.embed_text", side_effect=EmbeddingError("provider_unconfigured")), \
             patch("focusos_api.memory_search.scoped_client", return_value=context):
            result = search_memories("session", MemorySearchInput(query="calendar", limit=3))
        self.assertEqual(result.mode, "lexical_fallback")
        self.assertIsNone(client.rpc.call_args.args[1]["p_vector"])
        self.assertEqual(client.rpc.call_args.args[1]["p_limit"], 3)

    def test_query_embedding_and_project_scope(self):
        client, context = self._client([])
        project = uuid4()
        with patch("focusos_api.memory_search.embed_text", return_value=[0.1] * 256), \
             patch("focusos_api.memory_search.scoped_client", return_value=context):
            result = search_memories("session", MemorySearchInput(
                query="demo", project_id=project))
        self.assertEqual(result.mode, "semantic_enabled")
        self.assertEqual(client.rpc.call_args.args[1]["p_project_id"], str(project))
        self.assertTrue(client.rpc.call_args.args[1]["p_vector"].startswith("["))

    def test_invalid_limit_rejected(self):
        with self.assertRaises(Exception):
            MemorySearchInput(query="demo", limit=50)


if __name__ == "__main__":
    unittest.main()
