"""Adaptive estimates from check-ins. The database is simulated."""
import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from focusos_api import estimates
from focusos_api.database import DatabaseUnavailable
from focusos_api.estimates import Estimate, adjusted_minutes, estimate_factors, factor_for, shrunk
from focusos_api.product import CheckInInput, CheckInRejected, pending_check_ins, protected, record_check_in
from focusos_api.unified_commands import _estimate_adjustment

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def session(planned, actual, outcome="done", project=None):
    return {"planned_minutes": planned, "actual_minutes": actual, "outcome": outcome, "project_id": project}


class EstimatorTests(unittest.TestCase):
    def test_no_check_ins_means_no_correction(self):
        overall = estimate_factors([])["overall"]
        self.assertEqual((overall.factor, overall.sessions, overall.confident()), (1.0, 0, False))

    def test_prior_dominates_few_check_ins_and_data_dominates_many(self):
        few = estimate_factors([session(60, 120)])["overall"]
        many = estimate_factors([session(60, 120)] * 40)["overall"]
        self.assertLess(few.factor, 1.3)            # one session that took 2x barely moves it
        self.assertAlmostEqual(many.factor, 2 ** (40 / 43), places=3)
        self.assertTrue(many.confident())

    def test_log_space_treats_overruns_and_underruns_symmetrically(self):
        balanced = estimate_factors([session(60, 120), session(60, 30)] * 5)["overall"]
        self.assertAlmostEqual(balanced.factor, 1.0, places=6)
        self.assertFalse(balanced.confident())      # no correction worth applying
        self.assertLess(balanced.low, 1.0); self.assertGreater(balanced.high, 1.0)

    def test_skipped_and_malformed_rows_are_ignored(self):
        rows = [session(60, None, "skipped"), session(0, 30), session(60, "90"), session(60, 90)]
        self.assertEqual(estimate_factors(rows)["overall"].sessions, 1)

    def test_partial_sessions_count_with_their_total_need(self):
        self.assertEqual(estimate_factors([session(60, 90, "partial")])["overall"].sessions, 1)

    def test_projects_shrink_toward_the_overall_habit(self):
        rows = [session(60, 90)] * 10 + [session(60, 60, project="p1")]
        factors = estimate_factors(rows)
        project = factor_for(factors, "p1")
        self.assertEqual(project.scope, "project")
        # One on-time session in the project is pulled toward the user's overall 1.4x habit.
        self.assertGreater(project.factor, 1.15)
        self.assertEqual(factor_for(factors, "unknown").scope, "overall")
        self.assertEqual(factor_for(factors, None).scope, "overall")

    def test_factor_and_minutes_stay_in_safe_ranges(self):
        extreme = estimate_factors([session(15, 1440)] * 50)["overall"]
        self.assertEqual(extreme.factor, 3.0)
        self.assertEqual(adjusted_minutes(30, Estimate(1.37, 1.1, 1.7, 9, "overall")), 40)
        self.assertEqual(adjusted_minutes(400, extreme), 480)
        self.assertEqual(adjusted_minutes(20, Estimate(0.5, 0.5, 0.6, 9, "overall")), 15)

    def test_shrinkage_formula(self):
        result = shrunk([math.log(2)] * 3, 0.0, "overall")
        self.assertAlmostEqual(result.factor, math.exp(3 * math.log(2) / 6))


class ScheduleAdjustmentTests(unittest.TestCase):
    def factors(self, rows):
        return patch("focusos_api.unified_commands.estimates.load_factors", return_value=estimate_factors(rows))

    def test_confident_factor_books_the_corrected_duration(self):
        with self.factors([session(60, 90)] * 20):
            adjustment = _estimate_adjustment("session", {"title": "Write report", "project_id": None}, 30)
        self.assertEqual(adjustment["booked_minutes"], 45)
        self.assertEqual((adjustment["estimate_minutes"], adjustment["scope"]), (30, "overall"))

    def test_too_few_check_ins_or_tiny_effect_keeps_the_saved_estimate(self):
        with self.factors([session(60, 120)] * 2):
            self.assertIsNone(_estimate_adjustment("session", {"title": "x"}, 30))
        with self.factors([session(60, 63)] * 30):
            self.assertIsNone(_estimate_adjustment("session", {"title": "x"}, 30))

    def test_missing_table_or_outage_never_blocks_scheduling(self):
        with patch("focusos_api.unified_commands.estimates.load_factors", side_effect=DatabaseUnavailable("missing")):
            self.assertIsNone(_estimate_adjustment("session", {"title": "x"}, 30))


class FakeQuery:
    def __init__(self, data): self.data = data
    def __getattr__(self, _): return lambda *a, **k: self
    def execute(self): return self


class CheckInTests(unittest.TestCase):
    def client(self, blocks, sessions):
        client = MagicMock()
        client.table.side_effect = lambda name: FakeQuery(blocks if name == "approval_requests" else sessions)
        scoped = MagicMock(); scoped.__enter__.return_value = ("owner", client)
        return patch("focusos_api.product.scoped_client", return_value=scoped)

    def block(self, start, minutes=60, **changes):
        return {"id": str(uuid4()), "task_id": None, "status": "succeeded", "cancellation_status": None,
                "payload": {"title": "Deep work", "start": start.isoformat(), "end": (start + timedelta(minutes=minutes)).isoformat(),
                            "timezone": "Asia/Jakarta"}, **changes}

    def test_offers_started_unchecked_blocks_from_the_last_week(self):
        done, ended, future, old, cancelled = (self.block(NOW - timedelta(hours=3)), self.block(NOW - timedelta(hours=5), 90),
            self.block(NOW + timedelta(hours=1)), self.block(NOW - timedelta(days=9)),
            self.block(NOW - timedelta(hours=2), cancellation_status="cancelled"))
        with self.client([done, ended, future, old, cancelled], [{"approval_id": done["id"]}]):
            pending = pending_check_ins("session", NOW)
        self.assertEqual([item["id"] for item in pending], [ended["id"]])
        self.assertEqual(pending[0]["planned_minutes"], 90)

    def test_minutes_must_match_the_outcome(self):
        CheckInInput(outcome="skipped")
        CheckInInput(outcome="done", actual_minutes=45)
        for value in ({"outcome": "skipped", "actual_minutes": 10}, {"outcome": "done"},
                      {"outcome": "done", "actual_minutes": 0}, {"outcome": "maybe", "actual_minutes": 5}):
            with self.subTest(value), self.assertRaises(ValidationError):
                CheckInInput.model_validate(value)

    def test_refused_check_in_is_a_conflict_not_an_outage(self):
        refused = DatabaseUnavailable("Restricted database operation failed")
        refused.__cause__ = type("APIError", (Exception,), {"code": "P0002"})()
        with patch("focusos_api.product.scoped_client", side_effect=refused):
            with self.assertRaises(CheckInRejected):
                record_check_in("session", uuid4(), CheckInInput(outcome="done", actual_minutes=30))
        with self.assertRaises(HTTPException) as raised:
            protected(lambda: (_ for _ in ()).throw(CheckInRejected()))
        self.assertEqual(raised.exception.status_code, 409)
        outage = DatabaseUnavailable("down")
        with patch("focusos_api.product.scoped_client", side_effect=outage):
            with self.assertRaises(DatabaseUnavailable):
                record_check_in("session", uuid4(), CheckInInput(outcome="skipped"))


if __name__ == "__main__":
    unittest.main()
