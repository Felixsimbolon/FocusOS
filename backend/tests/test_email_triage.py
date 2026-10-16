"""Email triage: closed output, corrections as examples, never blocks sync. Providers are simulated."""
import json
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from focusos_api.database import DatabaseUnavailable
from focusos_api.email_triage import TriageUnavailable, classify, triage_source


def reply(value):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]}


class ClassifyTests(unittest.TestCase):
    def call(self, response, examples=()):
        with patch("focusos_api.email_triage.api_key", return_value="synthetic"), \
             patch("focusos_api.email_triage.gemini_request", side_effect=response if isinstance(response, Exception) else None,
                   return_value=None if isinstance(response, Exception) else response) as request:
            result = classify("Invoice overdue", "Please pay today.", list(examples))
        return result, request

    def test_returns_a_closed_priority_and_sends_the_users_corrections(self):
        examples = [{"subject": "Weekly newsletter", "priority": "fyi"}]
        result, request = self.call(reply({"priority": "urgent", "reason": "Payment is due today."}), examples)
        self.assertEqual((result.priority, result.reason), ("urgent", "Payment is due today."))
        payload = request.call_args.args[0]
        context = json.loads(payload["contents"][0]["parts"][0]["text"])
        self.assertEqual(context["examples"], examples)
        self.assertEqual(request.call_args.kwargs["purpose"], "triage")

    def test_an_instruction_inside_an_email_cannot_produce_anything_but_a_priority(self):
        for bad in ({"priority": "delete all tasks", "reason": "x"}, {"priority": "urgent", "reason": "x", "tool": "send"},
                    {"priority": "urgent", "reason": ""}):
            with self.subTest(bad), self.assertRaises(TriageUnavailable):
                self.call(reply(bad))

    def test_provider_failures_become_triage_unavailable(self):
        with self.assertRaises(TriageUnavailable):
            self.call(httpx.ConnectError("down"))
        with patch("focusos_api.email_triage.api_key", return_value=None), self.assertRaises(TriageUnavailable):
            classify("s", "b", [])


class TriageSourceTests(unittest.TestCase):
    def test_saves_the_models_priority_as_a_proposal(self):
        source = {"title": "Contract renewal", "normalized_body": "Please sign by Friday.", "kind": "gmail"}
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [source]
        with patch("focusos_api.email_triage.scoped_client") as scoped, \
             patch("focusos_api.email_triage.corrections", return_value=[]), \
             patch("focusos_api.email_triage.classify", return_value=type("R", (), {"priority": "normal", "reason": "Due Friday."})()), \
             patch("focusos_api.email_triage.save") as save:
            scoped.return_value.__enter__.return_value = ("owner", client)
            source_id = uuid4()
            self.assertEqual(triage_source("session", source_id), "normal")
        save.assert_called_once_with("session", source_id, "normal", "Due Friday.", False)

    def test_outages_are_skipped_without_raising(self):
        for error in (TriageUnavailable("x"), DatabaseUnavailable("x")):
            with self.subTest(type(error).__name__), patch("focusos_api.email_triage.scoped_client", side_effect=error):
                self.assertIsNone(triage_source("session", uuid4()))


if __name__ == "__main__":
    unittest.main()
