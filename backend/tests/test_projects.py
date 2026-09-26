import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import ValidationError

from focusos_api.main import app
from focusos_api.tasks import (
    ProjectCreate,
    TaskCreate,
    TaskProjectNotFound,
    _payload_hash,
    create_project,
    create_task,
    list_projects,
)


PROJECT_ID = "7304c278-a7e8-42d7-a6b3-825986f71112"
PROJECT_ROW = {
    "id": PROJECT_ID,
    "name": "Portfolio",
    "created_at": "2026-09-26T12:00:00+00:00",
}


class ProjectValidationTests(unittest.TestCase):
    def test_project_name_is_trimmed(self):
        self.assertEqual(ProjectCreate(name="  Portfolio  ").name, "Portfolio")

    def test_blank_oversized_and_unknown_project_fields_are_rejected(self):
        for payload in (
            {"name": "  "},
            {"name": "x" * 101},
            {"name": "Portfolio", "user_id": "other"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    ProjectCreate(**payload)

    def test_task_accepts_optional_project_uuid(self):
        task = TaskCreate(title="Draft", project_id=PROJECT_ID)
        self.assertEqual(task.project_id, UUID(PROJECT_ID))


class ProjectRepositoryTests(unittest.TestCase):
    def test_list_projects_is_owner_filtered_and_bounded(self):
        with patch("focusos_api.tasks.scoped_client") as scoped:
            client = Mock()
            client.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value.data = [
                PROJECT_ROW
            ]
            scoped.return_value.__enter__.return_value = ("owner-123", client)

            result = list_projects("user-token")

        self.assertEqual(result.projects[0].id, UUID(PROJECT_ID))
        query = client.table.return_value.select.return_value
        query.eq.assert_called_once_with("user_id", "owner-123")
        query.eq.return_value.order.assert_called_once_with("name")
        query.eq.return_value.order.return_value.order.assert_called_once_with("id")
        query.eq.return_value.order.return_value.order.return_value.limit.assert_called_once_with(100)

    def test_task_repository_rejects_a_project_the_owner_cannot_access(self):
        payload = TaskCreate(title="Draft", project_id=PROJECT_ID)
        with patch("focusos_api.tasks.scoped_client") as scoped:
            client = Mock()
            client.rpc.return_value.execute.return_value.data = [
                {
                    "task": None,
                    "replayed": False,
                    "stored_request_hash": _payload_hash(payload),
                    "project_available": False,
                }
            ]
            scoped.return_value.__enter__.return_value = ("owner-123", client)

            with self.assertRaises(TaskProjectNotFound):
                create_task(
                    "user-token",
                    UUID("9f4cdd59-ab23-4f8c-85fd-6ef4cc872718"),
                    payload,
                )
        args = client.rpc.call_args.args[1]
        self.assertEqual(args["p_project_id"], PROJECT_ID)

    def test_project_creation_uses_the_owner_derived_rpc_and_safe_dto(self):
        with patch("focusos_api.tasks.scoped_client") as scoped:
            client = Mock()
            client.rpc.return_value.execute.return_value.data = [
                {"project": PROJECT_ROW, "existing": False}
            ]
            scoped.return_value.__enter__.return_value = ("owner-123", client)

            result = create_project("user-token", ProjectCreate(name="Portfolio"))

        self.assertEqual(result.project.id, UUID(PROJECT_ID))
        self.assertFalse(result.existing)
        client.rpc.assert_called_once_with(
            "focusos_create_project", {"p_name": "Portfolio"}
        )
        self.assertNotIn("user_id", result.project.model_dump())


class ProjectRouteTests(unittest.TestCase):
    def test_anonymous_project_routes_are_denied(self):
        with patch("focusos_api.main.list_projects") as read, patch(
            "focusos_api.main.create_project"
        ) as create:
            with TestClient(app) as client:
                get_response = client.get("/projects")
                post_response = client.post("/projects", json={"name": "Portfolio"})
        self.assertEqual(get_response.status_code, 401)
        self.assertEqual(post_response.status_code, 401)
        read.assert_not_called()
        create.assert_not_called()

    def test_project_creation_returns_existing_status(self):
        with patch(
            "focusos_api.main.create_project",
            return_value={"project": PROJECT_ROW, "existing": True},
        ) as create:
            with TestClient(app) as client:
                response = client.post(
                    "/projects",
                    headers={"Authorization": "Bearer user-token"},
                    json={"name": "Portfolio"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["existing"])
        self.assertNotIn("user_id", response.text)
        self.assertEqual(create.call_args.args[1].name, "Portfolio")

    def test_task_with_unowned_project_returns_concealed_not_found(self):
        with patch(
            "focusos_api.main.create_task", side_effect=TaskProjectNotFound()
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/tasks",
                    headers={
                        "Authorization": "Bearer user-token",
                        "Idempotency-Key": "4304c278-a7e8-42d7-a6b3-825986f71112",
                    },
                    json={"title": "Draft", "project_id": PROJECT_ID},
                )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Project not found")
