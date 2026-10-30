"""Claude as the generation provider, behind the same request/response shape as gemini.py.

Every model call in FocusOS builds a GenerateContent-style payload (system instruction, contents with text, inline
files or function calls, an optional JSON schema). When Claude is configured, gemini.request() sends that payload here:
it becomes one Messages API call and the answer comes back in the same shape, so callers, their validation and their
error handling stay as they are. Embeddings stay on Gemini; Claude has no embedding endpoint.

Configuration (backend environment only):
  ANTHROPIC_API_KEY   the key
  CLAUDE_MODEL        model or, on Microsoft Foundry, deployment name (e.g. claude-sonnet-5-5)
  ANTHROPIC_API_URL   optional: a Foundry URL (https://<resource>.services.ai.azure.com/...) or another base URL;
                      ANTHROPIC_FOUNDRY_RESOURCE may name the Foundry resource instead
  CLAUDE_EFFORT       optional, default "low": these calls are short and bounded, so thinking stays light
"""
import hashlib
import json
import os
import re
from functools import lru_cache
from urllib.parse import urlparse

import anthropic
import httpx

# Thinking shares the output budget; callers size max tokens for the answer alone.
THINKING_HEADROOM = 4096
EFFORTS = ("low", "medium", "high", "xhigh", "max")
UNSUPPORTED_SCHEMA_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength",
                           "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties",
                           "default", "title", "examples", "propertyOrdering")
SUPPORTED_FORMATS = {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}
# Word and text files are read without a model (documents.py); only PDFs and photos are sent inline.
FILE_TYPES = {"application/pdf": "document", "image/png": "image", "image/jpeg": "image",
              "image/webp": "image", "image/gif": "image"}


# Schemas whose compiled grammar Claude refused as too large; this process asks for them in the prompt instead.
_PROMPTED_SCHEMAS: set[str] = set()


class ClaudeRequestError(ValueError):
    """The payload cannot be expressed as a Messages request (a caller bug, never user data)."""


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def configured() -> bool:
    return bool(_env("ANTHROPIC_API_KEY") and _env("CLAUDE_MODEL"))


def api_key() -> str:
    return _env("ANTHROPIC_API_KEY")


def model() -> str:
    return _env("CLAUDE_MODEL")


def effort() -> str:
    value = _env("CLAUDE_EFFORT").lower()
    return value if value in EFFORTS else "low"


@lru_cache(maxsize=4)
def _client(key: str, url: str, resource: str) -> anthropic.Anthropic:
    # FocusOS jobs retry on their own schedule, so the SDK does not retry inside a bounded step.
    host = (urlparse(url).hostname or "") if url else ""
    if host.endswith(".services.ai.azure.com"):
        return anthropic.AnthropicFoundry(api_key=key, resource=host.split(".services.ai.azure.com")[0], max_retries=0)
    if resource:
        return anthropic.AnthropicFoundry(api_key=key, resource=resource, max_retries=0)
    if url:
        return anthropic.Anthropic(api_key=key, base_url=url, max_retries=0)
    return anthropic.Anthropic(api_key=key, max_retries=0)


def client() -> anthropic.Anthropic:
    return _client(api_key(), _env("ANTHROPIC_API_URL"), _env("ANTHROPIC_FOUNDRY_RESOURCE"))


def clean_schema(node):
    """Claude's structured outputs take a JSON Schema subset: strip constraints it rejects (the callers' Pydantic
    models still enforce them) and close every object."""
    if isinstance(node, list):
        return [clean_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    result = {}
    for key, value in node.items():
        if key in UNSUPPORTED_SCHEMA_KEYS:
            continue
        if key == "format" and value not in SUPPORTED_FORMATS:
            continue
        if key in ("properties", "$defs", "definitions"):
            result[key] = {name: clean_schema(child) for name, child in value.items()}
        else:
            result[key] = clean_schema(value)
    types = result.get("type")
    if types == "object" or (isinstance(types, list) and "object" in types) or "properties" in result:
        result["additionalProperties"] = False
    return result


def _schema(generation: dict) -> dict | None:
    response_format = generation.get("responseFormat")
    if isinstance(response_format, dict):
        text = response_format.get("text") or {}
        if text.get("schema") is not None: return text["schema"]
    if generation.get("responseSchema") is not None: return generation["responseSchema"]
    if generation.get("responseJsonSchema") is not None: return generation["responseJsonSchema"]
    return None


def _content(part: dict) -> list[dict]:
    """One GenerateContent part as Messages content blocks."""
    if isinstance(part.get("text"), str):
        return [] if part.get("thought") is True else [{"type": "text", "text": part["text"]}] if part["text"] else []
    if isinstance(part.get("inlineData"), dict):
        media, data = part["inlineData"].get("mimeType"), part["inlineData"].get("data")
        kind = FILE_TYPES.get(media)
        if kind is None or not isinstance(data, str): raise ClaudeRequestError("unsupported_inline_file")
        return [{"type": kind, "source": {"type": "base64", "media_type": media, "data": data}}]
    if isinstance(part.get("functionCall"), dict):
        call = part["functionCall"]
        return [{"type": "tool_use", "id": call.get("id") or "call", "name": call["name"], "input": call.get("args") or {}}]
    if isinstance(part.get("functionResponse"), dict):
        answer = part["functionResponse"]
        return [{"type": "tool_result", "tool_use_id": answer.get("id") or "call",
                 "content": json.dumps(answer.get("response"), ensure_ascii=False)}]
    raise ClaudeRequestError("unsupported_part")


def _messages(contents: list[dict]) -> list[dict]:
    messages = []
    for turn in contents:
        role = "assistant" if turn.get("role") == "model" else "user"
        parts = turn.get("parts") or []
        # A model turn this module produced carries Claude's own blocks (thinking signatures included): replay them unchanged.
        saved = next((part["claude_content"] for part in parts if isinstance(part.get("claude_content"), list)), None)
        blocks = saved if role == "assistant" and saved is not None else [block for part in parts for block in _content(part)]
        if blocks: messages.append({"role": role, "content": blocks})
    return messages


def _schema_key(schema: dict) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()


def build(payload: dict, prompted: bool = False) -> dict:
    """The Messages request for one GenerateContent payload. prompted: give the JSON schema as an instruction instead
    of a structured-output constraint (for schemas whose grammar Claude refuses as too large)."""
    generation = payload.get("generationConfig") or {}
    system = "\n\n".join(part["text"] for part in (payload.get("systemInstruction") or {}).get("parts", [])
                         if isinstance(part.get("text"), str))
    request = {"model": model(), "messages": _messages(payload.get("contents") or []),
               "max_tokens": int(generation.get("maxOutputTokens") or 2048) + THINKING_HEADROOM,
               "output_config": {"effort": effort()}}
    schema = _schema(generation)
    if schema is not None and (prompted or _schema_key(schema) in _PROMPTED_SCHEMAS):
        rule = ("Return only one JSON object, with no prose and no code fences, that validates against this JSON Schema:\n"
                + json.dumps(clean_schema(schema), ensure_ascii=False, separators=(",", ":")))
        system = f"{system}\n\n{rule}" if system else rule
    elif schema is not None:
        request["output_config"]["format"] = {"type": "json_schema", "schema": clean_schema(schema)}
    declarations = [item for tool in payload.get("tools") or [] for item in tool.get("functionDeclarations") or []]
    if declarations:
        request["tools"] = [{"name": item["name"], "description": item.get("description", ""), "strict": True,
                             "input_schema": clean_schema(item.get("parametersJsonSchema") or item.get("parameters") or {"type": "object"})}
                            for item in declarations]
        mode = ((payload.get("toolConfig") or {}).get("functionCallingConfig") or {}).get("mode", "AUTO")
        if mode == "NONE":
            request["tool_choice"] = {"type": "none"}
        else:
            # Current models refuse forced tool use; ask for the call instead (callers check exactly one was made).
            request["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
            if mode == "ANY":
                names = ", ".join(item["name"] for item in declarations)
                system = f"{system}\n\nAnswer only by calling {names}; write no text." if system else f"Answer only by calling {names}."
    if system: request["system"] = system
    return request


def _translated(exc: anthropic.APIError) -> httpx.HTTPError:
    """The SDK's error as the httpx error callers and telemetry already understand (status, timeout, transport)."""
    if isinstance(exc, anthropic.APITimeoutError):
        return httpx.ReadTimeout("Claude request timed out", request=exc.request)
    if isinstance(exc, anthropic.APIStatusError):
        return httpx.HTTPStatusError(f"Claude returned {exc.status_code}", request=exc.response.request, response=exc.response)
    if isinstance(exc, anthropic.APIConnectionError):
        return httpx.ConnectError("Claude connection failed", request=exc.request)
    return httpx.HTTPError("Claude request failed")


def generate(payload: dict, timeout: float) -> dict:
    """Send one payload; return a GenerateContent-shaped answer: one candidate whose parts hold the text and any
    function call, with finishReason and usageMetadata as Gemini reports them."""
    request = build(payload)
    try:
        try:
            response = client().with_options(timeout=timeout).messages.create(**request)
        except anthropic.BadRequestError as exc:
            # The API names no error code for this; its message is the only signal. Retry once with the schema in the prompt:
            # the callers' Pydantic validation and repair attempts still hold the answer to it.
            schema = _schema(payload.get("generationConfig") or {})
            if schema is None or "format" not in request.get("output_config", {}) or "grammar" not in str(exc.message).lower():
                raise
            _PROMPTED_SCHEMAS.add(_schema_key(schema))
            response = client().with_options(timeout=timeout).messages.create(**build(payload, prompted=True))
    except anthropic.APIError as exc:
        raise _translated(exc) from exc
    finish = {"end_turn": "STOP", "tool_use": "STOP", "stop_sequence": "STOP", "max_tokens": "MAX_TOKENS",
              "refusal": "SAFETY"}.get(response.stop_reason or "", "OTHER")
    calls = [{"functionCall": {"id": block.id, "name": block.name, "args": block.input}}
             for block in response.content if block.type == "tool_use"]
    text = "".join(block.text for block in response.content if block.type == "text")
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", text, flags=re.S)
    if fenced: text = fenced.group(1)
    parts = [*calls, {"thought": True, "claude_content": [block.to_dict() for block in response.content]}] if calls \
        else [{"text": text}]
    return {"candidates": [{"finishReason": finish, "content": {"role": "model", "parts": parts}}],
            "usageMetadata": {"promptTokenCount": response.usage.input_tokens, "candidatesTokenCount": response.usage.output_tokens},
            "modelVersion": response.model}
