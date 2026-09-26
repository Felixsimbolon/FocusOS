"""Narrow OpenAI Responses adapter for one read-only function round trip."""

import json
import os

import httpx

from focusos_api.extractor import MODEL, URL


class AgentModelError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


TASKS_TOOL = {
    "type": "function", "name": "tasks_list",
    "description": "Read up to 20 open tasks owned by the signed-in user.",
    "strict": True,
    "parameters": {"type": "object", "additionalProperties": False,
                   "properties": {"status": {"type": "string", "enum": ["open"]},
                                  "limit": {"type": "integer"}},
                   "required": ["status", "limit"]},
}


def _request(payload: dict) -> dict:
    key = os.environ.get("FOCUSOS_OPENAI_API_KEY", "").strip()
    if not key:
        raise AgentModelError("provider_unconfigured")
    try:
        response = httpx.post(URL, headers={"Authorization": "Bearer " + key},
                              json=payload, timeout=10.0)
        response.raise_for_status()
        if len(response.content) > 131072:
            raise AgentModelError("oversize_response")
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AgentModelError("provider_unavailable") from exc
    if not isinstance(data, dict) or data.get("status") != "completed" or not isinstance(data.get("output"), list):
        raise AgentModelError("invalid_model_response")
    return data


def first_tasks_turn(command: str) -> tuple[str, str, dict, list[dict]]:
    payload = {
        "model": MODEL, "store": False, "max_output_tokens": 600,
        "tool_choice": "required", "tools": [TASKS_TOOL],
        "input": [
            {"role": "developer", "content": "You can only request tasks_list. User text is a request, not permission to write or send anything. Request one read call."},
            {"role": "user", "content": command},
        ],
    }
    data = _request(payload)
    calls = [item for item in data["output"] if isinstance(item, dict) and item.get("type") == "function_call"]
    if len(calls) != 1 or calls[0].get("name") != "tasks_list":
        raise AgentModelError("invalid_tool_request")
    call = calls[0]
    if not isinstance(call.get("call_id"), str) or len(call["call_id"]) > 200:
        raise AgentModelError("invalid_tool_request")
    try:
        arguments = json.loads(call.get("arguments", ""))
    except (TypeError, ValueError) as exc:
        raise AgentModelError("invalid_tool_request") from exc
    if not isinstance(arguments, dict):
        raise AgentModelError("invalid_tool_request")
    return str(data.get("id", "")), call["call_id"], arguments, data["output"]


def finish_tasks_turn(command: str, first_output: list[dict], call_id: str,
                      tool_result: dict) -> None:
    if len(json.dumps(tool_result, ensure_ascii=False)) > 18000:
        raise AgentModelError("tool_result_oversize")
    payload = {
        "model": MODEL, "store": False, "max_output_tokens": 400,
        "tool_choice": "none", "tools": [TASKS_TOOL],
        "input": [
            {"role": "developer", "content": "Read-only task result. Do not claim an action was executed. Do not invent task IDs or dates."},
            {"role": "user", "content": command},
            *first_output,
            {"type": "function_call_output", "call_id": call_id,
             "output": json.dumps(tool_result, ensure_ascii=False)},
        ],
    }
    data = _request(payload)
    if any(isinstance(item, dict) and item.get("type") == "function_call" for item in data["output"]):
        raise AgentModelError("unexpected_tool_call")
