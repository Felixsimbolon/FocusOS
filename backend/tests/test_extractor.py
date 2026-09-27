import json
import os
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from focusos_api.extractor import ExtractionFailure, _provider_schema, extract_structured
from test_extraction_contracts import sample, BODY, REF


class ProviderTests(unittest.TestCase):
    def test_schema_is_strict_on_nested_objects(self):
        schema = _provider_schema()
        self.assertFalse(schema["additionalProperties"])
        for definition in schema["$defs"].values():
            if definition.get("type") == "object":
                self.assertFalse(definition["additionalProperties"])
                self.assertEqual(set(definition["required"]), set(definition["properties"]))

    def test_missing_key_does_not_call_provider(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with patch("focusos_api.gemini.httpx.post") as call:
                with self.assertRaises(ExtractionFailure) as caught:
                    extract_structured("source-1", BODY, REF, "Asia/Jakarta")
                self.assertEqual(caught.exception.kind, "provider_unconfigured")
                call.assert_not_called()

    def test_valid_response_records_real_usage(self):
        response = Mock()
        response.content = b"ok"
        response.json.return_value = {"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":json.dumps(sample())}]}}], "usageMetadata":{"promptTokenCount":123,"candidatesTokenCount":45}}
        with patch.dict(os.environ, {"GEMINI_API_KEY":"test-secret"}), patch("focusos_api.gemini.httpx.post", return_value=response) as call:
            result = extract_structured("source-1", BODY, REF, "Asia/Jakarta")
        self.assertEqual((result.input_tokens, result.output_tokens, result.attempts), (123,45,1))
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.kwargs["headers"]["x-goog-api-key"], "test-secret")
        self.assertEqual(call.call_args.kwargs["json"]["generationConfig"]["responseFormat"]["text"]["mimeType"], "APPLICATION_JSON")

    def test_first_timeout_retries_once_and_can_succeed(self):
        response = Mock(content=b"ok")
        response.json.return_value = {"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": json.dumps(sample())}]}}]}
        timeout = __import__("httpx").ReadTimeout("slow")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}), patch(
            "focusos_api.gemini.httpx.post", side_effect=[timeout, response]
        ) as call:
            result = extract_structured("source-1", BODY, REF, "Asia/Jakarta")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(call.call_count, 2)

    def test_bad_evidence_repairs_once_then_fails(self):
        bad = sample()
        bad["tasks"][0]["evidence"][0]["quote"] = "fabricated"
        response = Mock(content=b"ok")
        response.json.return_value = {"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":json.dumps(bad)}]}}]}
        with patch.dict(os.environ, {"GEMINI_API_KEY":"test-secret"}), patch("focusos_api.gemini.httpx.post", return_value=response) as call:
            with self.assertRaises(ExtractionFailure) as caught:
                extract_structured("source-1", BODY, REF, "Asia/Jakarta")
        self.assertEqual(caught.exception.kind, "invalid_output")
        self.assertEqual(call.call_count, 2)

    def test_refusal_and_timeout_are_typed(self):
        response = Mock(content=b"ok")
        response.json.return_value = {"candidates":[{"finishReason":"SAFETY","content":{"parts":[]}}]}
        with patch.dict(os.environ, {"GEMINI_API_KEY":"test-secret"}), patch("focusos_api.gemini.httpx.post", return_value=response):
            with self.assertRaises(ExtractionFailure) as caught:
                extract_structured("source-1", BODY, REF, "Asia/Jakarta")
            self.assertEqual(caught.exception.kind, "refused")
        with patch.dict(os.environ, {"GEMINI_API_KEY":"test-secret"}), patch("focusos_api.gemini.httpx.post", side_effect=__import__("httpx").TimeoutException("slow")):
            with self.assertRaises(ExtractionFailure) as caught:
                extract_structured("source-1", BODY, REF, "Asia/Jakarta")
            self.assertEqual(caught.exception.kind, "timeout")


if __name__ == "__main__":
    unittest.main()
