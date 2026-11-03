"""Deadline forecast: the simulation, its suggestions, and the endpoint. No Calendar or database is reached."""
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from focusos_api import estimates, forecast, memory_answers, product
from focusos_api.forecast import Slot, Work
from focusos_api.google_calendar import CalendarReconnectRequired
from focusos_api.main import app
from focusos_api.profiles import WorkingHours

JAKARTA = ZoneInfo("Asia/Jakarta")
NOW = datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc)  # Tuesday 08:00 in Jakarta
EXACT = estimates.Estimate(1.0, 1.0, 1.0, 0, "overall")   # no duration uncertainty
CERTAIN = (1e6, 1.0)                                       # every booked block happens


def work(name: str, minutes: float, due_hours: float, priority: str = "normal", estimated: bool = True) -> Work:
    return Work(name, name.title(), priority, None, NOW + timedelta(hours=due_hours), minutes, estimated, EXACT)


def free(start_hours: float, end_hours: float, day: int = 0, task: str | None = None) -> Slot:
    return Slot(NOW + timedelta(hours=start_hours), NOW + timedelta(hours=end_hours), day, task)


def chance(works, slots, name, runs=50):
    finishes, _ = forecast.simulate(works, slots, CERTAIN, NOW, runs=runs, seed="test")
    return forecast._probability(finishes[name], next(item for item in works if item.id == name).deadline)


class SimulationTests(unittest.TestCase):
    def setUp(self):
        # Free time fully used, so outcomes depend only on what each test sets up.
        self.share = patch.object(forecast, "FREE_TIME_USE", (1e6, 1.0)); self.share.start()

    def tearDown(self):
        self.share.stop()

    def test_work_that_fits_before_the_deadline_is_on_time_and_work_with_no_time_is_not(self):
        self.assertEqual(chance([work("a", 120, 10)], [free(1, 4)], "a"), 1.0)
        self.assertEqual(chance([work("a", 120, 10)], [], "a"), 0.0)
        finishes, _ = forecast.simulate([work("a", 120, 10)], [free(1, 4)], CERTAIN, NOW, runs=5, seed="test")
        self.assertTrue(all(value is not None and abs((value - (NOW + timedelta(hours=3))).total_seconds()) < 60 for value in finishes["a"]))

    def test_free_time_goes_to_the_nearest_deadline_first(self):
        works = [work("later", 120, 30), work("sooner", 120, 5)]
        slots = [free(1, 3)]  # room for only one of them
        self.assertEqual(chance(works, slots, "sooner"), 1.0)
        self.assertEqual(chance(works, slots, "later"), 0.0)

    def test_a_booked_block_works_on_its_own_task_even_when_another_is_due_sooner(self):
        works = [work("booked", 60, 30), work("sooner", 60, 5)]
        slots = [free(1, 2, task="booked")]
        self.assertEqual(chance(works, slots, "booked"), 1.0)
        self.assertEqual(chance(works, slots, "sooner"), 0.0)
        # Leftover booked time is not wasted: it goes on to the nearest deadline.
        self.assertEqual(chance([work("booked", 30, 30), work("sooner", 30, 5)], slots, "sooner"), 1.0)

    def test_a_skipped_block_gives_no_time(self):
        finishes, _ = forecast.simulate([work("a", 60, 10)], [free(1, 2, task="a")], (1.0, 1e6), NOW, runs=50, seed="test")
        self.assertEqual(forecast._probability(finishes["a"], NOW + timedelta(hours=10)), 0.0)

    def test_finished_work_is_on_time_at_once(self):
        self.assertEqual(chance([work("done", 0, 2)], [], "done"), 1.0)

    def test_the_same_seed_gives_the_same_forecast(self):
        self.share.stop()
        spread = estimates.Estimate(1.2, 0.8, 1.8, 10, "overall")
        works = [Work("a", "A", "normal", None, NOW + timedelta(hours=20), 240, True, spread)]
        slots = [free(1, 5, 0), free(25, 29, 1)]
        first = forecast.simulate(works, slots, (8.0, 2.0), NOW, runs=100, seed="owner:2026-11-03")
        second = forecast.simulate(works, slots, (8.0, 2.0), NOW, runs=100, seed="owner:2026-11-03")
        self.assertEqual(first, second)
        self.share.start()

    def test_duration_factors_stay_inside_the_learned_range_limits(self):
        import random
        wide = estimates.Estimate(1.0, 0.1, 10.0, 10, "overall")
        values = [forecast._duration_factor(random.Random(index), wide) for index in range(200)]
        self.assertTrue(all(estimates.FACTOR_RANGE[0] <= value <= estimates.FACTOR_RANGE[1] for value in values))


class InputTests(unittest.TestCase):
    def test_a_date_deadline_means_the_end_of_that_local_day(self):
        task = SimpleNamespace(due_kind="date", due_date=date(2026, 11, 6), due_at=None)
        self.assertEqual(forecast.deadline_of(task, JAKARTA), datetime(2026, 11, 6, 17, 0, tzinfo=timezone.utc))
        timed = SimpleNamespace(due_kind="datetime", due_date=None, due_at=datetime(2026, 11, 6, 23, 59, tzinfo=JAKARTA))
        self.assertEqual(forecast.deadline_of(timed, JAKARTA), datetime(2026, 11, 6, 16, 59, tzinfo=timezone.utc))
        self.assertIsNone(forecast.deadline_of(SimpleNamespace(due_kind="none", due_date=None, due_at=None), JAKARTA))

    def test_checked_in_work_counts_as_progress_and_skips_do_not(self):
        rows = [{"task_id": "t", "planned_minutes": 60, "actual_minutes": 75, "outcome": "done"},
                {"task_id": "t", "planned_minutes": 60, "actual_minutes": 90, "outcome": "partial"},  # got through 2/3
                {"task_id": "t", "planned_minutes": 60, "actual_minutes": None, "outcome": "skipped"},
                {"task_id": None, "planned_minutes": 60, "actual_minutes": 60, "outcome": "done"}]
        self.assertEqual(forecast.covered_minutes(rows), {"t": 100.0})
        self.assertEqual(forecast.show_up(rows), (forecast.SHOW_UP_PRIOR[0] + 3, forecast.SHOW_UP_PRIOR[1] + 1))

    def test_free_time_excludes_busy_time_and_every_booked_block(self):
        hours = WorkingHours(days=[1, 2, 3, 4, 5], start_minute=9 * 60, end_minute=12 * 60)  # 02:00-05:00 UTC
        busy = [(NOW + timedelta(hours=1, minutes=30), NOW + timedelta(hours=2))]
        block = (NOW + timedelta(hours=3), NOW + timedelta(hours=4), "t")
        other = (NOW + timedelta(hours=2, minutes=30), NOW + timedelta(hours=3), "elsewhere")
        slots = forecast.build_slots(NOW, NOW + timedelta(hours=6), JAKARTA, hours, busy, [block, other], {"t"})
        self.assertEqual([(slot.start.hour, slot.start.minute, slot.end.hour, slot.end.minute, slot.task) for slot in slots],
                         [(2, 0, 2, 30, None), (3, 0, 3, 30, None), (4, 0, 5, 0, "t")])


class SuggestionTests(unittest.TestCase):
    def test_a_short_task_gets_a_booking_request_the_composer_can_send(self):
        item = work("report", 240, 72)
        found = forecast.suggestions(item, 0.3, need_p80=300, booked=60, free=900, keep_rate=0.8, zone=JAKARTA)
        self.assertEqual(found[0]["kind"], "book")
        self.assertEqual(found[0]["minutes"], 255)  # 300 - 60 * 0.8 = 252, rounded up to 5
        self.assertTrue(found[0]["request"].startswith('Book 3 sessions of 85 minutes for "Report" before '))

    def test_no_free_time_left_means_renegotiate_and_safe_work_gets_nothing(self):
        item = work("report", 240, 72)
        self.assertEqual(forecast.suggestions(item, 0.1, 300, 0, 100, 0.8, JAKARTA)[0]["kind"], "renegotiate")
        self.assertEqual(forecast.suggestions(item, 0.95, 300, 0, 100, 0.8, JAKARTA), [])
        unestimated = work("guess", 60, 72, estimated=False)
        self.assertEqual([item["kind"] for item in forecast.suggestions(unestimated, 0.95, 60, 0, 600, 0.8, JAKARTA)], ["estimate"])

    def test_deferring_a_competing_task_is_suggested_when_it_frees_enough_time(self):
        with patch.object(forecast, "FREE_TIME_USE", (1e6, 1.0)):
            works = [work("thesis", 120, 10, "high"), work("errand", 120, 5, "low")]
            slots = [free(1, 3)]
            base = chance(works, slots, "thesis")
            found = forecast.what_ifs(works[0], works, slots, CERTAIN, NOW, "test", base)
        self.assertEqual(base, 0.0)
        self.assertEqual([(item["kind"], item["task_id"], item["probability"]) for item in found], [("defer", "errand", 1.0)])
        # A task due later never competes, and a higher-priority one is never offered for deferral.
        self.assertEqual(forecast.what_ifs(works[1], works, slots, CERTAIN, NOW, "test", 1.0), [])


def _task(title, due, minutes=120, priority="normal"):
    return SimpleNamespace(id=uuid4(), title=title, priority=priority, project_id=None, estimate_minutes=minutes,
                           due_kind="datetime", due_date=None, due_at=due)


class ForecastTests(unittest.TestCase):
    def run_forecast(self, tasks, calendar_error=None):
        query = MagicMock()
        for name in ("select", "eq", "order", "limit"): getattr(query, name).return_value = query
        query.execute.return_value.data = []
        client = MagicMock(); client.table.return_value = query

        @contextmanager
        def scoped(_):
            yield "owner", client
        profile = SimpleNamespace(timezone="Asia/Jakarta", working_hours=WorkingHours(days=[1, 2, 3, 4, 5, 6, 7], start_minute=8 * 60, end_minute=20 * 60))
        window = SimpleNamespace(complete=True)
        with patch.object(forecast, "read_profile", return_value=profile), \
                patch.object(forecast, "list_tasks", return_value=SimpleNamespace(tasks=tasks)), \
                patch.object(forecast, "scoped_client", scoped), \
                patch.object(forecast, "fetch_calendar_window", side_effect=calendar_error, return_value=window) as fetch, \
                patch.object(forecast, "normalize_window", return_value=()):
            return forecast.forecast("session", NOW), fetch

    def test_without_calendar_access_the_forecast_still_runs_and_says_so(self):
        result, _ = self.run_forecast([_task("Slides", NOW + timedelta(days=2)), _task("Old", NOW - timedelta(days=1)),
                                       SimpleNamespace(id=uuid4(), title="Someday", priority="low", project_id=None, estimate_minutes=None,
                                                       due_kind="none", due_date=None, due_at=None)],
                                      calendar_error=CalendarReconnectRequired("reconnect"))
        self.assertEqual(result["calendar"], "unavailable")
        self.assertEqual([item["title"] for item in result["tasks"]], ["Slides"])
        self.assertEqual([item["title"] for item in result["overdue"]], ["Old"])
        self.assertEqual(result["undated"], 1)
        entry = result["tasks"][0]
        self.assertEqual(entry["status"], forecast.band(entry["probability"]))
        self.assertGreater(entry["free_minutes"], 0)

    def test_nothing_due_in_two_weeks_needs_no_calendar_read(self):
        result, fetch = self.run_forecast([_task("Thesis", NOW + timedelta(days=40))])
        fetch.assert_not_called()
        self.assertEqual((result["tasks"], result["later"], result["calendar"]), ([], 1, "not_needed"))

    def test_without_working_hours_there_is_no_forecast(self):
        with patch.object(forecast, "read_profile", return_value=None), self.assertRaises(forecast.ForecastUnavailable):
            forecast.forecast("session", NOW)

    def test_the_endpoint_needs_a_session_and_explains_a_missing_profile(self):
        client = TestClient(app)
        self.assertEqual(client.get("/product/forecast").status_code, 401)
        with patch.object(product.forecast, "forecast", side_effect=forecast.ForecastUnavailable("profile_required")):
            app.dependency_overrides[product.access] = lambda: "token"
            try:
                response = client.get("/product/forecast", headers={"Authorization": "Bearer token"})
            finally:
                app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 409)


class AnswerTests(unittest.TestCase):
    def test_deadline_questions_get_forecast_references(self):
        for question in ("aman ga deadline minggu ini?", "keburu ga bikin slide sebelum jumat", "will I make it on time?"):
            self.assertTrue(memory_answers.FORECAST_QUESTION.search(question), question)
        for question in ("apa isi catatan rapat kemarin?", "siapa dosen pembimbingku?"):
            self.assertFalse(memory_answers.FORECAST_QUESTION.search(question), question)

    def test_a_forecast_reference_is_shown_as_chance_and_deadline(self):
        lines = forecast.summary_lines({"timezone": "Asia/Jakarta", "overdue": [], "tasks": [{
            "title": "Slides", "status": "tight", "probability": 0.62, "deadline": "2026-11-06T16:59:00+00:00",
            "finish": {"p50": None, "p80": "2026-11-06T10:00:00+00:00"},
            "suggestions": [{"kind": "book", "text": "Book about 90 more minutes before the deadline."}]}]})
        self.assertEqual(lines[0]["chance_on_time"], "62%")
        self.assertEqual(lines[0]["deadline"], "Fri 06 Nov 23:59")
        self.assertEqual(memory_answers._public_reference(lines[0]),
                         {"kind": "forecast", "title": "Slides", "detail": "62% on time · due Fri 06 Nov 23:59"})


if __name__ == "__main__":
    unittest.main()
