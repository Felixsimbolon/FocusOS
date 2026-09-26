import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from focusos_api.memory_embeddings import EmbeddingError, EMBED_DIM, embed_text, embed_memory


class EmbeddingTests(unittest.TestCase):
    def test_valid_256_vector(self):
        response = Mock(status_code=200, content=b'{}')
        response.json.return_value = {"model": "text-embedding-3-small",
            "data": [{"embedding": [0.1] * EMBED_DIM}]}
        with patch.dict("os.environ", {"FOCUSOS_OPENAI_API_KEY": "synthetic-key"}), \
             patch("focusos_api.memory_embeddings.httpx.post", return_value=response) as post:
            vector = embed_text("Confirmed fact\nEvidence: exact quote")
        self.assertEqual(len(vector), EMBED_DIM)
        self.assertEqual(post.call_args.kwargs["json"]["dimensions"], 256)

    def test_dimension_mismatch_fails(self):
        response = Mock(status_code=200, content=b'{}')
        response.json.return_value = {"model": "text-embedding-3-small",
            "data": [{"embedding": [0.1] * 255}]}
        with patch.dict("os.environ", {"FOCUSOS_OPENAI_API_KEY": "synthetic-key"}), \
             patch("focusos_api.memory_embeddings.httpx.post", return_value=response):
            with self.assertRaises(EmbeddingError):
                embed_text("Fact")

    def test_missing_key_fails_without_provider_call(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch("focusos_api.memory_embeddings.httpx.post") as post:
            with self.assertRaises(EmbeddingError) as caught:
                embed_text("Fact")
        self.assertEqual(caught.exception.code, "provider_unconfigured")
        post.assert_not_called()

    def test_reused_claim_avoids_provider(self):
        memory_id = uuid4()
        client = Mock()
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"text": "Fact", "evidence_quote": "Quote", "status": "active"}]
        context = Mock()
        context.__enter__ = Mock(return_value=("owner", client))
        context.__exit__ = Mock(return_value=False)
        with patch("focusos_api.memory_embeddings.scoped_client", return_value=context), \
             patch("focusos_api.memory_embeddings._rpc", return_value={"state": "reused"}), \
             patch("focusos_api.memory_embeddings.embed_text") as provider:
            result = embed_memory("session", memory_id)
        self.assertEqual(result.state, "reused")
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
