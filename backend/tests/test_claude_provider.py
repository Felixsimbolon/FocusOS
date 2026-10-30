"""Claude behind the GenerateContent shape. The Messages API is simulated; no request leaves the test."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx

from focusos_api import agent_model, claude, gemini
from focusos_api.gemini import output_text, parts, structured_payload

ENV = {"ANTHROPIC_API_KEY": "synthetic", "CLAUDE_MODEL": "claude-sonnet-5-5",
       "ANTHROPIC_API_URL": "https://example-res.services.ai.azure.com/api/projects/example", "CLAUDE_EFFORT": "", "ANTHROPIC_FOUNDRY_RESOURCE": ""}


def block(kind, **fields):
    value = SimpleNamespace(type=kind, **fields)
    value.to_dict = lambda: {"type": kind, **fields}
    return value


def message(*content, stop="end_turn"):
    return SimpleNamespace(content=list(content), stop_reason=stop, model="claude-sonnet-5-5",
                           usage=SimpleNamespace(input_tokens=120, output_tokens=40))


class FakeClient:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []
        self.messages = SimpleNamespace(create=self.create)

    def with_options(self, **_):
        return self

    def create(self, **request):
        self.requests.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception): raise result
        return result


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV); self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_a_structured_payload_becomes_one_messages_request(self):
        schema = {"type": "object", "properties": {"title": {"type": "string", "maxLength": 80},
                  "minutes": {"type": "integer", "minimum": 15}, "day": {"type": "string", "format": "date"},
                  "items": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {"x": {"type": "string"}}}}},
                  "required": ["title"]}
        request = claude.build(structured_payload("Extract.", "tugas besok", schema, 2400))
        self.assertEqual((request["model"], request["system"], request["max_tokens"]), ("claude-sonnet-5-5", "Extract.", 2400 + claude.THINKING_HEADROOM))
        self.assertEqual(request["messages"], [{"role": "user", "content": [{"type": "text", "text": "tugas besok"}]}])
        sent = request["output_config"]["format"]["schema"]
        self.assertEqual(request["output_config"]["effort"], "low")
        # Constraints Claude rejects are stripped (Pydantic still enforces them); every object is closed.
        self.assertNotIn("maxLength", json.dumps(sent)); self.assertNotIn("minimum", json.dumps(sent)); self.assertNotIn("minItems", json.dumps(sent))
        self.assertEqual(sent["properties"]["day"]["format"], "date")
        self.assertFalse(sent["additionalProperties"]); self.assertFalse(sent["properties"]["items"]["items"]["additionalProperties"])

    def test_files_go_as_document_and_image_blocks_before_the_text(self):
        payload = {"contents": [{"role": "user", "parts": [{"inlineData": {"mimeType": "application/pdf", "data": "JVBERg=="}},
                                                          {"inlineData": {"mimeType": "image/png", "data": "iVBO"}}, {"text": "File name: a.pdf"}]}],
                   "generationConfig": {"maxOutputTokens": 8000}}
        content = claude.build(payload)["messages"][0]["content"]
        self.assertEqual([item["type"] for item in content], ["document", "image", "text"])
        self.assertEqual(content[0]["source"], {"type": "base64", "media_type": "application/pdf", "data": "JVBERg=="})
        self.assertNotIn("format", claude.build(payload)["output_config"])
        with self.assertRaises(claude.ClaudeRequestError):
            claude.build({"contents": [{"role": "user", "parts": [{"inlineData": {"mimeType": "video/mp4", "data": "x"}}]}]})

    def test_a_forced_function_call_becomes_an_asked_for_strict_tool(self):
        request = claude.build({"systemInstruction": {"parts": [{"text": agent_model.SYSTEM}]}, "contents": [{"role": "user", "parts": [{"text": "tasks?"}]}],
                                "tools": [{"functionDeclarations": [agent_model.TASKS_TOOL]}],
                                "toolConfig": {"functionCallingConfig": {"mode": "ANY"}}, "generationConfig": {"maxOutputTokens": 600}})
        self.assertEqual(request["tool_choice"], {"type": "auto", "disable_parallel_tool_use": True})
        self.assertTrue(request["tools"][0]["strict"]); self.assertFalse(request["tools"][0]["input_schema"]["additionalProperties"])
        self.assertIn("calling tasks_list", request["system"])

    def test_foundry_resource_comes_from_the_url_and_other_urls_are_base_urls(self):
        claude._client.cache_clear()
        with patch.object(claude.anthropic, "AnthropicFoundry") as foundry:
            claude.client()
        self.assertEqual(foundry.call_args.kwargs["resource"], "example-res")
        claude._client.cache_clear()
        with patch.dict(os.environ, {"ANTHROPIC_API_URL": "https://proxy.example.test/"}), patch.object(claude.anthropic, "Anthropic") as first_party:
            claude.client()
        self.assertEqual(first_party.call_args.kwargs["base_url"], "https://proxy.example.test/")
        claude._client.cache_clear()


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV); self.env.start()

    def tearDown(self):
        self.env.stop()

    def run_with(self, *responses):
        fake = FakeClient(*responses)
        return fake, patch.object(claude, "client", return_value=fake)

    def test_text_comes_back_in_the_shape_callers_read(self):
        fake, patched = self.run_with(message(block("thinking", thinking="", signature="sig"), block("text", text='{"ok": true}')))
        with patched, patch.object(gemini.observability, "record") as record:
            data = gemini.request(structured_payload("s", "u", {"type": "object"}, 100), timeout=20, max_bytes=65536, purpose="intent")
        self.assertEqual(json.loads(output_text(data)), {"ok": True})
        self.assertEqual(gemini.usage(data), (120, 40))
        self.assertEqual(record.call_args.kwargs["prompt_tokens"], 120)

    def test_refusals_truncation_and_oversize_answers_are_reported_as_before(self):
        for stop, code in (("refusal", "refused"), ("max_tokens", "incomplete")):
            fake, patched = self.run_with(message(block("text", text="{}"), stop=stop))
            with self.subTest(stop=stop), patched, patch.object(gemini.observability, "record"), self.assertRaises(gemini.GeminiResponseError) as raised:
                output_text(gemini.request(structured_payload("s", "u", {}, 100), 20, 65536))
            self.assertEqual(raised.exception.code, code)
        fake, patched = self.run_with(message(block("text", text="x" * 500)))
        with patched, patch.object(gemini.observability, "record"), self.assertRaises(gemini.GeminiResponseError) as raised:
            gemini.request(structured_payload("s", "u", {}, 100), 20, max_bytes=100)
        self.assertEqual(raised.exception.code, "oversize_response")

    def test_a_schema_too_large_to_compile_is_asked_for_in_the_prompt_once_then_remembered(self):
        request = httpx.Request("POST", "https://example.test/v1/messages")
        too_large = anthropic.BadRequestError("The compiled grammar is too large, which would cause performance issues.",
                                              response=httpx.Response(400, request=request), body=None)
        schema = {"type": "object", "properties": {"big": {"type": "string"}}}
        fake, patched = self.run_with(too_large, message(block("text", text='```json\n{"big": "ok"}\n```')), message(block("text", text='{"big": "again"}')))
        with patched, patch.object(gemini.observability, "record"):
            first = output_text(gemini.request(structured_payload("Extract.", "u", schema, 100), 20, 65536))
            second = output_text(gemini.request(structured_payload("Extract.", "u", schema, 100), 20, 65536))
        self.assertEqual((json.loads(first), json.loads(second)), ({"big": "ok"}, {"big": "again"}))
        self.assertIn("format", fake.requests[0]["output_config"])
        for retried in fake.requests[1:]:
            self.assertNotIn("format", retried["output_config"]); self.assertIn("JSON Schema", retried["system"])
        claude._PROMPTED_SCHEMAS.clear()

    def test_provider_errors_become_the_httpx_errors_callers_handle(self):
        request = httpx.Request("POST", "https://example.test/v1/messages")
        limited = anthropic.RateLimitError("slow down", response=httpx.Response(429, request=request), body=None)
        for error, expected in ((limited, httpx.HTTPStatusError), (anthropic.APITimeoutError(request=request), httpx.TimeoutException),
                                (anthropic.APIConnectionError(request=request), httpx.TransportError)):
            fake, patched = self.run_with(error)
            with self.subTest(error=type(error).__name__), patched, patch.object(gemini.observability, "record") as record, self.assertRaises(expected) as raised:
                gemini.request(structured_payload("s", "u", {}, 100), 20, 65536, purpose="extraction")
            self.assertIs(record.call_args.args[4], raised.exception)
        self.assertEqual(gemini.observability._status(httpx.HTTPStatusError("x", request=request, response=httpx.Response(429, request=request))), ("rate_limited", 429))

    def test_the_read_only_agent_round_trip_replays_claudes_own_blocks(self):
        first = message(block("thinking", thinking="", signature="sig"), block("text", text="Checking."),
                        block("tool_use", id="toolu_1", name="tasks_list", input={"status": "open", "limit": 20}), stop="tool_use")
        second = message(block("text", text="You have 2 open tasks."))
        fake, patched = self.run_with(first, second)
        with patched, patch.object(gemini.observability, "record"):
            _, call_id, arguments, output = agent_model.first_tasks_turn("apa saja task saya?")
            agent_model.finish_tasks_turn("apa saja task saya?", output, call_id, {"tasks": [{"title": "A"}, {"title": "B"}]})
        self.assertEqual((call_id, arguments), ("toolu_1", {"status": "open", "limit": 20}))
        replay = fake.requests[1]["messages"]
        self.assertEqual([item["type"] for item in replay[1]["content"]], ["thinking", "text", "tool_use"])  # unchanged, signature included
        self.assertEqual(replay[2]["content"][0]["tool_use_id"], "toolu_1")
        self.assertEqual(fake.requests[1]["tool_choice"], {"type": "none"})

    def test_without_claude_settings_generation_stays_on_gemini_and_embeddings_always_do(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": "g"}):
            self.assertFalse(claude.configured())
            self.assertEqual(gemini.api_key(), "g")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "g"}):
            self.assertEqual((gemini.api_key(), gemini.gemini_key()), ("synthetic", "g"))
            from focusos_api import memory_embeddings
            self.assertIs(memory_embeddings.api_key, gemini.gemini_key)


if __name__ == "__main__":
    unittest.main()
