import base64
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from focusos_api import project_files, project_view
from focusos_api.database import DatabaseUnavailable
from focusos_api.documents import DocumentInput

PDF = base64.b64encode(b"%PDF-1.7 brief").decode()


def response(status: int, body: dict | None = None):
    return MagicMock(status_code=status, text="", json=MagicMock(return_value=body or {}))


def scoped(client):
    context = MagicMock(); context.__enter__.return_value = ("owner", client); return context


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.file = project_files.FileInput(id=uuid4(), filename="Tugas 2 (final).pdf", mime_type="application/pdf", data=PDF)

    def test_storage_key_is_safe_and_under_the_owner(self):
        self.assertEqual(project_files.safe_name("Tugas 2 (final).pdf"), "Tugas-2-final-.pdf")
        self.assertEqual(project_files.safe_name("../../.."), "file")
        client = MagicMock(); client.rpc.return_value.execute.return_value.data = {"id": str(self.file.id)}
        with patch.object(project_files, "scoped_client", return_value=scoped(client)), \
             patch.object(project_files, "_storage", return_value=response(200)) as storage:
            project_files.upload_file("session", uuid4(), self.file)
        method, path = storage.call_args.args[1:3]
        self.assertEqual((method, path), ("POST", f"object/project-files/owner/{self.file.id}/Tugas-2-final-.pdf"))
        args = client.rpc.call_args.args[1]
        self.assertEqual((args["p_name"], args["p_size"], args["p_path"]), ("Tugas 2 (final).pdf", len(b"%PDF-1.7 brief"), f"owner/{self.file.id}/Tugas-2-final-.pdf"))

    def test_a_retried_upload_that_already_reached_storage_is_fine(self):
        client = MagicMock(); client.rpc.return_value.execute.return_value.data = {"id": str(self.file.id)}
        with patch.object(project_files, "scoped_client", return_value=scoped(client)), patch.object(project_files, "_storage", return_value=response(409)):
            self.assertEqual(project_files.upload_file("session", uuid4(), self.file)["id"], str(self.file.id))

    def test_a_file_that_is_not_a_pdf_is_refused_before_storage(self):
        fake = project_files.FileInput(id=uuid4(), filename="x.pdf", mime_type="application/pdf", data=base64.b64encode(b"MZ executable").decode())
        with patch.object(project_files, "_storage") as storage, self.assertRaises(HTTPException) as raised:
            project_files.upload_file("session", uuid4(), fake)
        self.assertEqual(raised.exception.status_code, 422); storage.assert_not_called()

    def test_bytes_are_removed_when_the_row_is_refused(self):
        error = DatabaseUnavailable("x"); error.__cause__ = type("E", (Exception,), {"code": "P0002"})()
        client = MagicMock(); client.rpc.return_value.execute.side_effect = error
        with patch.object(project_files, "scoped_client", return_value=scoped(client)), \
             patch.object(project_files, "_storage", return_value=response(200)) as storage, self.assertRaises(HTTPException) as raised:
            project_files.upload_file("session", uuid4(), self.file)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(storage.call_args.args[1], "DELETE")

    def test_an_assignment_brief_is_kept_best_effort(self):
        document = DocumentInput(request_key=uuid4(), filename="brief.pdf", mime_type="application/pdf", data=PDF)
        with patch.object(project_files, "store", side_effect=DatabaseUnavailable("down")):
            self.assertFalse(project_files.keep_brief("session", document, b"%PDF", uuid4()))
        with patch.object(project_files, "store", return_value={"id": "f"}) as store:
            self.assertTrue(project_files.keep_brief("session", document, b"%PDF", assignment := uuid4()))
        self.assertEqual(store.call_args.args[3:], (None, assignment))


class LinkTests(unittest.TestCase):
    def test_link_is_signed_for_a_few_minutes(self):
        client = MagicMock(); client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = \
            [{"name": "brief.pdf", "storage_path": "owner/f/brief.pdf"}]
        with patch.object(project_files, "scoped_client", return_value=scoped(client)), \
             patch.object(project_files, "_storage", return_value=response(200, {"signedURL": "/object/sign/project-files/owner/f/brief.pdf?token=t"})) as storage, \
             patch.object(project_files, "_settings", return_value=("https://db.example", "sb_publishable_x")):
            link = project_files.file_link("session", uuid4())
        self.assertEqual(link["url"], "https://db.example/storage/v1/object/sign/project-files/owner/f/brief.pdf?token=t")
        self.assertEqual(storage.call_args.kwargs["json"], {"expiresIn": project_files.LINK_SECONDS})

    def test_someone_elses_file_is_not_found(self):
        client = MagicMock(); client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        with patch.object(project_files, "scoped_client", return_value=scoped(client)), self.assertRaises(HTTPException) as raised:
            project_files.file_link("session", uuid4())
        self.assertEqual(raised.exception.status_code, 404)

    def test_delete_forgets_the_row_then_removes_the_bytes(self):
        client = MagicMock(); client.rpc.return_value.execute.return_value.data = "owner/f/brief.pdf"
        with patch.object(project_files, "scoped_client", return_value=scoped(client)), patch.object(project_files, "_storage", return_value=response(200)) as storage:
            self.assertEqual(project_files.delete_file("session", uuid4()), {"deleted": True})
        self.assertEqual(storage.call_args.args[1:3], ("DELETE", "object/project-files/owner/f/brief.pdf"))


class DetailFilesTests(unittest.TestCase):
    def test_detail_lists_own_files_and_assignment_briefs_and_past_blocks(self):
        pid, other, task = str(uuid4()), str(uuid4()), str(uuid4())
        data = {"projects": [{"id": pid, "name": "Statistika", "created_at": "x"}],
                "tasks": [{"id": task, "title": "T", "status": "open", "due_kind": "none", "project_id": pid}],
                "notes": [], "assignments": [{"id": "a", "title": "Tugas 2", "status": "planned", "project_id": pid}],
                "files": [{"id": "f1", "project_id": pid, "assignment_id": None, "name": "rubrik.png", "created_at": "2"},
                          {"id": "f2", "project_id": None, "assignment_id": "a", "name": "brief.pdf", "created_at": "1"},
                          {"id": "f3", "project_id": other, "assignment_id": None, "name": "lain.pdf", "created_at": "3"}],
                "blocks": [{"id": "b1", "task_id": task, "cancellation_status": "none", "payload": {"title": "T", "start": "2026-10-16T02:00:00+00:00", "end": "2026-10-16T03:00:00+00:00", "timezone": "Asia/Jakarta"}},
                           {"id": "b2", "task_id": task, "cancellation_status": "none", "payload": {"title": "T", "start": "2026-10-20T02:00:00+00:00", "end": "2026-10-20T03:00:00+00:00", "timezone": "Asia/Jakarta"}}]}
        with patch.object(project_view, "_gather", return_value=data):
            found = project_view.detail("session", pid, datetime(2026, 10, 18, tzinfo=timezone.utc))
            [row] = project_view.overview("session", datetime(2026, 10, 18, tzinfo=timezone.utc))
        self.assertEqual([(item["id"], item["assignment"]) for item in found["files"]], [("f1", None), ("f2", "Tugas 2")])
        self.assertEqual(([b["id"] for b in found["upcoming"]], [b["id"] for b in found["past"]]), (["b2"], ["b1"]))
        self.assertEqual(row["files"], 2)


if __name__ == "__main__":
    unittest.main()
