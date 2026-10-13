"""Grounded answers over tasks, memories and scheduled work; provider and DB are simulated."""
import json
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from focusos_api.memory_answers import AnswersUnavailable, answer_questions
from focusos_api.memory_embeddings import refresh_stale_embeddings
from focusos_api.memory_search import MemoryMatch, hybrid_matches, query_terms

NOW = datetime(2026, 10, 14, 2, tzinfo=timezone.utc).isoformat()


def task(title, **changes):
    values = {"id": uuid4(), "title": title, "description": None, "status": "open", "priority": "normal",
              "due_kind": "date", "due_date": date(2026, 10, 18), "due_at": None, "estimate_minutes": 60,
              "source_id": uuid4()}
    return SimpleNamespace(**{**values, **changes})


def memory(text):
    return MemoryMatch(id=uuid4(), text=text, evidence_quote=text, source_id=uuid4(), source_ref="manual:synthetic",
                       project_id=None, match_kind="hybrid", score=0.03)


def provider(answers):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({"answers": answers})}]}}]}


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.tasks = [task("Buat halaman web"), task("Siapkan outline presentasi", status="done")]
        self.memories = [memory("Audiens demo adalah backend engineers.")]
        patches = {
            "focusos_api.memory_answers.api_key": lambda: "synthetic",
            "focusos_api.memory_answers.refresh_stale_embeddings": lambda *_: 0,
            "focusos_api.memory_answers.list_tasks": lambda *a, **k: SimpleNamespace(tasks=self.tasks, truncated=False),
            "focusos_api.memory_answers._scheduled_work": lambda *_: [],
            "focusos_api.memory_answers.embed_text": lambda *_: [0.1] * 256,
            "focusos_api.memory_answers.hybrid_matches": lambda *_: self.memories,
        }
        for target, fake in patches.items():
            started = patch(target, side_effect=fake); started.start(); self.addCleanup(started.stop)

    def ask(self, answers, questions=("Kapan deadline halaman web?",)):
        with patch("focusos_api.memory_answers.gemini_request", return_value=provider(answers)) as model:
            result = answer_questions("session", list(questions), NOW, "Asia/Jakarta")
        return result, model

    def test_answer_cites_the_saved_task_with_its_deadline(self):
        result, model = self.ask([{"question_index": 0, "status": "answered", "answer": "Deadline 18 Oktober 2026.", "refs": ["T1"]}])
        self.assertEqual(result[0]["status"], "answered")
        self.assertEqual(result[0]["answer"], "Deadline 18 Oktober 2026.")
        self.assertEqual(result[0]["references"][0]["title"], "Buat halaman web")
        self.assertIn("due 2026-10-18", result[0]["references"][0]["detail"])
        # The model sees structured task fields, not only memory text.
        context = json.loads(model.call_args.args[0]["contents"][0]["parts"][0]["text"])
        self.assertEqual(context["references"][0]["due"], "2026-10-18")
        self.assertEqual(context["references"][1]["status"], "done")

    def test_model_context_never_contains_database_ids(self):
        _, model = self.ask([{"question_index": 0, "status": "no_reference", "answer": "", "refs": []}])
        body = model.call_args.args[0]["contents"][0]["parts"][0]["text"]
        for item in [*self.tasks, *self.memories]:
            self.assertNotIn(str(item.id), body)
            self.assertNotIn(str(item.source_id), body)
        self.assertIn("untrusted", model.call_args.args[0]["systemInstruction"]["parts"][0]["text"])

    def test_missing_answer_is_reported_as_no_reference(self):
        result, _ = self.ask([{"question_index": 0, "status": "no_reference", "answer": "", "refs": []}],
                             questions=("Berapa budget proyek Nusa?",))
        self.assertEqual(result[0], {"question": "Berapa budget proyek Nusa?", "status": "no_reference", "answer": None, "references": []})

    def test_answer_without_a_valid_citation_is_not_trusted(self):
        for refs in ([], ["T99"], ["invented"]):
            with self.subTest(refs=refs):
                result, _ = self.ask([{"question_index": 0, "status": "answered", "answer": "Rp 10 juta.", "refs": refs}])
                self.assertEqual(result[0]["status"], "no_reference")
                self.assertIsNone(result[0]["answer"])

    def test_several_questions_are_answered_independently(self):
        result, _ = self.ask([
            {"question_index": 1, "status": "answered", "answer": "Backend engineers.", "refs": ["M1"]},
            {"question_index": 0, "status": "answered", "answer": "Sudah selesai.", "refs": ["T2", "T2"]},
        ], questions=("Outline presentasi sudah selesai?", "Siapa audiens demo?", "Kapan rapat tim?"))
        self.assertEqual([item["status"] for item in result], ["answered", "answered", "unavailable"])
        self.assertEqual(len(result[0]["references"]), 1)
        self.assertEqual(result[1]["references"][0]["kind"], "memory")

    def test_no_saved_data_answers_no_reference_without_a_model_call(self):
        self.tasks, self.memories = [], []
        result, model = self.ask([])
        self.assertEqual(result[0]["status"], "no_reference")
        model.assert_not_called()

    def test_transport_failure_is_retryable_and_bad_output_is_unavailable(self):
        with patch("focusos_api.memory_answers.gemini_request", side_effect=httpx.ConnectError("down")):
            with self.assertRaises(AnswersUnavailable):
                answer_questions("session", ["Kapan deadline?"], NOW, "Asia/Jakarta")
        result, _ = self.ask([{"question_index": "0", "status": "answered", "answer": "x", "refs": ["T1"]}])
        self.assertEqual(result[0]["status"], "unavailable")

    def test_stale_embeddings_are_refreshed_before_searching(self):
        with patch("focusos_api.memory_answers.refresh_stale_embeddings") as refresh:
            self.ask([{"question_index": 0, "status": "no_reference", "answer": "", "refs": []}])
        refresh.assert_called_once_with("session")


class RetrievalTests(unittest.TestCase):
    def test_question_words_are_not_required_search_terms(self):
        self.assertEqual(query_terms("Kapan deadline tugas halaman web saya?"), ["deadline", "tugas", "halaman", "web"])
        self.assertEqual(query_terms("What is the code name for the demo?"), ["code", "name", "demo"])
        self.assertEqual(query_terms("apa?"), [])
        self.assertLessEqual(len(query_terms(" ".join(f"word{i}" for i in range(40)))), 16)

    def test_hybrid_search_sends_or_terms_and_vector(self):
        client = MagicMock()
        client.rpc.return_value.execute.return_value.data = []
        @contextmanager
        def scoped(*_): yield "owner", client
        with patch("focusos_api.memory_search.scoped_client", scoped):
            hybrid_matches("session", "Kapan deadline web?", [0.5] * 256, 8)
        name, args = client.rpc.call_args.args
        self.assertEqual(name, "focusos_search_memories_hybrid")
        self.assertEqual(args["p_terms"], ["deadline", "web"])
        self.assertEqual(args["p_limit"], 8)
        self.assertTrue(args["p_vector"].startswith("[0.5,"))

    def test_edited_task_memories_are_reindexed(self):
        client = MagicMock()
        query = client.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value
        ids = [str(uuid4()), str(uuid4())]
        query.order.return_value.limit.return_value.execute.return_value.data = [{"id": value} for value in ids]
        @contextmanager
        def scoped(*_): yield "owner", client
        states = iter(["ready", "failed"])
        with patch("focusos_api.memory_embeddings.scoped_client", scoped), \
             patch("focusos_api.memory_embeddings.embed_memory", side_effect=lambda *_: SimpleNamespace(state=next(states))) as embed:
            self.assertEqual(refresh_stale_embeddings("session"), 1)
        self.assertEqual([str(call.args[1]) for call in embed.call_args_list], ids)
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.assert_called_once_with(
            "embedding_status", ["pending", "failed"])


if __name__ == "__main__":
    unittest.main()
