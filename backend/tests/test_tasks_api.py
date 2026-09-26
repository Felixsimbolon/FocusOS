import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from focusos_api.main import app
from focusos_api.tasks import (
    TaskCreate,
    _payload_hash,
    TaskRequestConflict,
    create_task,
    list_tasks,
)


TASK_ID = "4304c278-a7e8-42d7-a6b3-825986f71112"
TASK_ROW = {
    "id": TASK_ID,
    "title": "Write demo",
    "description": None,
    "status": "open",
    "priority": "normal",
    "due_kind": "none",
    "due_date": None,
    "due_at": None,
    "due_timezone": None,
    "estimate_minutes": None,
    "estimate_origin": None,
    "project_id": None,
    "version": 1,
    "created_at": "2026-09-26T12:00:00+00:00",
    "updated_at": "2026-09-26T12:00:00+00:00",
}


class TaskRepositoryTests(unittest.TestCase):
    def test_list_is_user_filtered_status_filtered_and_bounded(self):
        with patch("focusos_api.tasks.scoped_client") as scoped:
            client = Mock()
            query = client.table.return_value.select.return_value
            query.eq.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value.data = [
                TASK_ROW
            ]
            scoped.return_value.__enter__.return_value = ("owner-123", client)

            result = list_tasks("user-token", status="open", limit=20)

        self.assertEqual(len(result.tasks), 1)
        self.assertFalse(result.truncated)
        client.table.assert_called_once_with("tasks")
        query.eq.assert_called_once_with("user_id", "owner-123")
        query.eq.return_value.eq.assert_called_once_with("status", "open")
        query.eq.return_value.eq.return_value.order.assert_called_once_with("created_at", desc=True)
        query.eq.return_value.eq.return_value.order.return_value.order.assert_called_once_with(
            "id", desc=True
        )
        query.eq.return_value.eq.return_value.order.return_value.order.return_value.limit.assert_called_once_with(21)

    def test_create_passes_only_validated_fields_and_returns_safe_task(self):
        request_id = UUID("9f4cdd59-ab23-4f8c-85fd-6ef4cc872718")
        with patch("focusos_api.tasks.scoped_client") as scoped:
            client = Mock()
            client.rpc.return_value.execute.return_value.data = [
                {"task": TASK_ROW, "replayed": False, "stored_request_hash": _payload_hash(TaskCreate(title="Write demo"))}
            ]
            scoped.return_value.__enter__.return_value = ("owner-123", client)

            result = create_task("user-token", request_id, TaskCreate(title="Write demo"))

        self.assertEqual(result.task.id, UUID(TASK_ID))
        self.assertFalse(result.replayed)
        args = client.rpc.call_args.args[1]
        self.assertEqual(args["p_create_request_id"], str(request_id))
        self.assertEqual(len(args["p_create_request_hash"]), 64)
        self.assertEqual(args["p_title"], "Write demo")
        self.assertNotIn("user_id", args)
        self.assertNotIn("status", args)

    def test_create_rejects_mismatched_replay_hash(self):
        with patch("focusos_api.tasks.scoped_client") as scoped:
            client = Mock()
            client.rpc.return_value.execute.return_value.data = [
                {"task": TASK_ROW, "replayed": True, "stored_request_hash": "0" * 64}
            ]
            scoped.return_value.__enter__.return_value = ("owner-123", client)
            with self.assertRaises(TaskRequestConflict):
                create_task(
                    "user-token",
                    UUID("9f4cdd59-ab23-4f8c-85fd-6ef4cc872718"),
                    TaskCreate(title="Write demo"),
                )


class TaskRouteTests(unittest.TestCase):
    def test_anonymous_task_reads_and_writes_are_denied(self):
        with patch("focusos_api.main.list_tasks") as read, patch(
            "focusos_api.main.create_task"
        ) as create:
            with TestClient(app) as client:
                get_response = client.get("/tasks")
                post_response = client.post(
                    "/tasks",
                    headers={"Idempotency-Key": TASK_ID},
                    json={"title": "Write demo"},
                )

        self.assertEqual(get_response.status_code, 401)
        self.assertEqual(post_response.status_code, 401)
        read.assert_not_called()
        create.assert_not_called()

    def test_task_create_requires_uuid_request_key(self):
        with TestClient(app) as client:
            response = client.post(
                "/tasks",
                headers={"Authorization": "Bearer token", "Idempotency-Key": "bad"},
                json={"title": "Write demo"},
            )
        self.assertEqual(response.status_code, 422)

    def test_create_route_returns_replay_status_but_no_internal_hash(self):
        result = {
            "task": TASK_ROW,
            "replayed": True,
        }
        with patch("focusos_api.main.create_task", return_value=result) as create:
            with TestClient(app) as client:
                response = client.post(
                    "/tasks",
                    headers={
                        "Authorization": "Bearer user-token",
                        "Idempotency-Key": TASK_ID,
                    },
                    json={"title": "Write demo"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["replayed"], True)
        self.assertEqual(response.json()["task"]["id"], TASK_ID)
        self.assertNotIn("hash", response.text.lower())
        self.assertNotIn("user_id", response.json()["task"])
        self.assertEqual(create.call_args.args[1], UUID(TASK_ID))

    def test_create_route_maps_idempotency_reuse_to_conflict(self):
        with patch("focusos_api.main.create_task", side_effect=TaskRequestConflict()):
            with TestClient(app) as client:
                response = client.post(
                    "/tasks",
                    headers={
                        "Authorization": "Bearer user-token",
                        "Idempotency-Key": TASK_ID,
                    },
                    json={"title": "Write demo"},
                )
        self.assertEqual(response.status_code, 409)

    def test_list_route_passes_filters_to_repository(self):
        result = {"tasks": [TASK_ROW], "truncated": False}
        with patch("focusos_api.main.list_tasks", return_value=result) as read:
            with TestClient(app) as client:
                response = client.get(
                    "/tasks?status=open&limit=25",
                    headers={"Authorization": "Bearer user-token"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tasks"][0]["id"], TASK_ID)
        self.assertEqual(read.call_args.kwargs, {"status": "open", "limit": 25})


if __name__ == "__main__":
    unittest.main()
