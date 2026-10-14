"""Model-call telemetry and the daily budget. Provider and database are simulated."""
import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from focusos_api import jobs, observability
from focusos_api.gemini import request
from focusos_api.main import app
from focusos_api.memory_embeddings import EmbeddingError, embed_text
from test_jobs import OWNER, claimed
from focusos_api.token_crypto import TokenCipher

SECRET_PROMPT = "Rahasia: gaji Budi 30 juta"
PAYLOAD = {"contents": [{"role": "user", "parts": [{"text": SECRET_PROMPT}]}]}
OK = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}],
      "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 80}}


def response(status=200, body=None):
    return httpx.Response(status, json=body if body is not None else OK,
                          request=httpx.Request("POST", "https://generativelanguage.googleapis.com/x"))


class Recorder:
    """Captures telemetry batches written through the caller's session."""
    def __init__(self, fail=False, today_tokens=0):
        self.batches, self.fail, self.today_tokens, self.usage_reads = [], fail, today_tokens, 0
    @contextmanager
    def scoped(self, token):
        if self.fail: raise RuntimeError("database down")
        client = MagicMock()
        def rpc(name, args):
            if name == "focusos_record_llm_calls": self.batches.append(args["p_calls"])
            if name == "focusos_llm_usage": self.usage_reads += 1
            data = {"today_tokens": self.today_tokens} if name == "focusos_llm_usage" else len(args.get("p_calls", []))
            return MagicMock(execute=MagicMock(return_value=MagicMock(data=data)))
        client.rpc.side_effect = rpc
        yield "owner", client


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.db = Recorder()
        for target in ("focusos_api.database.scoped_client",):
            started = patch(target, self.db.scoped); started.start(); self.addCleanup(started.stop)
        started = patch.dict(os.environ, {"GEMINI_API_KEY": "synthetic", "FOCUSOS_DAILY_TOKEN_BUDGET": "", "FOCUSOS_LLM_PRICES": ""})
        started.start(); self.addCleanup(started.stop)

    def call(self, outcome, purpose="intent"):
        with patch("focusos_api.gemini.httpx.post", side_effect=outcome if isinstance(outcome, Exception) else None,
                   return_value=None if isinstance(outcome, Exception) else outcome):
            return request(PAYLOAD, timeout=5, max_bytes=65536, purpose=purpose)

    def test_success_records_tokens_once_per_scope_without_prompt_text(self):
        with observability.bound("session-token"):
            self.call(response())
            self.call(response(), purpose="answer")
        self.assertEqual(len(self.db.batches), 1)
        calls = self.db.batches[0]
        self.assertEqual([(c["purpose"], c["status"], c["prompt_tokens"], c["output_tokens"]) for c in calls],
                         [("intent", "ok", 1200, 80), ("answer", "ok", 1200, 80)])
        self.assertEqual(calls[0]["trace_id"], calls[1]["trace_id"])
        self.assertNotIn(SECRET_PROMPT, json.dumps(calls))
        self.assertNotIn("session-token", json.dumps(calls))

    def test_rate_limit_and_timeout_are_distinct_outcomes(self):
        with observability.bound("session-token"):
            with self.assertRaises(httpx.HTTPStatusError): self.call(response(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}))
            with self.assertRaises(httpx.TimeoutException): self.call(httpx.ReadTimeout("slow"))
            with self.assertRaises(httpx.HTTPStatusError): self.call(response(500, {}))
        statuses = [(c["status"], c["http_status"]) for c in self.db.batches[0]]
        self.assertEqual(statuses, [("rate_limited", 429), ("timeout", None), ("error", 500)])

    def test_embeddings_are_recorded_with_their_purpose(self):
        embedding = httpx.Response(200, json={"embedding": {"values": [0.1] * 256}}, request=httpx.Request("POST", "https://x"))
        with observability.bound("session-token"), patch("focusos_api.memory_embeddings.httpx.post", return_value=embedding):
            embed_text("halaman web", purpose="embed_query")
        [call] = self.db.batches[0]
        self.assertEqual((call["operation"], call["purpose"], call["model"]), ("embed", "embed_query", "gemini-embedding-2"))
        with observability.bound("session-token"), patch("focusos_api.memory_embeddings.httpx.post", side_effect=httpx.ConnectError("down")):
            with self.assertRaises(EmbeddingError): embed_text("halaman web")
        self.assertEqual(self.db.batches[1][0]["status"], "error")

    def test_calls_outside_a_scope_and_flush_failures_never_break_requests(self):
        self.assertEqual(self.call(response()), OK)
        self.assertEqual(self.db.batches, [])
        self.db.fail = True
        with observability.bound("session-token"):
            self.assertEqual(self.call(response()), OK)

    def test_cost_is_estimated_only_for_configured_prices(self):
        prices = json.dumps({"gemini-3.5-flash-lite": {"input": 0.1, "output": 0.4}})
        with patch.dict(os.environ, {"FOCUSOS_LLM_PRICES": prices}), observability.bound("session-token"):
            self.call(response())
        self.assertAlmostEqual(self.db.batches[0][0]["cost_usd"], (1200 * 0.1 + 80 * 0.4) / 1_000_000)
        with observability.bound("session-token"):
            self.call(response())
        self.assertIsNone(self.db.batches[1][0]["cost_usd"])
        self.assertFalse(observability.cost_configured())

    def test_budget_blocks_calls_before_they_reach_the_provider(self):
        self.db.today_tokens = 4000
        with patch.dict(os.environ, {"FOCUSOS_DAILY_TOKEN_BUDGET": "5000"}), \
             patch("focusos_api.profiles.read_profile", return_value=None), observability.bound("session-token"):
            self.call(response())  # 4000 used: allowed, now 5280.
            with patch("focusos_api.gemini.httpx.post") as provider:
                with self.assertRaises(observability.BudgetExceeded):
                    request(PAYLOAD, timeout=5, max_bytes=65536)
                provider.assert_not_called()
        self.assertEqual(self.db.usage_reads, 1)

    def test_budget_is_off_by_default(self):
        self.db.today_tokens = 10**9
        with observability.bound("session-token"):
            self.assertEqual(self.call(response()), OK)
        self.assertEqual(self.db.usage_reads, 0)


class BoundaryTests(unittest.TestCase):
    def test_job_step_binds_one_trace_and_stops_on_budget(self):
        cipher = TokenCipher({1: b"k" * 32}, 1); row = claimed(cipher, uuid4())
        @contextmanager
        def auth(_): yield OWNER, MagicMock()
        seen = {}
        def step(token, job):
            seen["scope"] = observability._scope.get()
            raise observability.BudgetExceeded(10, 5)
        with patch.object(jobs, "_service_rpc", side_effect=[row, True]) as rpc, patch.object(jobs, "scoped_client", auth), \
             patch.object(jobs.TokenCipher, "from_environment", return_value=cipher), patch.object(jobs, "_step", side_effect=step), \
             patch.object(observability, "flush"):
            jobs.work_one()
        finish = rpc.call_args_list[-1].args[1]
        self.assertEqual(str(seen["scope"].trace_id), row["id"])
        self.assertEqual((finish["p_status"], finish["p_error"]), ("failed", "llm_budget_exceeded"))
        self.assertIn("usage limit", finish["p_result"]["message"])

    def test_http_requests_flush_their_calls_and_budget_maps_to_429(self):
        flushed = []
        def search(token, _):
            observability.record("answer_select", "generate", "m", 0.0, prompt_tokens=1, output_tokens=1)
            raise observability.BudgetExceeded(10, 5)
        with patch("focusos_api.main.search_memories", side_effect=search), \
             patch.object(observability, "flush", side_effect=lambda scope: flushed.append(list(scope.calls))):
            result = TestClient(app).post("/memories/search", json={"query": "web"}, headers={"Authorization": "Bearer session"})
        self.assertEqual(result.status_code, 429)
        self.assertEqual([call["purpose"] for call in flushed[0]], ["answer_select"])

    def test_worker_secret_is_never_used_as_a_session(self):
        with patch.dict(os.environ, {"FOCUSOS_WORKER_SECRET": "w" * 32}), \
             patch("focusos_api.job_routes.work_one", return_value={"state": "idle"}), patch.object(observability, "open_scope") as opened:
            TestClient(app).get("/internal/jobs/tick", headers={"Authorization": "Bearer " + "w" * 32})
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
