"""Small Gemini GenerateContent adapter shared by bounded model calls."""
import logging
import re
import os

import httpx

MODEL = "gemini-3.5-flash-lite"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
logger = logging.getLogger(__name__)


class GeminiResponseError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip()


def url(model: str = MODEL, method: str = "generateContent") -> str:
    return f"{BASE_URL}/{model}:{method}"


def request(payload: dict, timeout: float, max_bytes: int) -> dict:
    response = httpx.post(
        url(), headers={"x-goog-api-key": api_key()}, json=payload, timeout=timeout
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        provider_status = reason = field = None
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict):
                provider_status = error.get("status")
                for detail in error.get("details", []):
                    if not isinstance(detail, dict):
                        continue
                    candidate = detail.get("reason")
                    if isinstance(candidate, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", candidate):
                        reason = candidate
                    violations = detail.get("fieldViolations")
                    if isinstance(violations, list):
                        for violation in violations:
                            candidate = violation.get("field") if isinstance(violation, dict) else None
                            if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_.\[\]]{1,160}", candidate):
                                field = candidate
        except (ValueError, AttributeError, TypeError):
            pass
        logger.warning(
            "Gemini request rejected: http_status=%s provider_status=%s reason=%s field=%s model=%s",
            response.status_code, provider_status or "unknown",
            reason or "unknown", field or "unknown", MODEL,
        )
        raise
    except httpx.HTTPError as exc:
        logger.warning(
            "Gemini transport failed: error_type=%s model=%s",
            type(exc).__name__, MODEL,
        )
        raise
    if len(response.content) > max_bytes:
        raise GeminiResponseError("oversize_response")
    data = response.json()
    if not isinstance(data, dict):
        raise GeminiResponseError("malformed")
    return data


def parts(data: dict) -> list[dict]:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
        feedback = data.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            raise GeminiResponseError("refused")
        raise GeminiResponseError("malformed")
    candidate = candidates[0]
    reason = candidate.get("finishReason")
    if reason in ("SAFETY", "PROHIBITED_CONTENT", "SPII", "BLOCKLIST", "MODEL_ARMOR"):
        raise GeminiResponseError("refused")
    if reason != "STOP":
        raise GeminiResponseError("incomplete")
    content = candidate.get("content")
    result = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(result, list) or not all(isinstance(part, dict) for part in result):
        raise GeminiResponseError("malformed")
    return result


def output_text(data: dict) -> str:
    text_parts = [part["text"] for part in parts(data) if isinstance(part.get("text"), str)]
    if len(text_parts) != 1:
        raise GeminiResponseError("malformed")
    return text_parts[0]


def usage(data: dict) -> tuple[int | None, int | None]:
    counts = data.get("usageMetadata") or {}
    prompt = counts.get("promptTokenCount")
    output = counts.get("candidatesTokenCount")
    return prompt if isinstance(prompt, int) else None, output if isinstance(output, int) else None


def structured_payload(system: str, user: str, schema: dict, max_tokens: int) -> dict:
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": schema}},
        },
    }

