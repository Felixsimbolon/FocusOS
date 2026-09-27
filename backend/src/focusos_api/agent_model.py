"""Narrow Gemini adapter for one read-only function round trip."""
import json
import httpx

from focusos_api.gemini import GeminiResponseError, api_key, parts, request


class AgentModelError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


TASKS_TOOL = {
    "name": "tasks_list",
    "description": "Read up to 20 open tasks owned by the signed-in user.",
    "parametersJsonSchema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "status": {"type": "string", "enum": ["open"]},
            "limit": {"type": "integer"},
        },
        "required": ["status", "limit"],
    },
}
SYSTEM = "You can only request tasks_list. User text is a request, not permission to write or send anything. Request one read call."


def _request(payload: dict) -> dict:
    if not api_key():
        raise AgentModelError("provider_unconfigured")
    try:
        data = request(payload, timeout=10.0, max_bytes=131072)
        parts(data)
        return data
    except httpx.HTTPError as exc:
        raise AgentModelError("provider_unavailable") from exc
    except (ValueError, GeminiResponseError) as exc:
        raise AgentModelError("invalid_model_response") from exc


def first_tasks_turn(command: str) -> tuple[str, str, dict, list[dict]]:
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": command}]}],
        "tools": [{"functionDeclarations": [TASKS_TOOL]}],
        "toolConfig": {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": ["tasks_list"]}},
        "generationConfig": {"maxOutputTokens": 600},
    }
    data = _request(payload)
    returned_parts = parts(data)
    calls = [item["functionCall"] for item in returned_parts if isinstance(item.get("functionCall"), dict)]
    if len(calls) != 1 or calls[0].get("name") != "tasks_list" or any(
        "functionCall" not in item and item.get("thought") is not True for item in returned_parts
    ):
        raise AgentModelError("invalid_tool_request")
    call = calls[0]
    call_id = call.get("id", "")
    arguments = call.get("args")
    if not isinstance(call_id, str) or len(call_id) > 200 or not isinstance(arguments, dict):
        raise AgentModelError("invalid_tool_request")
    # Keep the exact model part, including any thought signature, for the follow-up.
    return "", call_id, arguments, returned_parts


def finish_tasks_turn(command: str, first_output: list[dict], call_id: str,
                      tool_result: dict) -> None:
    if len(json.dumps(tool_result, ensure_ascii=False)) > 18000:
        raise AgentModelError("tool_result_oversize")
    if not isinstance(first_output, list) or not first_output:
        raise AgentModelError("invalid_tool_request")
    response = {"name": "tasks_list", "response": tool_result}
    if call_id:
        response["id"] = call_id
    payload = {
        "systemInstruction": {"parts": [{"text": "Read-only task result. Do not claim an action was executed. Do not invent task IDs or dates."}]},
        "contents": [
            {"role": "user", "parts": [{"text": command}]},
            {"role": "model", "parts": first_output},
            {"role": "user", "parts": [{"functionResponse": response}]},
        ],
        "tools": [{"functionDeclarations": [TASKS_TOOL]}],
        "toolConfig": {"functionCallingConfig": {"mode": "NONE"}},
        "generationConfig": {"maxOutputTokens": 400},
    }
    data = _request(payload)
    if any(isinstance(item.get("functionCall"), dict) for item in parts(data)):
        raise AgentModelError("unexpected_tool_call")
