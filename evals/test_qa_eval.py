import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qa_eval import (DEFAULT_THRESHOLDS, answer_metrics, check_thresholds, evaluate, hybrid_ranking,
                     legacy_ranking, lexical_ranking, load, score_answer)

CONFIG = {"k": 8, "rrf_k": 60, "semantic_threshold": 0.2}
MEMORIES = [{"id": "M-a", "text": "Audiens demo Nusa adalah backend engineers.", "evidence": "x"},
            {"id": "M-b", "text": "Office Wi-Fi network name is FocusLab-5G.", "evidence": "y"},
            {"id": "M-c", "text": "Gym membership costs 350 thousand rupiah.", "evidence": "z"}]
CORPUS, CASES = load()


class QAEvaluationTests(unittest.TestCase):
    def test_mock_mode_never_calls_a_provider_and_is_labeled(self):
        with patch("focusos_api.gemini.httpx.post") as generate, patch("focusos_api.memory_embeddings.httpx.post") as embed:
            report = evaluate(False, CONFIG)
        generate.assert_not_called(); embed.assert_not_called()
        self.assertFalse(report["provider_called"])
        self.assertIn("not Gemini quality", report["note"])
        self.assertEqual(report["answers"]["cases"], len(CASES))
        self.assertEqual(check_thresholds(report, DEFAULT_THRESHOLDS), [])

    def test_legacy_search_returns_unrelated_memories_but_hybrid_does_not(self):
        self.assertEqual(len(legacy_ranking("Apa password laptop?", None, {}, MEMORIES)), 3)
        self.assertEqual(lexical_ranking("Apa password laptop?", MEMORIES), [])
        self.assertEqual(lexical_ranking("Siapa audiens demo?", MEMORIES), ["M-a"])

    def test_fusion_rewards_agreement_between_signals(self):
        vectors = {"M-a": [1.0, 0.0], "M-b": [0.9, 0.1], "M-c": [0.0, 1.0]}
        ranking = hybrid_ranking("audiens demo", [1.0, 0.0], vectors, MEMORIES, CONFIG)
        self.assertEqual(ranking[0], "M-a")  # Top in both semantic and keyword ranks.
        self.assertNotIn("M-c", ranking)      # Below the semantic threshold and no keyword match.

    def test_answer_scoring_requires_supported_citations(self):
        case = next(case for case in CASES if case["id"] == "q02")
        good = {"status": "answered", "answer": "Backend engineers.",
                "references": [{"kind": "memory", "title": "Audiens demo Nusa adalah backend engineers."}]}
        self.assertTrue(score_answer(case, good, CORPUS)["passed"])
        wrong = {**good, "references": [*good["references"], {"kind": "memory", "title": "Office Wi-Fi network name is FocusLab-5G."}]}
        row = score_answer(case, wrong, CORPUS)
        self.assertEqual((row["citation_precision"], row["passed"]), (0.5, False))
        guess = {**good, "answer": "Product managers."}
        self.assertFalse(score_answer(case, guess, CORPUS)["passed"])

    def test_answering_an_unanswerable_question_counts_as_a_false_answer(self):
        case = next(case for case in CASES if case["id"] == "q24")
        row = score_answer(case, {"status": "answered", "answer": "rahasia123", "references": []}, CORPUS)
        metrics = answer_metrics([row])
        self.assertEqual((row["passed"], metrics["false_answer_rate"]), (False, 1.0))
        report = {"provider_called": True, "retrieval": {"hybrid": {"recall_at_k": 1, "precision_at_k": 1}}, "answers": metrics}
        self.assertIn("false answer rate", check_thresholds(report, DEFAULT_THRESHOLDS)[0])

    def test_cases_cannot_reference_missing_corpus_items(self):
        with tempfile.TemporaryDirectory() as folder:
            cases = Path(folder) / "cases.jsonl"
            cases.write_text(json.dumps({"id": "x", "category": "memory", "question": "?", "expected_status": "answered",
                                         "expected_refs": ["M-missing"], "acceptable_refs": [], "answer_any": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load(cases_path=cases)

    def test_dataset_covers_paraphrase_and_unanswerable_traps(self):
        categories = {case["category"] for case in CASES}
        self.assertTrue({"memory", "task", "event", "paraphrase", "unanswerable"} <= categories)
        self.assertGreaterEqual(sum(case["expected_status"] == "no_reference" for case in CASES), 5)


if __name__ == "__main__":
    unittest.main()
