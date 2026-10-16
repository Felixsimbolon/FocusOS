"""Replying to a request that asked the user a question. Providers/DB are simulated."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from focusos_api.agent_continuation import CommandRunNotFound
from focusos_api.follow_ups import FollowUpError, already_done, follow_up, open_questions
from focusos_api.jobs import RetryStep
from focusos_api.unified_commands import ScheduleIntent, WorkInput, constraint_text, infer_work, start_work
from test_combined_requests import plan
from test_planning_compiler import NOW, PROFILE
from test_unified_commands import TEXT, UnifiedHarness, intent, sel

EARLIER = "Buat task review desain, deadline Jumat. " + TEXT
QUESTION = "Which saved task do you mean: Buat halaman web or Review desain?"
CLARIFIED = {"tasks_saved": 1, "schedules": [{"title": "Saved task", "status": "clarify", "message": QUESTION}]}


def parent(command=EARLIER, entrypoint="unified"):
    return SimpleNamespace(command=command, checkpoint={"entrypoint": entrypoint})


class OpenQuestionTests(unittest.TestCase):
    def test_reads_whole_request_and_per_schedule_questions(self):
        self.assertEqual(open_questions("failed", "request_ambiguous", {"message": "What should I schedule?"}),
                         ["What should I schedule?"])
        self.assertEqual(open_questions("succeeded", None, CLARIFIED), [f"Saved task: {QUESTION}"])
        # A failure that is not a question has nothing to reply to.
        self.assertEqual(open_questions("failed", "calendar_reconnect_required", {"message": "Reconnect Google."}), [])

    def test_lists_completed_parts_so_they_are_not_redone(self):
        done = already_done({"tasks_saved": 2, "schedules": [{"title": "belajar Python", "status": "scheduled"}],
                             "answers": [{"question": "Kapan deadline?", "status": "answered"}]})
        self.assertEqual(done, ["saved 2 task(s)", "scheduled belajar Python", "answered: Kapan deadline?"])


class FollowUpContextTests(unittest.TestCase):
    def context(self, run=None, job=None, reply="yang review desain", error=None):
        loader = patch("focusos_api.follow_ups.load_command_run", side_effect=error) if error else \
            patch("focusos_api.follow_ups.load_command_run", return_value=run or parent())
        with loader, patch("focusos_api.follow_ups._parent_job",
                           return_value=job if job is not None else {"status": "succeeded", "result": CLARIFIED, "safe_error": None}):
            return follow_up("session", uuid4(), reply)

    def test_reply_carries_the_earlier_request_and_its_open_question(self):
        command, conversation = self.context()
        self.assertEqual(command, EARLIER + "\nyang review desain")
        self.assertEqual(conversation["open_questions"], [f"Saved task: {QUESTION}"])
        self.assertEqual(conversation["already_done"], ["saved 1 task(s)"])
        self.assertEqual(conversation["previous_request"], EARLIER)

    def test_rejects_replies_that_cannot_continue(self):
        cases = {"not found": {"error": CommandRunNotFound("missing")},
                 "other entrypoint": {"run": parent(entrypoint="agent")},
                 "still running": {"job": {"status": "running", "result": {}}},
                 "no question": {"job": {"status": "succeeded", "result": {"tasks_saved": 1}}},
                 "too long": {"reply": "x" * (1001 - len(EARLIER))}}
        for name, kwargs in cases.items():
            with self.subTest(name), self.assertRaises(FollowUpError):
                self.context(**kwargs)


class ReplyIntentTests(unittest.TestCase):
    conversation = {"previous_request": EARLIER, "open_questions": [QUESTION], "already_done": ["saved 1 task(s)"]}

    def infer(self, value, text="yang review desain"):
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]}
        with patch("focusos_api.unified_commands.api_key", return_value="synthetic"), \
             patch("focusos_api.unified_commands.request", return_value=response) as call:
            result = infer_work(text, [{"title": "Review desain", "due_kind": "none"}], NOW.isoformat(), PROFILE.timezone, self.conversation)
        return result, json.loads(call.call_args.args[0]["contents"][0]["parts"][0]["text"])

    def test_quotes_may_come_from_the_earlier_request(self):
        existing = ScheduleIntent(target="existing", title_quote=None, request_quote=TEXT, selection=sel(task_refs=["task-1"]))
        result, context = self.infer(plan(schedules=[existing]).model_dump())
        self.assertEqual(result.schedules[0].selection.task_refs, ["task-1"])
        self.assertEqual(context["text"], "yang review desain")
        self.assertEqual(context["conversation"]["open_questions"], [QUESTION])
        self.assertNotIn("reply_to", context["conversation"])

    def test_quotes_outside_both_texts_are_rejected(self):
        invented = ScheduleIntent(target="existing", title_quote=None, request_quote="Cari waktu lusa jam 8",
                                  selection=sel(task_refs=["task-1"]))
        with self.assertRaises(RetryStep):
            self.infer(plan(schedules=[invented]).model_dump())

    def test_finished_parts_of_the_earlier_request_do_not_bind_the_reply(self):
        schedule = ScheduleIntent(target="existing", title_quote=None, request_quote=TEXT, selection=sel(task_refs=["task-1"]))
        combined = EARLIER + "\nyang review desain"
        self.assertEqual(constraint_text(plan(schedules=[schedule]), schedule, combined, follow_up=True), TEXT)


class ReplyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.h = UnifiedHarness().enter(); self.addCleanup(self.h.close)

    def reply(self, reply_text):
        job = self.h.start(EARLIER + "\n" + reply_text)
        conversation = {"previous_request": EARLIER, "open_questions": [QUESTION], "already_done": [], "reply_to": str(uuid4())}
        self.h.save_run("session", self.h.run.id, self.h.run.version, "waiting", "start",
                        {**self.h.run.checkpoint, "reply_text": reply_text, "conversation": conversation}, None, 0, 0)
        return job, conversation

    def test_reply_schedules_the_chosen_task_with_the_earlier_constraints(self):
        self.h.extract_and_capture()  # The earlier request saved the task the reply names.
        job, conversation = self.reply("yang review desain")
        self.h.work_intent = intent(task_refs=["task-1"])
        infer = MagicMock(return_value=self.h.work_intent)
        with patch("focusos_api.unified_commands.infer_work", infer):
            step, _ = self.h.drain(job)
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(infer.call_args.args[0], "yang review desain")
        self.assertEqual(infer.call_args.args[4], conversation)
        self.assertEqual(self.h.run.checkpoint["constraint_text"], TEXT)
        self.assertEqual(self.h.insert_count, 1)

    def test_reply_captures_only_what_the_reply_adds(self):
        job, _ = self.reply("Tambah task kirim laporan, estimasi 20 menit.")
        self.h.work_intent = plan(capture=True)
        captured = SimpleNamespace(extraction=SimpleNamespace(status="ready"),
                                   capture={"tasks_saved": 1, "memories_saved": 0, "memory_ids": []})
        with patch("focusos_api.unified_commands.create_manual_source",
                   return_value=SimpleNamespace(source=SimpleNamespace(id=self.h.source_id))) as create, \
             patch("focusos_api.unified_commands.process_and_capture", return_value=captured):
            step, _ = self.h.drain(job)
        self.assertEqual(step.status, "succeeded")
        self.assertEqual(create.call_args.args[2].text, "Tambah task kirim laporan, estimasi 20 menit.")


class StartReplyTests(unittest.TestCase):
    def test_reply_run_stores_the_combined_command_and_reply_text(self):
        rpc = MagicMock(return_value={"id": str(uuid4()), "status": "pending", "version": 1})
        checkpoint = MagicMock(return_value=True)
        conversation = {"previous_request": EARLIER, "open_questions": [QUESTION], "already_done": [], "reply_to": "x"}
        with patch("focusos_api.unified_commands.follow_up", return_value=(EARLIER + "\nyang web", conversation)), \
             patch("focusos_api.unified_commands._rpc", rpc), patch("focusos_api.unified_commands._checkpoint", checkpoint), \
             patch("focusos_api.unified_commands.load_command_run", return_value=SimpleNamespace(checkpoint={"entrypoint": "unified"})), \
             patch("focusos_api.unified_commands.enqueue_job", return_value=SimpleNamespace(model_dump=lambda **_: {})):
            start_work("session", WorkInput(request_key=uuid4(), text="yang web", reply_to=uuid4()))
        self.assertEqual(rpc.call_args.args[2]["p_command"], EARLIER + "\nyang web")
        saved = checkpoint.call_args.args[5]
        self.assertEqual((saved["reply_text"], saved["conversation"]), ("yang web", conversation))

    def test_reply_that_cannot_continue_is_rejected_before_anything_is_saved(self):
        with patch("focusos_api.unified_commands.follow_up", side_effect=FollowUpError("No open question.")), \
             patch("focusos_api.unified_commands._rpc") as rpc:
            with self.assertRaises(HTTPException) as raised:
                start_work("session", WorkInput(request_key=uuid4(), text="yang web", reply_to=uuid4()))
        self.assertEqual((raised.exception.status_code, raised.exception.detail), (422, "No open question."))
        rpc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
