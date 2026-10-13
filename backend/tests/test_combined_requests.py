"""One request with several captures, questions and schedules. Providers/DB are simulated."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from focusos_api.jobs import Step, RetryStep, _step
from focusos_api.unified_commands import (ScheduleIntent, WorkIntent, _match_new_tasks, constraint_text,
                                          infer_work, legacy_intent)
from test_planning_compiler import NOW, PROFILE, TASK
from test_unified_commands import UnifiedHarness, intent, sel

QUESTION = "Kapan deadline halaman web?"
SCHEDULE = "Cari waktu besok antara jam 13 sampai 16 untuk belajar Python selama 45 menit."
SECOND = "Cari waktu besok antara jam 9 sampai 11 untuk review desain selama 60 menit."
COMBINED = f"Buat task siapkan slide demo, deadline Jumat, estimasi 30 menit. {QUESTION} {SCHEDULE}"
ANSWER = [{"question": QUESTION, "status": "answered", "answer": "18 Oktober 2026.",
           "references": [{"kind": "task", "title": "Buat halaman web", "detail": "open, due 2026-10-18"}]}]


def activity(title, quote, **changes):
    return ScheduleIntent(target="activity", title_quote=title, request_quote=quote, selection=sel(**changes))


def plan(capture=False, questions=(), schedules=(), clarification=None):
    return WorkIntent(capture=capture, questions=list(questions), schedules=list(schedules),
                      clarification=clarification, explanation="Several parts.")


def captured(tasks=1, memories=1):
    return SimpleNamespace(extraction=SimpleNamespace(status="ready"),
                           capture={"tasks_saved": tasks, "memories_saved": memories, "memory_ids": []})


class CombinedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.h = UnifiedHarness().enter(); self.addCleanup(self.h.close)
        self.source = patch("focusos_api.unified_commands.create_manual_source",
                            return_value=SimpleNamespace(source=SimpleNamespace(id=self.h.source_id)))
        self.create = self.source.start(); self.addCleanup(self.source.stop)

    def test_question_only_answers_without_saving_or_scheduling(self):
        self.h.work_intent = plan(questions=[QUESTION])
        with patch("focusos_api.unified_commands.answer_questions", return_value=ANSWER) as answer:
            step, job = self.h.drain(self.h.start(QUESTION))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(step.result["answers"], ANSWER)
        self.assertEqual(answer.call_args.args[1], [QUESTION])
        self.create.assert_not_called()
        self.assertEqual((self.h.insert_count, self.h.run.status, self.h.run.result["status"]), (0, "succeeded", "answered"))
        # A replay of the finished request does not ask the model again.
        with patch("focusos_api.unified_commands.answer_questions") as again:
            replay, _ = self.h.drain(job)
        again.assert_not_called()
        self.assertEqual(replay.result["answers"], ANSWER)

    def test_no_reference_answer_is_kept_as_a_result(self):
        missing = [{"question": "Berapa budget proyek?", "status": "no_reference", "answer": None, "references": []}]
        self.h.work_intent = plan(questions=["Berapa budget proyek?"])
        with patch("focusos_api.unified_commands.answer_questions", return_value=missing):
            step, _ = self.h.drain(self.h.start("Berapa budget proyek?"))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(step.result["answers"][0]["status"], "no_reference")

    def test_answer_provider_outage_retries_instead_of_claiming_no_reference(self):
        from focusos_api.memory_answers import AnswersUnavailable
        self.h.work_intent = plan(questions=[QUESTION])
        job = self.h.start(QUESTION)
        first = _step("session", job); job.update(checkpoint=first.checkpoint, result=first.result)
        with patch("focusos_api.unified_commands.answer_questions", side_effect=AnswersUnavailable("provider_unavailable")):
            with self.assertRaises(RetryStep) as raised: _step("session", job)
        self.assertEqual(raised.exception.code, "answer_unavailable")

    def test_capture_question_and_schedule_in_one_request(self):
        self.h.work_intent = plan(capture=True, questions=[QUESTION], schedules=[activity("belajar Python", SCHEDULE)])
        with patch("focusos_api.unified_commands.process_and_capture", return_value=captured()), \
             patch("focusos_api.unified_commands.answer_questions", return_value=ANSWER):
            step, _ = self.h.drain(self.h.start(COMBINED))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual((step.result["tasks_saved"], step.result["blocks_scheduled"]), (1, 1))
        self.assertEqual(step.result["answers"][0]["answer"], "18 Oktober 2026.")
        self.assertEqual(step.result["schedules"][0]["status"], "scheduled")
        self.assertEqual(self.h.approval.payload.title, "belajar Python")
        # The capture's "30 menit" estimate must not conflict with this schedule's 45 minutes.
        self.assertEqual(self.h.run.checkpoint["constraint_text"], SCHEDULE)
        self.assertEqual(self.h.run.result["scheduled_minutes"], 45)
        self.assertEqual(self.h.insert_count, 1)

    def test_failed_capture_still_answers_questions(self):
        self.h.work_intent = plan(capture=True, questions=[QUESTION])
        failed = SimpleNamespace(extraction=SimpleNamespace(status="failed", safe_error="batch_incomplete"))
        with patch("focusos_api.unified_commands.process_and_capture", return_value=failed), \
             patch("focusos_api.unified_commands.answer_questions", return_value=ANSWER):
            step, _ = self.h.drain(self.h.start(f"Buat task berikut:\n1. Satu.\n2. Dua.\n{QUESTION}"))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(step.result["answers"], ANSWER)
        self.assertIn("every task", step.result["notes"][0])

    def test_unsupported_part_becomes_a_note_without_blocking_the_rest(self):
        self.h.work_intent = plan(questions=[QUESTION], clarification="Recurring events are not supported yet.")
        with patch("focusos_api.unified_commands.answer_questions", return_value=ANSWER):
            step, _ = self.h.drain(self.h.start(QUESTION + " Jadwalkan tiap minggu."))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(step.result["notes"], ["Recurring events are not supported yet."])


class MultipleScheduleTests(unittest.TestCase):
    """Later schedules run on their own child runs; the first uses the request's run."""
    def setUp(self):
        self.h = UnifiedHarness().enter(); self.addCleanup(self.h.close)
        self.children, self.planned, self.outcomes = {}, [], []
        parent_save = self.h.save_run
        def save(token, run_id, version, status, stage, checkpoint, result, turns, calls, error=None):
            if str(run_id) in self.children:
                self.children[str(run_id)].update(checkpoint=checkpoint, status=status)
                return True
            return parent_save(token, run_id, version, status, stage, checkpoint, result, turns, calls, error)
        def start_child(token, name, args):
            assert name == "focusos_start_command_run"
            for child_id, child in self.children.items():
                if child["key"] == args["p_request_key"]:
                    return {"id": child_id, "status": child["status"], "version": 2}
            child_id = str(uuid4())
            self.children[child_id] = {"key": args["p_request_key"], "command": args["p_command"], "status": "pending"}
            return {"id": child_id, "status": "pending", "version": 1}
        def fake_plan(token, plan_id, checkpoint, previous):
            self.planned.append(str(plan_id))
            outcome = self.outcomes.pop(0) if self.outcomes else "ok"
            if outcome != "ok":
                return Step("failed", checkpoint, {**previous, "message": outcome}, "planning_not_scheduled")
            block = {"title": f"block {len(self.planned)}", "start": NOW.isoformat(), "end": NOW.isoformat(),
                     "timezone": PROFILE.timezone, "link": "https://calendar.google.com/calendar/event?eid=synthetic"}
            return Step("succeeded", checkpoint, {**previous, "run_id": str(plan_id), "blocks_scheduled": 1,
                                                  "blocks": [*(previous.get("blocks") or []), block]})
        for target, fake in {"focusos_api.unified_commands._checkpoint": save,
                             "focusos_api.unified_commands._rpc": start_child,
                             "focusos_api.jobs._plan_step": fake_plan}.items():
            started = patch(target, side_effect=fake); started.start(); self.addCleanup(started.stop)
        self.h.work_intent = plan(schedules=[activity("belajar Python", SCHEDULE),
            activity("review desain", SECOND, start_time="09:00", end_time="11:00", duration_minutes=60)])

    def test_two_schedules_each_get_their_own_plan(self):
        step, job = self.h.drain(self.h.start(f"{SCHEDULE} {SECOND}"))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(step.result["blocks_scheduled"], 2)
        self.assertEqual([item["status"] for item in step.result["schedules"]], ["scheduled", "scheduled"])
        self.assertEqual([item["blocks"] for item in step.result["schedules"]], [1, 1])
        self.assertEqual(self.planned[0], str(self.h.run.id))
        [(child_id, child)] = self.children.items()
        self.assertEqual(self.planned[1], child_id)
        # The child's command is only its own part, so its title and limits are grounded there.
        self.assertEqual(child["command"], SECOND)
        self.assertEqual(child["checkpoint"]["standalone_title"], "review desain")
        self.assertEqual(child["checkpoint"]["parent_run_id"], str(self.h.run.id))
        self.assertEqual(child["checkpoint"]["planning_selection"]["start_time"], "09:00")

    def test_one_failed_schedule_does_not_hide_the_other(self):
        self.outcomes = ["Not enough free time tomorrow between 13:00 and 16:00."]
        step, _ = self.h.drain(self.h.start(f"{SCHEDULE} {SECOND}"))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual([item["status"] for item in step.result["schedules"]], ["failed", "scheduled"])
        self.assertIn("Not enough", step.result["schedules"][0]["message"])
        self.assertEqual(step.result["blocks_scheduled"], 1)
        self.assertNotIn("message", step.result)

    def test_all_schedules_failing_fails_the_request_with_the_first_reason(self):
        self.outcomes = ["First window is full.", "Second window is full."]
        step, _ = self.h.drain(self.h.start(f"{SCHEDULE} {SECOND}"))
        self.assertEqual(step.status, "failed")
        self.assertEqual(step.result["message"], "First window is full.")
        self.assertEqual(step.error, "planning_not_scheduled")

    def test_ambiguous_schedule_is_reported_while_the_other_runs(self):
        unclear = ScheduleIntent(target="existing", title_quote=None, request_quote=SECOND,
            selection=sel(status="needs_clarification", questions=["Which saved task do you mean?"]))
        self.h.work_intent = plan(schedules=[unclear, activity("belajar Python", SCHEDULE)])
        step, _ = self.h.drain(self.h.start(f"{SCHEDULE} {SECOND}"))
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(step.result["schedules"][0]["status"], "clarify")
        self.assertEqual(step.result["schedules"][0]["message"], "Which saved task do you mean?")
        # The only plan that ran used the request's own run.
        self.assertEqual(self.planned, [str(self.h.run.id)])


class IntentContractTests(unittest.TestCase):
    def infer(self, value, text=COMBINED, tasks=()):
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]}
        with patch("focusos_api.unified_commands.api_key", return_value="synthetic"), \
             patch("focusos_api.unified_commands.request", return_value=response):
            return infer_work(text, list(tasks), NOW.isoformat(), PROFILE.timezone)

    def test_accepts_every_part_type_in_one_request(self):
        value = plan(capture=True, questions=[QUESTION], schedules=[activity("belajar Python", SCHEDULE)]).model_dump()
        result = self.infer(value)
        self.assertEqual((result.capture, result.questions, len(result.schedules)), (True, [QUESTION], 1))
        self.assertEqual(result.action, "both")

    def test_rejects_invalid_parts(self):
        new_without_capture = plan(schedules=[ScheduleIntent(target="new", title_quote=None, request_quote=SCHEDULE, selection=sel())])
        title_outside_quote = plan(schedules=[activity("siapkan slide", SCHEDULE)])
        nothing = plan()
        for value in (new_without_capture, title_outside_quote, nothing):
            with self.subTest(value=value.model_dump_json()[:60]):
                with self.assertRaises(RetryStep) as raised:
                    self.infer(value.model_dump())
                self.assertEqual(raised.exception.code, "intent_invalid")

    def test_combined_request_binds_constraints_to_each_quoted_part(self):
        schedule = activity("belajar Python", SCHEDULE)
        self.assertEqual(constraint_text(plan(schedules=[schedule]), schedule, COMBINED), COMBINED)
        self.assertEqual(constraint_text(plan(capture=True, schedules=[schedule]), schedule, COMBINED), SCHEDULE)

    def test_legacy_single_action_checkpoint_still_resumes(self):
        old = {"action": "both", "title_quote": None, "explanation": "Save and schedule.",
               "selection": sel(duration_minutes=30).model_dump()}
        converted = legacy_intent(old)
        self.assertTrue(converted.capture)
        self.assertEqual(converted.schedules[0].target, "new")
        self.assertEqual(constraint_text(converted, converted.schedules[0], COMBINED), COMBINED)

    def test_named_new_task_is_matched_to_the_captured_task(self):
        rows = [{"id": "a", "title": "Siapkan outline presentasi", "evidence": [{"quote": "1. Siapkan outline presentasi"}]},
                {"id": "b", "title": "Buat halaman web", "evidence": [{"quote": "2. Buat halaman web"}]}]
        self.assertEqual([row["id"] for row in _match_new_tasks(rows, "halaman web")], ["b"])
        self.assertEqual(len(_match_new_tasks(rows, None)), 2)
        self.assertEqual(_match_new_tasks(rows, "laporan keuangan"), [])


if __name__ == "__main__":
    unittest.main()
