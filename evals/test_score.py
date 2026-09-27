import hashlib
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import make_report, score_case
from validate import load_cases


class ScoreTests(unittest.TestCase):
    def test_exact_match_and_evidence(self):
        row = load_cases()[0]
        task = row["expected"]["tasks"][0]
        record = {"status": "completed", "tasks": [{"title": task["title"],
            "deadline_kind": task["deadline_kind"], "deadline_value": task["deadline_value"],
            "evidence_sha256": [hashlib.sha256(task["evidence_quote"].encode()).hexdigest()]}]}
        score = score_case(row, record, {})
        self.assertEqual((score["matched"], score["deadline_correct"], score["evidence_correct"]), (1, 1, 1))

    def test_failure_and_semantic_variant_need_explicit_judgment(self):
        row = load_cases()[0]
        failed = score_case(row, {"status": "failed", "tasks": []}, {})
        self.assertEqual((failed["missed"], failed["matched"]), (1, 0))
        variant = {"status": "completed", "tasks": [{"title": "File the budget", "deadline_kind": "date",
                    "deadline_value": "2026-10-08", "evidence_sha256": []}]}
        unreviewed = score_case(row, variant, {})
        self.assertEqual(unreviewed["matched"], 0)
        self.assertEqual(len(unreviewed["needs_review"]), 1)
        reviewed = score_case(row, variant, {(row["id"], "File the budget", "Submit budget"): True})
        self.assertEqual(reviewed["matched"], 1)
        self.assertEqual(reviewed["evidence_correct"], 0)

    def test_skipped_cases_never_claim_accuracy(self):
        cases = load_cases()
        records = [{"case_id": row["id"], "status": "skipped", "model": "fixture",
                    "prompt_version": "1", "schema_version": "1"} for row in cases
                   if row["category"] in {"extraction", "ambiguity", "adversarial"}]
        report = make_report(cases, records, {})
        self.assertIn("not measured", report)
        self.assertNotIn("One-to-one task match", report)

if __name__ == "__main__":
    unittest.main()
