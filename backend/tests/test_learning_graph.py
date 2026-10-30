"""Learning paths: an assignment's concepts as a prerequisite graph, booked in learning order. Model and DB are simulated."""
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from focusos_api import assignments, unified_commands
from focusos_api.assignments import (MAX_DEPTH, GraphEdit, ancestors, grounded, learning_graph, levels, planned_tasks,
                                     schedule_order)
from focusos_api.jobs import Step
from focusos_api.planning_compiler import compile_plan
from focusos_api.unified_commands import ScheduleIntent, WorkIntent
from test_assignments_notes import BRIEF, TODAY, analysis
from test_planning_compiler import NOW, PROFILE, TASK, ZONE, checkpoint, selection
from test_unified_commands import sel


def concept(name, prerequisites=(), kind="core", minutes=60):
    return {"name": name, "why": f"Untuk {name}.", "study_minutes": minutes, "kind": kind, "prerequisites": list(prerequisites)}


def names(concepts):
    return [item["name"] for item in concepts]


class GraphTests(unittest.TestCase):
    def test_concepts_come_in_learning_order_with_their_prerequisites_renumbered(self):
        # The model listed the advanced topic first.
        ordered, subtasks = learning_graph([concept("Regresi", [1, 2]), concept("Korelasi", [2]), concept("Statistik deskriptif")],
                                           [{"title": "Analisis", "estimate_minutes": 60, "needs": [0]}])
        self.assertEqual(names(ordered), ["Statistik deskriptif", "Korelasi", "Regresi"])
        # Regresi needs Korelasi, which needs Statistik deskriptif: the implied edge is dropped.
        self.assertEqual([item["prerequisites"] for item in ordered], [[], [0], [1]])
        self.assertEqual(subtasks[0]["needs"], [2])
        self.assertEqual(levels(ordered), [1, 2, 3])
        self.assertEqual(ancestors(ordered, 2), {0, 1})

    def test_cycles_self_and_unknown_references_are_removed(self):
        ordered, _ = learning_graph([concept("A", [1, 0, 9, -1]), concept("B", [0])], [])
        self.assertEqual(sum(len(item["prerequisites"]) for item in ordered), 1)  # one edge of the A<->B cycle survives
        self.assertTrue(all(index not in item["prerequisites"] for index, item in enumerate(ordered)))

    def test_at_most_two_foundations_and_their_references_go_with_them(self):
        ordered, subtasks = learning_graph([concept("F1", kind="foundation"), concept("F2", kind="foundation"),
                                            concept("F3", kind="foundation"), concept("Inti", [0, 2])],
                                           [{"title": "Kerjakan", "estimate_minutes": 60, "needs": [2, 3]}])
        self.assertEqual(names(ordered), ["F1", "F2", "Inti"])
        self.assertEqual(ordered[2]["prerequisites"], [0])
        self.assertEqual(subtasks[0]["needs"], [2])

    def test_a_chain_deeper_than_the_limit_is_cut(self):
        chain = [concept(f"C{index}", [index - 1] if index else []) for index in range(MAX_DEPTH + 2)]
        ordered, _ = learning_graph(chain, [])
        self.assertLessEqual(max(levels(ordered)), MAX_DEPTH)

    def test_grounding_keeps_the_graph_and_old_analyses_still_load(self):
        result = grounded(analysis(concepts=[concept("Uji asumsi", [1]), concept("Regresi linear")]), BRIEF)
        self.assertEqual([item.name for item in result.concepts], ["Regresi linear", "Uji asumsi"])
        self.assertEqual(result.concepts[1].prerequisites, [0])
        legacy = grounded(analysis(), BRIEF)  # concepts without kind or prerequisites
        self.assertTrue(all(item.prerequisites == [] and item.kind == "core" for item in legacy.concepts))


class OrderTests(unittest.TestCase):
    DATA = {"due": {"date": "2026-10-30"}, "concepts": [concept("Dasar"), concept("Tengah", [0]), concept("Lanjut", [1])],
            "subtasks": [{"title": "Kerjakan", "estimate_minutes": 60, "needs": [2]}, {"title": "Rapikan", "estimate_minutes": 30, "needs": []}]}

    def test_each_task_waits_for_every_studied_concept_it_builds_on(self):
        tasks = planned_tasks(self.DATA, {"0": "not", "1": "understood", "2": "not"}, "Stat", TODAY)
        by_key = {item["key"]: item["after"] for item in tasks}
        # Lanjut builds on Dasar through Tengah, which is already understood.
        self.assertEqual(by_key, {"study-0": [], "study-2": ["study-0"], "sub-0": ["study-0", "study-2"], "sub-1": []})
        self.assertEqual(schedule_order(tasks, 12), {"1": [0], "2": [0, 1]})
        # A part beyond the booking limit is not referenced.
        self.assertEqual(schedule_order(tasks, 2), {"1": [0]})


class EditTests(unittest.TestCase):
    def row(self, **changes):
        data = {"due": {"date": None}, "concepts": [concept("Dasar"), concept("Lanjut", [0])], "subtasks": []}
        return {"id": str(uuid4()), "status": "questions", "version": 3, "analysis": data, "understanding": {}, **changes}

    def test_a_wrong_prerequisite_can_be_removed_before_planning(self):
        with patch.object(assignments, "_load", return_value=self.row()), \
             patch.object(assignments, "_update", side_effect=lambda token, r, fields: {**r, **fields}):
            saved = assignments.edit_graph("session", uuid4(), GraphEdit(expected_version=3, concept=1, remove_prerequisite=0))
        self.assertEqual(saved["analysis"]["concepts"][1]["prerequisites"], [])
        self.assertEqual(names(saved["analysis"]["concepts"]), ["Dasar", "Lanjut"])  # positions stay

    def test_edits_are_refused_when_planned_stale_or_unknown(self):
        cases = [(self.row(status="planned"), GraphEdit(expected_version=3, concept=1, remove_prerequisite=0), 409),
                 (self.row(), GraphEdit(expected_version=2, concept=1, remove_prerequisite=0), 409),
                 (self.row(), GraphEdit(expected_version=3, concept=0, remove_prerequisite=1), 422)]
        for row, edit, status in cases:
            with self.subTest(status=status), patch.object(assignments, "_load", return_value=row), self.assertRaises(HTTPException) as raised:
                assignments.edit_graph("session", uuid4(), edit)
            self.assertEqual(raised.exception.status_code, status)


class BookingOrderTests(unittest.TestCase):
    def test_the_planner_starts_no_earlier_than_the_parts_it_builds_on_end(self):
        after = datetime(2026, 10, 3, 14, 30, tzinfo=ZONE)
        result, _ = compile_plan(selection(day="any"), [TASK], checkpoint(not_before=after.isoformat()), PROFILE, now=NOW)
        self.assertGreaterEqual(datetime.fromisoformat(result["blocks"][0]["start"]), after)

    def ordered(self, ends):
        tasks = [{"id": str(uuid4()), "title": title, "due_kind": "none", "estimate_minutes": 60} for title in ("Belajar dasar", "Belajar lanjut")]
        schedules = [ScheduleIntent(target="existing", title_quote=None, request_quote="-", selection=sel(task_refs=[f"task-{i + 1}"]))
                     for i in range(2)]
        intent = WorkIntent(capture=False, questions=[], schedules=schedules, clarification=None, explanation="Book.")
        run = SimpleNamespace(id=uuid4(), checkpoint={"intent_tasks": tasks, "schedule_after": {"1": [0]}, "window_start": NOW.isoformat()})
        return run, intent, {"schedule_index": 1, "part_ends": ends}

    def test_a_part_whose_prerequisite_was_not_booked_waits_and_says_why(self):
        run, intent, cp = self.ordered({})
        with patch.object(unified_commands, "_finalize", side_effect=lambda token, run, intent, cp, result: Step("succeeded", cp, result)):
            step = unified_commands._prepare_schedule("session", run, intent, cp, {})
        entry = step.result["schedules"][-1]
        self.assertEqual((entry["status"], entry["code"]), ("failed", "prerequisite_unscheduled"))
        self.assertIn("Belajar dasar", entry["message"])

    def test_a_part_after_a_booked_prerequisite_carries_its_end(self):
        end = datetime(2026, 10, 3, 7, 30, tzinfo=timezone.utc).isoformat()
        run, intent, cp = self.ordered({"0": end})
        with patch.object(unified_commands, "read_profile", return_value=None):
            step = unified_commands._prepare_schedule("session", run, intent, cp, {})
        # Past the ordering check: it fails only for the missing profile in this test.
        self.assertEqual(step.result["schedules"][-1]["code"] if "schedules" in step.result else None, "profile_required")

    def test_a_finished_part_records_when_its_last_block_ends(self):
        run, intent, _ = self.ordered({})
        run.checkpoint["work_plan"] = intent.model_dump()
        blocks = [{"end": "2026-10-03T03:00:00+00:00"}, {"end": "2026-10-03T05:00:00+00:00"}]
        step = Step("succeeded", {"schedule_index": 0, "blocks_before": 0}, {"blocks": blocks})
        with patch.object(unified_commands, "_next_part", side_effect=lambda token, run, intent, cp, result, index: Step(checkpoint=cp, result=result)):
            finished = unified_commands.schedule_finished("session", {}, run, step)
        self.assertEqual(finished.checkpoint["part_ends"], {"0": "2026-10-03T05:00:00+00:00"})


if __name__ == "__main__":
    unittest.main()
