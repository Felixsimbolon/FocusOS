"""Assignments (analyse, ask, plan), notes and project overview. Gemini and the database are simulated."""
import json
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from focusos_api import assignments, notes, project_view
from focusos_api.assignments import Analysis, PlanInput, analyse_text, grounded, planned_tasks, study_minutes
from focusos_api.database import DatabaseUnavailable
from focusos_api.unified_commands import WorkIntent

BRIEF = ("Tugas 2 Statistika. Kumpulkan laporan analisis regresi linear dan slide presentasi. "
         "Deadline: Jumat, 24 Oktober 2026 pukul 23.59. Gunakan dataset penjualan.")
TODAY = date(2026, 10, 18)


def analysis(**changes):
    value = {"title": "Tugas 2 Statistika", "summary": "Analisis regresi linear dengan laporan dan slide.", "project_name": "Statistika",
             "deliverables": [{"text": "Laporan analisis", "quote": "laporan analisis regresi linear"},
                              {"text": "Video", "quote": "rekaman video 5 menit"}],
             "due": {"raw_text": "Jumat, 24 Oktober 2026 pukul 23.59", "date": "2026-10-24", "time": "23:59"},
             "concepts": [{"name": "Regresi linear", "why": "Inti analisisnya.", "study_minutes": 100},
                          {"name": "Uji asumsi", "why": "Agar hasilnya sah.", "study_minutes": 60}],
             "subtasks": [{"title": "Bersihkan dataset", "estimate_minutes": 50}, {"title": "Tulis laporan", "estimate_minutes": 500}]}
    value.update(changes)
    return Analysis.model_validate(value)


def reply(value):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]}


class AnalysisTests(unittest.TestCase):
    def test_keeps_only_quoted_deliverables_and_tidies_estimates(self):
        result = grounded(analysis(), BRIEF)
        self.assertEqual([item.text for item in result.deliverables], ["Laporan analisis"])
        self.assertEqual(result.due.date, "2026-10-24")
        self.assertEqual([c.study_minutes for c in result.concepts], [105, 60])
        self.assertEqual([s.estimate_minutes for s in result.subtasks], [45, 240])

    def test_a_deadline_not_written_in_the_brief_is_dropped(self):
        result = grounded(analysis(due={"raw_text": "Senin depan", "date": "2026-10-20", "time": None}), BRIEF)
        self.assertEqual((result.due.raw_text, result.due.date), (None, None))

    def test_malformed_answers_get_one_retry_and_the_call_is_labeled(self):
        good = reply(analysis().model_dump())
        with patch.object(assignments, "api_key", return_value="k"), \
             patch.object(assignments, "gemini_request", side_effect=[reply({"title": "x"}), good]) as call:
            result = analyse_text(BRIEF, TODAY)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args.kwargs["purpose"], "assignment")
        self.assertEqual(json.loads(call.call_args.args[0]["contents"][0]["parts"][0]["text"])["today"], "2026-10-18")
        self.assertEqual(result.title, "Tugas 2 Statistika")


class PlanTests(unittest.TestCase):
    def test_study_sessions_only_for_what_is_not_understood_then_subtasks(self):
        data = grounded(analysis(), BRIEF).model_dump()
        tasks = planned_tasks(data, {"0": "partly", "1": "understood"}, "Statistika", TODAY)
        self.assertEqual([t["title"] for t in tasks], ["[Statistika] Belajar: Regresi linear", "[Statistika] Bersihkan dataset", "[Statistika] Tulis laporan"])
        self.assertEqual(tasks[0]["estimate"], 60)          # half of 105, rounded up to 15
        self.assertEqual(tasks[0]["due"], date(2026, 10, 23))  # study finishes the day before the deadline
        self.assertEqual(tasks[1]["due"], date(2026, 10, 24))
        self.assertEqual((tasks[0]["priority"], tasks[1]["priority"]), ("high", "normal"))
        self.assertIsNone(study_minutes({"study_minutes": 60}, "understood"))

    def row(self, **changes):
        return {"id": str(uuid4()), "title": "Tugas 2 Statistika", "status": "questions", "version": 4, "project_id": None, "plan_run_id": None,
                "analysis": grounded(analysis(), BRIEF).model_dump(), "understanding": {"0": "not", "1": "understood"}, **changes}

    def test_plan_creates_tagged_tasks_and_one_prepared_booking_request(self):
        row = self.row()
        created = []
        def create(token, key, task):
            created.append((key, task))
            return SimpleNamespace(task=SimpleNamespace(id=uuid4(), title=task.title, due_kind=task.due_kind, due_date=task.due_date, due_at=None,
                                                        estimate_minutes=task.estimate_minutes, source_id=None, priority=task.priority, project_id=task.project_id))
        project_id = uuid4()
        checkpoint = MagicMock(return_value=True)
        with patch.object(assignments, "_load", return_value=row), \
             patch.object(assignments, "create_project", return_value=SimpleNamespace(project=SimpleNamespace(id=project_id, name="Statistika"))), \
             patch.object(assignments, "create_task", side_effect=create), \
             patch.object(assignments, "_rpc", return_value={"id": str(uuid4()), "status": "pending", "version": 1}), \
             patch.object(assignments, "_checkpoint", checkpoint), \
             patch.object(assignments, "enqueue_job", return_value=SimpleNamespace(model_dump=lambda **_: {"id": "job"})), \
             patch.object(assignments, "_update", side_effect=lambda token, r, fields: {**r, **fields}) as update:
            result = assignments.plan("session", uuid4(), PlanInput(expected_version=4, request_key=uuid4()), datetime(2026, 10, 18, 2, tzinfo=timezone.utc))
        self.assertEqual(result["created"], 3)
        self.assertTrue(all(task.title.startswith("[Statistika] ") and task.project_id == project_id for _, task in created))
        intent = WorkIntent.model_validate(checkpoint.call_args.args[5]["work_plan"])
        self.assertEqual([s.selection.task_refs for s in intent.schedules], [["task-1"], ["task-2"], ["task-3"]])
        self.assertEqual(intent.schedules[0].selection.duration_minutes, 105)
        self.assertEqual(update.call_args.args[2]["status"], "planned")
        # Retrying creates nothing new: task keys come from the assignment id.
        self.assertEqual(len({key for key, _ in created}), 3)

    def test_plan_needs_every_question_answered_and_the_current_version(self):
        with patch.object(assignments, "_load", return_value=self.row(understanding={"0": "not"})), self.assertRaises(HTTPException) as missing:
            assignments.plan("session", uuid4(), PlanInput(expected_version=4, request_key=uuid4()))
        self.assertEqual(missing.exception.status_code, 422)
        with patch.object(assignments, "_load", return_value=self.row()), self.assertRaises(HTTPException) as stale:
            assignments.plan("session", uuid4(), PlanInput(expected_version=3, request_key=uuid4()))
        self.assertEqual(stale.exception.status_code, 409)

    def test_a_planned_assignment_is_not_planned_twice(self):
        row = self.row(status="planned", plan_run_id=str(uuid4()))
        with patch.object(assignments, "_load", return_value=row), patch.object(assignments, "create_task") as create:
            result = assignments.plan("session", uuid4(), PlanInput(expected_version=4, request_key=uuid4()))
        create.assert_not_called()
        self.assertEqual(result["run_id"], row["plan_run_id"])


class NoteTests(unittest.TestCase):
    def test_conflicting_save_explains_itself(self):
        error = DatabaseUnavailable("x"); error.__cause__ = type("E", (Exception,), {"code": "40001"})()
        with patch.object(notes, "scoped_client", side_effect=error), self.assertRaises(HTTPException) as raised:
            notes.save_note("session", uuid4(), notes.NoteInput(project_id=uuid4(), title="Kuliah 3", body="isi", expected_version=2))
        self.assertEqual(raised.exception.status_code, 409)

    def test_a_note_needs_a_project(self):
        with patch.object(notes, "scoped_client") as scoped, self.assertRaises(HTTPException) as raised:
            notes.save_note("session", uuid4(), notes.NoteInput(title="Catatan umum", body="isi", expected_version=0))
        self.assertEqual((raised.exception.status_code, raised.exception.detail), (422, "Choose a project for this note."))
        scoped.assert_not_called()

    def test_saved_note_is_indexed_for_questions(self):
        client = MagicMock(); client.rpc.return_value.execute.return_value.data = {"id": str(uuid4()), "title": "Kuliah 3", "body": "Regresi.", "version": 1}
        with patch.object(notes, "scoped_client") as scoped, patch.object(notes, "embed_note", return_value=True) as embed:
            scoped.return_value.__enter__.return_value = ("owner", client)
            saved = notes.save_note("session", uuid4(), notes.NoteInput(project_id=uuid4(), title="Kuliah 3", body="Regresi.", expected_version=0))
        self.assertTrue(saved["indexed"]); embed.assert_called_once()

    def test_note_search_sends_terms_and_vector(self):
        client = MagicMock(); client.rpc.return_value.execute.return_value.data = [{"id": "n", "title": "Kuliah 3", "excerpt": "Regresi."}]
        with patch.object(notes, "scoped_client") as scoped:
            scoped.return_value.__enter__.return_value = ("owner", client)
            rows = notes.note_matches("session", "Apa itu regresi linear?", [0.1] * 256)
        name, args = client.rpc.call_args.args
        self.assertEqual(name, "focusos_search_notes")
        self.assertIn("regresi", args["p_terms"])
        self.assertTrue(args["p_vector"].startswith("["))
        self.assertEqual(rows[0]["title"], "Kuliah 3")

    def test_notes_become_cited_references(self):
        from focusos_api import memory_answers
        def model(payload, **_):
            context = json.loads(payload["contents"][0]["parts"][0]["text"])
            assert any(item["ref"] == "N1" and item["kind"] == "note" for item in context["references"])
            return reply({"answers": [{"question_index": 0, "status": "answered", "answer": "Hubungan linear.", "refs": ["N1"]}]})
        with patch.object(memory_answers, "api_key", return_value="k"), patch.object(memory_answers, "refresh_stale_embeddings", return_value=0), \
             patch.object(memory_answers, "list_tasks", return_value=SimpleNamespace(tasks=[])), patch.object(memory_answers, "_scheduled_work", return_value=[]), \
             patch.object(memory_answers, "_memories", return_value=[]), patch.object(memory_answers, "_graph_memories", return_value=[]), \
             patch("focusos_api.notes.project_notes", return_value=[]), patch("focusos_api.notes.note_matches", return_value=[{"id": "n", "title": "Kuliah 3", "excerpt": "Regresi adalah hubungan linear."}]), \
             patch.object(memory_answers, "gemini_request", side_effect=model):
            [answer] = memory_answers.answer_questions("session", ["Apa itu regresi?"], "2026-10-18T09:00:00+07:00", "Asia/Jakarta")
        self.assertEqual(answer["references"], [{"kind": "note", "title": "Kuliah 3", "detail": "Regresi adalah hubungan linear."}])


    def test_a_project_is_named_only_by_its_whole_name(self):
        projects = [{"id": "a", "name": "Skripsi"}, {"id": "b", "name": "Web"}, {"id": "c", "name": "AI"}]
        self.assertEqual([p["id"] for p in notes.mentioned_projects(projects, "Gimana progress skripsi aku?")], ["a"])
        self.assertEqual(notes.mentioned_projects(projects, "website baru"), [])
        self.assertEqual(notes.mentioned_projects(projects, "tugas AI"), [], "names shorter than three letters are ignored")

    def test_project_notes_come_whole_with_the_project_name(self):
        pid = str(uuid4()); client = MagicMock()
        def table(name):
            query = MagicMock(); query.select.return_value = query; query.eq.return_value = query; query.in_.return_value = query
            query.order.return_value = query; query.limit.return_value = query
            query.execute.return_value.data = ([{"id": pid, "name": "Statistika"}] if name == "projects"
                                               else [{"id": "n", "title": "Kuliah 6", "body": "x" * 2000, "project_id": pid}])
            return query
        client.table.side_effect = table
        with patch.object(notes, "scoped_client") as scoped:
            scoped.return_value.__enter__.return_value = ("owner", client)
            [row] = notes.project_notes("session", ["Apa yang harus aku kerjakan di Statistika?"])
        self.assertEqual((row["project"], len(row["excerpt"])), ("Statistika", notes.PROJECT_EXCERPT))

    def test_no_named_project_reads_no_notes(self):
        client = MagicMock(); client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "p", "name": "Skripsi"}]
        with patch.object(notes, "scoped_client") as scoped:
            scoped.return_value.__enter__.return_value = ("owner", client)
            self.assertEqual(notes.project_notes("session", ["Apa itu regresi?"]), [])
        self.assertEqual(client.table.call_count, 1)

    def test_project_notes_lead_and_search_adds_a_few_more(self):
        from focusos_api import memory_answers
        own = [{"id": f"p{i}", "title": f"Proyek {i}", "excerpt": "isi", "project": "Statistika"} for i in range(2)]
        searched = [{"id": "p0", "title": "Proyek 0", "excerpt": "isi"}] + [{"id": f"s{i}", "title": f"Cari {i}", "excerpt": "isi"} for i in range(5)]
        with patch("focusos_api.notes.project_notes", return_value=own), patch("focusos_api.notes.note_matches", return_value=searched):
            rows = memory_answers._notes("session", ["Statistika?"], {})
        self.assertEqual([row["id"] for row in rows], ["p0", "p1", "s0", "s1", "s2"])

    def test_project_notes_survive_a_failed_search(self):
        from focusos_api import memory_answers
        own = [{"id": "p", "title": "Kuliah", "excerpt": "isi", "project": "Statistika"}]
        with patch("focusos_api.notes.project_notes", return_value=own), patch("focusos_api.notes.note_matches", side_effect=RuntimeError("down")):
            self.assertEqual(memory_answers._notes("session", ["Statistika?"], {}), own)

class ProjectViewTests(unittest.TestCase):
    def test_overview_counts_and_next_items(self):
        pid = str(uuid4()); task = str(uuid4())
        data = {"projects": [{"id": pid, "name": "Statistika", "created_at": "x"}],
                "tasks": [{"id": task, "title": "[Statistika] Tulis laporan", "status": "open", "due_kind": "date", "due_date": "2026-10-24", "project_id": pid},
                          {"id": str(uuid4()), "title": "done", "status": "done", "due_kind": "none", "project_id": pid}],
                "notes": [{"id": "n", "title": "Kuliah", "project_id": pid, "updated_at": "x"}],
                "assignments": [{"id": "a", "title": "Tugas 2", "status": "planned", "project_id": pid}],
                "blocks": [{"id": "b", "task_id": task, "cancellation_status": "none",
                            "payload": {"title": "[Statistika] Tulis laporan", "start": "2026-10-20T02:00:00+00:00", "end": "2026-10-20T03:00:00+00:00", "timezone": "Asia/Jakarta"}}]}
        with patch.object(project_view, "_gather", return_value=data):
            [row] = project_view.overview("session", datetime(2026, 10, 18, tzinfo=timezone.utc))
        self.assertEqual((row["open_tasks"], row["done_tasks"], row["notes"], row["assignments"], row["next_deadline"]), (1, 1, 1, 1, "2026-10-24"))
        self.assertEqual(row["next_block"]["title"], "[Statistika] Tulis laporan")


    def test_detail_summit_is_the_last_open_deadline(self):
        pid = str(uuid4())
        data = {"projects": [{"id": pid, "name": "Statistika", "created_at": "x"}, {"id": str(uuid4()), "name": "Lain", "created_at": "x"}],
                "tasks": [{"id": "a", "title": "A", "status": "open", "due_kind": "date", "due_date": "2026-10-21", "project_id": pid},
                          {"id": "b", "title": "B", "status": "open", "due_kind": "date", "due_date": "2026-10-24", "project_id": pid},
                          {"id": "c", "title": "C", "status": "done", "due_kind": "date", "due_date": "2026-11-30", "project_id": pid}],
                "notes": [], "assignments": [], "blocks": []}
        with patch.object(project_view, "_gather", return_value=data):
            found = project_view.detail("session", pid, datetime(2026, 10, 18, tzinfo=timezone.utc))
            self.assertEqual((found["deadline"], [task["id"] for task in found["tasks"]]), ("2026-10-24", ["a", "b", "c"]))
            with self.assertRaises(HTTPException) as missing: project_view.detail("session", uuid4())
        self.assertEqual(missing.exception.status_code, 404)

if __name__ == "__main__":
    unittest.main()
