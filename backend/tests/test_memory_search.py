import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from focusos_api.gemini import GeminiResponseError
from focusos_api.memory_embeddings import EmbeddingError
from focusos_api.memory_search import (
    MemoryMatch, MemorySearchInput, _select_answer_index, search_memories,
)


class MemorySearchTests(unittest.TestCase):
    def _client(self, data):
        client = Mock()
        client.rpc.return_value.execute.return_value.data = data
        context = Mock()
        context.__enter__ = Mock(return_value=("owner", client))
        context.__exit__ = Mock(return_value=False)
        return client, context

    def _match(self, text):
        return {
            "id": str(uuid4()), "text": text, "evidence_quote": text,
            "source_id": str(uuid4()), "source_ref": "synthetic",
            "project_id": None, "match_kind": "semantic", "score": 0.4,
        }

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

    def test_grounded_answer_uses_selected_candidate(self):
        rows = [self._match("The team meets Monday."),
                self._match("The code name for the FocusOS demo project is Aurora.")]
        _, context = self._client(rows)
        with patch("focusos_api.memory_search.embed_text", return_value=[0.1] * 256), \
             patch("focusos_api.memory_search.scoped_client", return_value=context), \
             patch("focusos_api.memory_search._select_answer_index", return_value=1):
            result = search_memories("session", MemorySearchInput(query="What is the code name?", answer=True))
        self.assertEqual(result.answer_status, "found")
        self.assertEqual(result.answer.text, rows[1]["text"])
        self.assertEqual(len(result.matches), 2)

    def test_unanswerable_query_does_not_choose_related_fact(self):
        rows = [self._match("The team meets Monday.")]
        _, context = self._client(rows)
        with patch("focusos_api.memory_search.embed_text", return_value=[0.1] * 256), \
             patch("focusos_api.memory_search.scoped_client", return_value=context), \
             patch("focusos_api.memory_search._select_answer_index", return_value=-1):
            result = search_memories("session", MemorySearchInput(query="What is the code name?", answer=True))
        self.assertEqual(result.answer_status, "not_found")
        self.assertIsNone(result.answer)

    def test_answer_selection_failure_does_not_turn_related_fact_into_answer(self):
        rows = [self._match("The team meets Monday.")]
        _, context = self._client(rows)
        with patch("focusos_api.memory_search.embed_text", return_value=[0.1] * 256), \
             patch("focusos_api.memory_search.scoped_client", return_value=context), \
             patch("focusos_api.memory_search._select_answer_index",
                   side_effect=GeminiResponseError("provider_unavailable")):
            result = search_memories("session", MemorySearchInput(query="What is the code name?", answer=True))
        self.assertEqual(result.answer_status, "unavailable")
        self.assertIsNone(result.answer)

    def test_selector_rejects_invalid_model_index(self):
        match = MemoryMatch.model_validate(self._match("The team meets Monday."))
        with patch("focusos_api.memory_search.api_key", return_value="configured"), \
             patch("focusos_api.memory_search.gemini_request", return_value={}), \
             patch("focusos_api.memory_search.output_text", return_value='{"index": 9}'):
            with self.assertRaises(GeminiResponseError):
                _select_answer_index("What is the code name?", [match])

    def test_invalid_limit_rejected(self):
        with self.assertRaises(Exception):
            MemorySearchInput(query="demo", limit=50)


if __name__ == "__main__":
    unittest.main()
