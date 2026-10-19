"""Email notifications and document capture. Gmail, Gemini and the database are simulated."""
import base64
import email
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from focusos_api import documents, notifications
from focusos_api.documents import DocumentInput, DocumentRejected
from focusos_api.notifications import GMAIL_SEND_SCOPE, compose, raw_message, send_due, send_one

NOW = datetime(2026, 10, 17, 0, 0, tzinfo=timezone.utc)  # 07:00 in Jakarta
CONNECTION = {"id": str(uuid4()), "email": "me@example.test", "scopes": [GMAIL_SEND_SCOPE]}


def reminder(minutes=10, **block):
    start = NOW + timedelta(minutes=minutes)
    return {"id": str(uuid4()), "kind": "block_reminder", "timezone": "Asia/Jakarta", "connection": CONNECTION,
            "block": {"title": "Revisi bab 2", "start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat(), "cancelled": False, **block}}


def brief(**data):
    return {"id": str(uuid4()), "kind": "morning_brief", "timezone": "Asia/Jakarta", "connection": CONNECTION,
            "brief": {"blocks": [], "due_today": [], "overdue": [], "urgent_email": [], **data}}


class ComposeTests(unittest.TestCase):
    def test_reminder_names_the_block_and_its_local_time(self):
        subject, body = compose(reminder(), NOW)
        self.assertEqual(subject, "In 10 min: Revisi bab 2 (07:10–08:10)")
        self.assertIn("starts at 07:10", body)

    def test_reminders_for_cancelled_or_started_blocks_are_not_sent(self):
        self.assertIsNone(compose(reminder(cancelled=True), NOW))
        self.assertIsNone(compose(reminder(minutes=-1), NOW))

    def test_brief_lists_the_day_and_says_when_it_is_clear(self):
        start = (NOW + timedelta(hours=2)).isoformat(); end = (NOW + timedelta(hours=3)).isoformat()
        subject, body = compose(brief(blocks=[{"title": "Write report", "start": start, "end": end}], due_today=["Submit budget"],
                                      overdue=["Reply to Andi"], urgent_email=["Invoice overdue"]), NOW)
        self.assertEqual(subject, "Your day, Sat 17 Oct: 1 due, 1 focus block, 1 overdue")
        for text in ("09:00–10:00  Write report", "Due today:", "Submit budget", "Past the deadline:", "Urgent email:"):
            self.assertIn(text, body)
        self.assertIn("a clear day", compose(brief(), NOW)[0])

    def test_message_goes_from_the_owner_to_the_same_address(self):
        message = email.message_from_bytes(base64.urlsafe_b64decode(raw_message("me@example.test", "Subject", "Body")))
        self.assertEqual((message["To"], message["From"]), ("me@example.test", "FocusOS <me@example.test>"))


class SendTests(unittest.TestCase):
    def client(self, status):
        return MagicMock(post=MagicMock(return_value=httpx.Response(status, json={})))

    def test_outcomes_from_gmail(self):
        with patch.object(notifications, "_bearer", return_value="google-token"):
            self.assertEqual(send_one(reminder(), NOW, self.client(200)), ("sent", None))
            self.assertEqual(send_one(reminder(), NOW, self.client(403)), ("failed", "gmail_send_rejected"))
            self.assertEqual(send_one(reminder(), NOW, self.client(503)), ("pending", "provider_unavailable"))
        no_permission = {**reminder(), "connection": {**CONNECTION, "scopes": []}}
        self.assertEqual(send_one(no_permission, NOW, self.client(200)), ("failed", "gmail_send_permission"))
        self.assertEqual(send_one({**reminder(), "connection": None}, NOW, self.client(200)), ("failed", "google_not_connected"))
        self.assertEqual(send_one(reminder(cancelled=True), NOW, self.client(200)), ("sent", "nothing_to_send"))

    def test_token_failures_are_retried_without_leaking(self):
        with patch.object(notifications, "_bearer", side_effect=RuntimeError("refresh token secret")):
            self.assertEqual(send_one(reminder(), NOW, self.client(200)), ("pending", "provider_unavailable"))

    def test_worker_plans_claims_sends_and_records_each_email(self):
        calls = []
        def rpc(name, args):
            calls.append((name, args))
            return {"focusos_plan_notifications": 2, "focusos_claim_notifications": [reminder(), brief()]}.get(name, True)
        client = self.client(200)
        with patch.object(notifications, "_service_rpc", side_effect=rpc), patch.object(notifications, "_bearer", return_value="t"):
            counts = send_due(NOW, http_client=client)
        self.assertEqual(counts, {"planned": 2, "sent": 2, "failed": 0, "retry": 0})
        self.assertEqual([name for name, _ in calls].count("focusos_finish_notification"), 2)
        self.assertEqual(client.post.call_count, 2)

    def test_a_single_users_test_skips_planning(self):
        with patch.object(notifications, "_service_rpc", side_effect=lambda name, args: [] if name == "focusos_claim_notifications" else 0) as rpc:
            send_due(NOW, owner="owner-id", http_client=self.client(200))
        self.assertEqual([call.args[0] for call in rpc.call_args_list], ["focusos_claim_notifications"])
        self.assertEqual(rpc.call_args.args[1]["p_owner"], "owner-id")

    def test_tick_requires_the_worker_secret(self):
        from focusos_api.main import app
        client = TestClient(app)
        secret = "s" * 40
        with patch.dict("os.environ", {"FOCUSOS_WORKER_SECRET": secret}), patch.object(notifications, "send_due", return_value={"sent": 0}):
            self.assertEqual(client.post("/internal/notifications/tick").status_code, 401)
            self.assertEqual(client.post("/internal/notifications/tick", headers={"Authorization": "Bearer wrong"}).status_code, 401)
            self.assertEqual(client.post("/internal/notifications/tick", headers={"Authorization": "Bearer " + secret}).status_code, 200)


PDF = base64.b64encode(b"%PDF-1.7\n" + b"x" * 64).decode()


def docx(body: str, doctype: bool = False) -> bytes:
    """A minimal Word file: just word/document.xml with the given body."""
    import io, zipfile
    xml = ('<?xml version="1.0"?>' + ('<!DOCTYPE w:document [<!ENTITY a "aaaa">]>' if doctype else "")
           + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + "</w:body></w:document>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive: archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def document(**changes):
    return DocumentInput.model_validate({"request_key": str(uuid4()), "filename": "silabus.pdf", "mime_type": "application/pdf", "data": PDF, **changes})


class DocumentTests(unittest.TestCase):
    def test_files_must_match_their_type_and_size(self):
        documents.decode(document())
        png_named_pdf = document(data=base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 64).decode())
        for bad in (png_named_pdf, document(data="!!not base64!!")):
            with self.subTest(bad.data[:12]), self.assertRaises(DocumentRejected):
                documents.decode(bad)
        with patch.object(documents, "MAX_BYTES", 10), self.assertRaises(DocumentRejected):
            documents.decode(document())

    def test_transcription_sends_the_file_inline_and_labels_the_call(self):
        reply = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "  UTS: 28 Oktober\\nTugas 1 deadline 20 Oktober  "}]}}]}
        with patch.object(documents, "api_key", return_value="k"), patch.object(documents, "gemini_request", return_value=reply) as call:
            text = documents.transcribe(document())
        payload = call.call_args.args[0]
        self.assertEqual(payload["contents"][0]["parts"][0]["inlineData"]["mimeType"], "application/pdf")
        self.assertEqual(call.call_args.kwargs["purpose"], "document")
        self.assertTrue(text.startswith("UTS: 28 Oktober"))

    def test_text_becomes_a_source_and_a_capture_job(self):
        source = SimpleNamespace(id=uuid4())
        with patch.object(documents, "transcribe", return_value="Tugas 1 deadline 20 Oktober"), \
             patch.object(documents, "create_manual_source", return_value=SimpleNamespace(source=source)) as create, \
             patch.object(documents, "enqueue_job", return_value=SimpleNamespace(model_dump=lambda **_: {"id": "job"})) as enqueue:
            result = documents.ingest("session", document())
        self.assertEqual(create.call_args.args[2].title, "Document: silabus.pdf")
        self.assertEqual((enqueue.call_args.args[1].kind, enqueue.call_args.args[1].subject_id), ("source", source.id))
        self.assertEqual(result["source_id"], str(source.id))

    def test_word_and_markdown_briefs_are_read_without_a_model(self):
        markdown = document(filename="tugas.md", mime_type="text/markdown",
                            data=base64.b64encode("﻿# Tugas 2\r\n- Deadline 28 Oktober\r\n".encode()).decode())
        word = document(filename="tugas.docx", mime_type=documents.DOCX, data=base64.b64encode(docx(
            '<w:p><w:r><w:t>Tugas 2 Statistika</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>Deadline 28 Oktober</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Bobot</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>30%</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')).decode())
        with patch.object(documents, "gemini_request") as call:
            self.assertEqual(documents.transcribe(markdown), "# Tugas 2\n- Deadline 28 Oktober")
            self.assertEqual(documents.transcribe(word), "Tugas 2 Statistika\n- Deadline 28 Oktober\nBobot | 30%")
        call.assert_not_called()

    def test_broken_or_unsafe_word_and_text_files_are_refused(self):
        bad = [document(mime_type=documents.DOCX),  # a PDF named as Word
               document(mime_type=documents.DOCX, data=base64.b64encode(b"PK\x03\x04 not really a zip").decode()),
               document(mime_type=documents.DOCX, data=base64.b64encode(docx("", doctype=True)).decode()),
               document(mime_type="text/plain", data=base64.b64encode(b"\xff\xfe\x00b\x00a\x00d").decode())]
        for item in bad:
            with self.subTest(item.mime_type), self.assertRaises(DocumentRejected):
                documents.transcribe(item)

    def test_unreadable_or_empty_documents_get_clear_answers(self):
        with patch.object(documents, "transcribe", return_value=""), self.assertRaises(HTTPException) as empty:
            documents._ingest("session", document())
        self.assertEqual(empty.exception.status_code, 422)
        with patch.object(documents, "transcribe", side_effect=documents.DocumentUnreadable("x")), self.assertRaises(HTTPException) as down:
            documents._ingest("session", document())
        self.assertEqual(down.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
