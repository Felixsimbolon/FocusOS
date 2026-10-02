import unittest
from unittest.mock import patch

from planning_eval import evaluate
from focusos_api.agent_planner import PlanningModelError


class PlanningEvaluationTests(unittest.TestCase):
    def test_mock_mode_is_labeled_and_never_calls_provider(self):
        with patch("planning_eval.select_planning_intent") as model:
            report = evaluate(False)
        model.assert_not_called()
        self.assertEqual(report["passed"], report["total"])
        self.assertFalse(report["provider_called"])
        self.assertFalse(report["calendar_written"])
        self.assertIsNone(report["model"])

    def test_provider_failures_are_counted_not_reported_as_skipped_passes(self):
        with patch("planning_eval.select_planning_intent", side_effect=PlanningModelError("planning_timeout")):
            report = evaluate(True)
        self.assertEqual(report["passed"], 0)
        self.assertTrue(all(row["safe_code"] == "planning_timeout" for row in report["observations"]))


if __name__ == "__main__":
    unittest.main()
