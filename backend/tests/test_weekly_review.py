"""Weekly review: SQL numbers only, grounded narrative, template fallback. Providers/DB simulated."""
import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from focusos_api.weekly_review import ReviewText, allowed_numbers, generate_review, grounded, narrate, template, week_start

STATS = {"week_start": "2026-10-12", "week_end": "2026-10-18", "timezone": "Asia/Jakarta", "tasks_created": 7,
         "tasks_completed": 4, "tasks_overdue": 2, "overdue_titles": ["Revisi bab 2"], "blocks_scheduled": 5,
         "blocks_cancelled": 1, "focus_minutes": 210, "focus_by_project": [{"project": "Skripsi", "minutes": 120}],
         "check_ins": 3, "check_ins_done": 2, "check_ins_partial": 1, "check_ins_skipped": 0,
         "planned_minutes_checked": 150, "actual_minutes_checked": 195, "model_calls": 40, "model_tokens": 51234}


def reply(value):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]}


class GroundingTests(unittest.TestCase):
    def test_numbers_must_come_from_the_stats(self):
        self.assertTrue(grounded(ReviewText(narrative="You booked 5 blocks, 3.5 hours in total, and finished 4 of 7 tasks.",
                                            suggestions=["Start the 2 overdue tasks on Monday."]), STATS))
        self.assertFalse(grounded(ReviewText(narrative="You focused 13 hours.", suggestions=[]), STATS))
        self.assertFalse(grounded(ReviewText(narrative="Fine week.", suggestions=["Do 9 tasks."]), STATS))

    def test_allowed_numbers_include_hours_and_week_dates(self):
        allowed = allowed_numbers(STATS)
        for value in ("210", "3", "3.5", "3,5", "2", "12", "18", "2026", "51234"):
            self.assertIn(value, allowed)
        self.assertNotIn("true", allowed)

    def test_template_only_uses_stats(self):
        text = template(STATS)
        self.assertTrue(grounded(text, STATS))
        self.assertLessEqual(len(text.suggestions), 3)

    def test_monday_of_the_week(self):
        self.assertEqual(week_start(date(2026, 10, 16), 0), date(2026, 10, 12))
        self.assertEqual(week_start(date(2026, 10, 12), -1), date(2026, 10, 5))


class NarrateTests(unittest.TestCase):
    def call(self, *responses):
        with patch("focusos_api.weekly_review.api_key", return_value="synthetic"), \
             patch("focusos_api.weekly_review.gemini_request", side_effect=list(responses)) as request:
            return narrate(STATS), request

    def test_invented_numbers_are_retried_once_then_refused(self):
        bad = reply({"narrative": "You focused 41 hours.", "suggestions": []})
        text, request = self.call(bad, bad)
        self.assertIsNone(text)
        self.assertEqual(request.call_count, 2)
        good = reply({"narrative": "You booked 5 blocks.", "suggestions": ["Keep 2 mornings free."]})
        text, request = self.call(bad, good)
        self.assertEqual(text.narrative, "You booked 5 blocks.")
        self.assertEqual(request.call_args.kwargs["purpose"], "review")

    def test_generate_falls_back_to_the_template_and_saves(self):
        client = MagicMock()
        client.rpc.return_value.execute.return_value.data = STATS
        with patch("focusos_api.weekly_review.scoped_client") as scoped, \
             patch("focusos_api.weekly_review.read_profile", return_value=type("P", (), {"timezone": "Asia/Jakarta"})()), \
             patch("focusos_api.weekly_review.narrate", return_value=None):
            scoped.return_value.__enter__.return_value = ("owner", client)
            review = generate_review("session", -1, datetime(2026, 10, 16, 3, tzinfo=timezone.utc))
        self.assertEqual((review["week_start"], review["narrative_source"]), ("2026-10-05", "template"))
        saved = [call for call in client.rpc.call_args_list if call.args[0] == "focusos_save_weekly_review"][0].args[1]
        self.assertEqual((saved["p_source"], saved["p_week_start"]), ("template", "2026-10-05"))


if __name__ == "__main__":
    unittest.main()
