"""Knowledge graph: grounding, best-effort indexing, and graph references in answers. Providers/DB simulated."""
import json
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from focusos_api.database import DatabaseUnavailable
from focusos_api.knowledge_graph import MemoryGraph, extract, graph_matches, grounded, index_memories

AUDIENCE = "Audiens demo Nusa adalah backend engineers."
CODENAME = "Kode nama proyek demo FocusOS adalah Nusa."


def graph(entities, relations, ref="m1"):
    return MemoryGraph.model_validate({"ref": ref, "entities": entities, "relations": relations})


class GroundingTests(unittest.TestCase):
    def test_keeps_only_names_and_values_found_in_the_memory(self):
        value = graph([{"key": "nusa", "kind": "project", "name": "Nusa"}, {"key": "ghost", "kind": "person", "name": "Maria"}],
                      [{"subject": "nusa", "predicate": "audience", "object": None, "object_text": "backend engineers"},
                       {"subject": "ghost", "predicate": "owner_of", "object": "nusa", "object_text": None},
                       {"subject": "nusa", "predicate": "budget", "object": None, "object_text": "50 juta"}])
        entities, relations = grounded(value, AUDIENCE)
        self.assertEqual(entities, [{"key": "nusa", "kind": "project", "name": "Nusa"}])
        self.assertEqual(relations, [{"subject": "nusa", "predicate": "audience", "object_text": "backend engineers"}])

    def test_relations_need_exactly_one_object(self):
        value = graph([{"key": "a", "kind": "project", "name": "Nusa"}, {"key": "b", "kind": "project", "name": "FocusOS"}],
                      [{"subject": "b", "predicate": "code_name", "object": "a", "object_text": "Nusa"},
                       {"subject": "b", "predicate": "code_name", "object": None, "object_text": None},
                       {"subject": "b", "predicate": "code_name", "object": "a", "object_text": None}])
        self.assertEqual(grounded(value, CODENAME)[1], [{"subject": "b", "predicate": "code_name", "object": "a"}])

    def test_invalid_kinds_and_predicates_are_rejected(self):
        with self.assertRaises(Exception):
            graph([], [{"subject": "a", "predicate": "Drop Table", "object": None, "object_text": "x"}])
        entities, _ = grounded(graph([{"key": "a", "kind": "secret", "name": "Nusa"}], []), AUDIENCE)
        self.assertEqual(entities, [])


class IndexTests(unittest.TestCase):
    def test_indexes_each_memory_with_grounded_entities(self):
        rows = [{"id": str(uuid4()), "text": AUDIENCE, "evidence_quote": AUDIENCE}]
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.execute.return_value.data = rows
        response = {"m1": graph([{"key": "nusa", "kind": "project", "name": "Nusa"}], [])}
        with patch("focusos_api.knowledge_graph.scoped_client") as scoped, patch("focusos_api.knowledge_graph.extract", return_value=response):
            scoped.return_value.__enter__.return_value = ("owner", client)
            self.assertEqual(index_memories("session", [rows[0]["id"]]), 1)
        name, args = client.rpc.call_args.args
        self.assertEqual(name, "focusos_save_memory_graph")
        self.assertEqual(args["p_entities"], [{"key": "nusa", "kind": "project", "name": "Nusa"}])

    def test_provider_outage_skips_indexing(self):
        with patch("focusos_api.knowledge_graph.scoped_client", side_effect=DatabaseUnavailable("x")):
            self.assertEqual(index_memories("session", [str(uuid4())]), 0)
        self.assertEqual(index_memories("session", []), 0)

    def test_extract_uses_a_closed_schema_and_labels_the_call(self):
        reply = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(
            {"memories": [{"ref": "m1", "entities": [], "relations": []}]})}]}}]}
        with patch("focusos_api.knowledge_graph.api_key", return_value="synthetic"), \
             patch("focusos_api.knowledge_graph.gemini_request", return_value=reply) as request:
            result = extract([{"ref": "m1", "text": AUDIENCE}])
        self.assertIn("m1", result)
        self.assertEqual(request.call_args.kwargs["purpose"], "graph")

    def test_question_terms_drive_the_graph_search(self):
        client = MagicMock()
        client.rpc.return_value.execute.return_value.data = [{"id": "1", "text": AUDIENCE, "evidence_quote": AUDIENCE, "hop": 1, "path": "FocusOS → code_name → Nusa"}]
        with patch("focusos_api.knowledge_graph.scoped_client") as scoped:
            scoped.return_value.__enter__.return_value = ("owner", client)
            rows = graph_matches("session", "Siapa audiens demo FocusOS?")
        name, args = client.rpc.call_args.args
        self.assertEqual(name, "focusos_graph_memories")
        self.assertIn("focusos", args["p_terms"])
        self.assertEqual((args["p_hops"], rows[0]["hop"]), (2, 1))


class GraphAnswerTests(unittest.TestCase):
    def test_graph_memories_become_cited_references_with_their_path(self):
        from focusos_api import memory_answers
        captured = {}
        def model(payload, **_):
            captured["context"] = json.loads(payload["contents"][0]["parts"][0]["text"])
            return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({"answers": [
                {"question_index": 0, "status": "answered", "answer": "Backend engineers.", "refs": ["G1"]}]})}]}}]}
        graph_row = {"id": str(uuid4()), "text": AUDIENCE, "evidence_quote": AUDIENCE, "hop": 1, "path": "FocusOS → code_name → Nusa"}
        with patch.object(memory_answers, "api_key", return_value="synthetic"), \
             patch.object(memory_answers, "refresh_stale_embeddings", return_value=0), \
             patch.object(memory_answers, "list_tasks", return_value=type("L", (), {"tasks": []})()), \
             patch.object(memory_answers, "_scheduled_work", return_value=[]), \
             patch.object(memory_answers, "_memories", return_value=[]), \
             patch.object(memory_answers.knowledge_graph, "graph_matches", return_value=[graph_row]), \
             patch.object(memory_answers, "gemini_request", side_effect=model):
            [answer] = memory_answers.answer_questions("session", ["Siapa audiens demo FocusOS?"], "2026-10-16T09:00:00+07:00", "Asia/Jakarta")
        self.assertEqual(answer["status"], "answered")
        self.assertEqual(answer["references"][0]["title"], AUDIENCE)
        reference = next(item for item in captured["context"]["references"] if item["ref"] == "G1")
        self.assertEqual(reference["path"], "FocusOS → code_name → Nusa")

    def test_graph_failure_never_blocks_answers(self):
        from focusos_api import memory_answers
        with patch.object(memory_answers.knowledge_graph, "graph_matches", side_effect=RuntimeError("down")):
            self.assertEqual(memory_answers._graph_memories("session", ["x"], set()), [])


if __name__ == "__main__":
    unittest.main()
