import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from pydantic import ValidationError

from focusos_api.main import app
from focusos_api.profiles import ProfileRecord
from focusos_api.tasks import (
    TaskRecord,
    TaskUpdate,
    TaskUpdateEnvelope,
    _today_key,
    list_today_tasks,
    update_task,
)


TASK_ID = "4304c278-a7e8-42d7-a6b3-825986f71112"


def task_row(
    *,
    task_id: str = TASK_ID,
    title: str = "Prepare demo",
    status: str = "open",
    priority: str = "normal",
    due_kind: str = "none",
    due_date: str | None = None,
    due_at: str | None = None,
    due_timezone: str | None = None,
    version: int = 1,
):
    return {
        "id": task_id,
        "title": title,
        "description": None,
        "status": status,
        "priority": priority,
        "due_kind": due_kind,
        "due_date": due_date,
        "due_at": due_at,
        "due_timezone": due_timezone,
        "estimate_minutes": None,
        "estimate_origin": None,
        "project_id": None,
        "version": version,
        "created_at": "2026-03-08T12:00:00+00:00",
        "updated_at": "2026-03-08T12:00:00+00:00",
    }


class TaskUpdateValidationTests(unittest.TestCase):
    def test_update_requires_positive_version_and_at_least_one_field(self):
        with self.assertRaises(ValidationError):
            TaskUpdate(expected_version=1)
        with self.assertRaises(ValidationError):
            TaskUpdate(expected_version=0, title="New")
        with self.assertRaises(ValidationError):
            TaskUpdate(expected_version=True, title="New")

    def test_patch_normalizes_title_and_can_clear_description_or_estimate(self):
        patch = TaskUpdate(
            expected_version=2,
            title="  Revised title ",
            description=None,
            estimate_minutes=None,
        )
        self.assertEqual(patch.title, "Revised title")
        self.assertIsNone(patch.description)
        self.assertIsNone(patch.estimate_minutes)

    def test_status_and_priority_are_allowlisted(self):
        for data in ({"status": "deleted"}, {"priority": "urgent"}, {"title": " "}):
            with self.subTest(data=data):
                with self.assertRaises(ValidationError):
                    TaskUpdate(expected_version=1, **data)

    def test_deadline_patch_must_supply_complete_consistent_tuple(self):
        with self.assertRaises(ValidationError):
            TaskUpdate(expected_version=1, due_date="2026-03-08")
        clear = TaskUpdate(
            expected_version=1,
            due_kind="none",
            due_date=None,
            due_at=None,
            due_timezone=None,
        )
        self.assertEqual(clear.due_kind, "none")
        with self.assertRaises(ValidationError):
            TaskUpdate(
                expected_version=1,
                due_kind="datetime",
                due_date=None,
                due_at="2026-03-08T09:00:00",
                due_timezone="Asia/Jakarta",
            )

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            TaskUpdate(expected_version=1, title="New", user_id="another")


class TaskUpdateRepositoryTests(unittest.TestCase):
    def test_update_uses_version_rpc_and_does_not_send_unset_fields(self):
        updated = task_row(title="Revised title", version=2)
        with patch("focusos_api.tasks.scoped_client") as scoped:
            client = Mock()
            client.rpc.return_value.execute.return_value.data = [
                {"outcome": "updated", "task": updated}
            ]
            scoped.return_value.__enter__.return_value = ("owner-123", client)

            result = update_task(
                "user-token",
                UUID(TASK_ID),
                TaskUpdate(expected_version=1, title=" Revised title "),
            )

        self.assertEqual(result.outcome, "updated")
        self.assertEqual(result.task.version, 2)
        args = client.rpc.call_args.args[1]
        self.assertEqual(args["p_expected_version"], 1)
        self.assertEqual(args["p_changes"], {"title": "Revised title"})
        self.assertNotIn("user_id", args["p_changes"])

    def test_today_filter_uses_profile_local_midnight_across_dst(self):
        profile = ProfileRecord(
            id=UUID(TASK_ID),
            timezone="America/New_York",
            working_hours={"days": [1], "start_minute": 540, "end_minute": 1020},
        )
        with patch("focusos_api.tasks.read_profile", return_value=profile), patch(
            "focusos_api.tasks.scoped_client"
        ) as scoped:
            client = Mock()
            chain = (
                client.table.return_value.select.return_value
                .eq.return_value.eq.return_value.or_.return_value.limit.return_value
                .execute.return_value
            )
            chain.data = []
            scoped.return_value.__enter__.return_value = ("owner-123", client)

            result = list_today_tasks(
                "user-token",
                now=datetime(2026, 3, 8, 12, tzinfo=ZoneInfo("America/New_York")),
            )

        self.assertEqual(result.today, date(2026, 3, 8))
        self.assertEqual(result.timezone, "America/New_York")
        query = client.table.return_value.select.return_value.eq.return_value.eq.return_value
        query.or_.assert_called_once_with(
            "due_kind.eq.none,due_date.lte.2026-03-08,due_at.lt.2026-03-09T04:00:00+00:00"
        )
        query.or_.return_value.limit.assert_called_once_with(1001)

    def test_today_order_is_deadline_then_priority_then_stable_id(self):
        rows = [
            task_row(task_id="f304c278-a7e8-42d7-a6b3-825986f71112", due_kind="date", due_date="2026-03-08", priority="normal"),
            task_row(task_id="1304c278-a7e8-42d7-a6b3-825986f71112", due_kind="date", due_date="2026-03-08", priority="high"),
            task_row(task_id="0304c278-a7e8-42d7-a6b3-825986f71112", due_kind="date", due_date="2026-03-07", priority="low"),
            task_row(task_id="2304c278-a7e8-42d7-a6b3-825986f71112", priority="high"),
        ]
        tasks = [TaskRecord.model_validate(row) for row in rows]
        ordered = sorted(tasks, key=lambda task: _today_key(task, ZoneInfo("Asia/Jakarta")))
        self.assertEqual(
            [str(task.id) for task in ordered],
            [
                "0304c278-a7e8-42d7-a6b3-825986f71112",
                "1304c278-a7e8-42d7-a6b3-825986f71112",
                "f304c278-a7e8-42d7-a6b3-825986f71112",
                "2304c278-a7e8-42d7-a6b3-825986f71112",
            ],
        )


class TaskUpdateRouteTests(unittest.TestCase):
    def test_today_and_patch_routes_require_authentication(self):
        with patch("focusos_api.main.list_today_tasks") as today, patch(
            "focusos_api.main.update_task"
        ) as update:
            with TestClient(app) as client:
                today_response = client.get("/tasks/today")
                patch_response = client.patch(
                    f"/tasks/{TASK_ID}",
                    json={"expected_version": 1, "status": "done"},
                )
        self.assertEqual(today_response.status_code, 401)
        self.assertEqual(patch_response.status_code, 401)
        today.assert_not_called()
        update.assert_not_called()

    def test_stale_edit_returns_409_with_latest_owner_task(self):
        current = TaskRecord.model_validate(task_row(title="Saved elsewhere", version=2))
        with patch(
            "focusos_api.main.update_task",
            return_value=TaskUpdateEnvelope(task=current, outcome="stale"),
        ):
            with TestClient(app) as client:
                response = client.patch(
                    f"/tasks/{TASK_ID}",
                    headers={"Authorization": "Bearer user-token"},
                    json={"expected_version": 1, "title": "My stale edit"},
                )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["task"]["version"], 2)
        self.assertEqual(response.json()["detail"]["task"]["title"], "Saved elsewhere")

    def test_successful_completion_returns_incremented_version(self):
        current = TaskRecord.model_validate(task_row(status="done", version=2))
        with patch(
            "focusos_api.main.update_task",
            return_value=TaskUpdateEnvelope(task=current, outcome="updated"),
        ) as update:
            with TestClient(app) as client:
                response = client.patch(
                    f"/tasks/{TASK_ID}",
                    headers={"Authorization": "Bearer user-token"},
                    json={"expected_version": 1, "status": "done"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["task"]["status"], "done")
        self.assertEqual(response.json()["task"]["version"], 2)
        self.assertEqual(update.call_args.args[2].status, "done")

    def test_invalid_partial_deadline_patch_is_rejected_before_write(self):
        with patch("focusos_api.main.update_task") as update:
            with TestClient(app) as client:
                response = client.patch(
                    f"/tasks/{TASK_ID}",
                    headers={"Authorization": "Bearer user-token"},
                    json={"expected_version": 1, "due_date": "2026-03-08"},
                )
        self.assertEqual(response.status_code, 422)
        update.assert_not_called()
