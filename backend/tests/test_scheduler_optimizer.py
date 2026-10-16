"""Joint placement of several tasks: constraints, objective and limits."""
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from focusos_api.scheduler_optimizer import (BUFFER_MINUTES, Job, candidates, greedy, optimize, placement_cost, reason)

T0 = datetime(2026, 10, 19, 2, 0, tzinfo=timezone.utc)  # Monday 09:00 in Asia/Jakarta


def hours(start, end):
    return (T0 + timedelta(hours=start), T0 + timedelta(hours=end))


def valid(solution, jobs, free):
    by_ref = {job.ref: job for job in jobs}
    placements = sorted(solution.placements, key=lambda item: item.start)
    for item in placements:
        job = by_ref[item.ref]
        assert item.end - item.start == timedelta(minutes=job.minutes)
        assert any(low <= item.start and item.end <= high for low, high in free)
        assert job.deadline is None or item.end <= job.deadline
    for a, b in zip(placements, placements[1:]):
        assert b.start >= a.end + timedelta(minutes=BUFFER_MINUTES)
    return True


class OptimizerTests(unittest.TestCase):
    def test_every_placement_respects_free_time_deadlines_and_buffers(self):
        free = [hours(0, 3), hours(5, 8)]
        jobs = [Job("a", 60, None, "low"), Job("b", 90, T0 + timedelta(hours=3), "normal"), Job("c", 45, None, "high")]
        solution = optimize(jobs, free, T0)
        self.assertIsNotNone(solution)
        self.assertTrue(valid(solution, jobs, free))
        self.assertTrue(solution.optimal)

    def test_beats_earliest_deadline_first_when_priorities_disagree(self):
        # Greedy books the deadline task first at 09:00, pushing the high-priority task later.
        free = [hours(0, 8)]
        jobs = [Job("deadline", 60, T0 + timedelta(hours=8), "low"), Job("urgent", 60, None, "high")]
        best, baseline = optimize(jobs, free, T0), greedy(jobs, free, T0)
        self.assertEqual(baseline.placements[0].ref, "deadline")
        self.assertLess(best.cost, baseline.cost)
        self.assertEqual(best.placements[0].ref, "urgent")
        self.assertTrue(valid(best, jobs, free))

    def test_packs_tasks_into_the_only_feasible_layout(self):
        # Two 60-minute tasks; one must use the short early gap or nothing fits.
        free = [hours(0, 1), hours(1.5, 2.5)]
        jobs = [Job("x", 60, T0 + timedelta(hours=1), "normal"), Job("y", 60, None, "normal")]
        solution = optimize(jobs, free, T0)
        self.assertTrue(valid(solution, jobs, free))
        self.assertEqual({item.ref: item.start for item in solution.placements}["x"], T0)

    def test_infeasible_requests_return_none(self):
        self.assertIsNone(optimize([Job("a", 120, None)], [hours(0, 1)], T0))
        self.assertIsNone(optimize([Job("a", 60, None), Job("b", 60, None)], [hours(0, 1.5)], T0))
        self.assertIsNone(optimize([Job("a", 60, T0 + timedelta(minutes=30))], [hours(0, 3)], T0))

    def test_limits_stop_the_search_and_report_it(self):
        free = [hours(0, 40)]
        jobs = [Job(str(index), 30, None) for index in range(6)]
        solution = optimize(jobs, free, T0, node_limit=5)
        self.assertTrue(solution is None or not solution.optimal)

    def test_candidates_use_the_grid_and_the_interval_start(self):
        low = T0 + timedelta(minutes=7)
        starts = [item.start for item in candidates(Job("a", 30, None), [(low, low + timedelta(hours=1))], T0)]
        self.assertIn(low, starts)
        self.assertIn(T0 + timedelta(minutes=15), starts)
        self.assertTrue(all((start - T0).total_seconds() % 900 == 0 for start in starts if start != low))

    def test_cost_prefers_early_important_work_and_slack_before_deadlines(self):
        start = T0 + timedelta(hours=2)
        self.assertGreater(placement_cost(Job("h", 60, None, "high"), start, start + timedelta(hours=1), T0),
                           placement_cost(Job("l", 60, None, "low"), start, start + timedelta(hours=1), T0))
        tight = Job("t", 60, T0 + timedelta(hours=3, minutes=30), "normal")
        loose = Job("t", 60, T0 + timedelta(days=2), "normal")
        self.assertGreater(placement_cost(tight, start, start + timedelta(hours=1), T0),
                           placement_cost(loose, start, start + timedelta(hours=1), T0))

    def test_reason_is_short_and_marked_as_the_servers_own(self):
        job = Job("a", 60, T0 + timedelta(hours=2), "high")
        solution = optimize([job, Job("b", 30, None)], [hours(0, 4)], T0)
        text = reason(job, next(item for item in solution.placements if item.ref == "a"), ZoneInfo("Asia/Jakarta"))
        self.assertTrue(text.startswith("Optimized: high priority, due Mon"))
        self.assertLessEqual(len(text), 160)


if __name__ == "__main__":
    unittest.main()
