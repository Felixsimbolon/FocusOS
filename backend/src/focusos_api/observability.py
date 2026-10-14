"""Model-call telemetry and a per-user daily token budget.

A scope binds the caller's session to the current context (one job step or one
HTTP request). Every model call inside it is timed and buffered, then written in
one batch when the scope ends. Only counts, timing and outcome are recorded,
never prompt or response text. Telemetry failures are logged and swallowed: they
must never break the user's request.
"""
import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator
from uuid import UUID, uuid4

import httpx

logger = logging.getLogger("focusos.telemetry")
MAX_BUFFER = 50


class BudgetExceeded(Exception):
    """The user's model token budget for today is used up."""
    def __init__(self, used: int, limit: int):
        self.used, self.limit = used, limit
        super().__init__("llm_budget_exceeded")


@dataclass
class Scope:
    token: str
    trace_id: UUID
    job_id: UUID | None = None
    calls: list[dict] = field(default_factory=list)
    tokens_used: int | None = None  # Today's usage, read once per scope when a budget is set.


_scope: ContextVar[Scope | None] = ContextVar("focusos_telemetry_scope", default=None)


def _prices() -> dict:
    """USD per million tokens: {"model": {"input": x, "output": y}}. Unset means unknown cost."""
    try:
        value = json.loads(os.environ.get("FOCUSOS_LLM_PRICES", "") or "{}")
    except ValueError:
        logger.warning("FOCUSOS_LLM_PRICES is not valid JSON; cost is not estimated")
        return {}
    return value if isinstance(value, dict) else {}


def cost_configured() -> bool:
    return bool(_prices())


def daily_token_budget() -> int:
    try:
        return max(0, int(os.environ.get("FOCUSOS_DAILY_TOKEN_BUDGET", "0") or 0))
    except ValueError:
        return 0


def estimate_cost(model: str, prompt_tokens: int | None, output_tokens: int | None) -> float | None:
    price = _prices().get(model)
    if not isinstance(price, dict) or prompt_tokens is None:
        return None
    try:
        cost = (prompt_tokens * float(price.get("input", 0)) + (output_tokens or 0) * float(price.get("output", 0))) / 1_000_000
    except (TypeError, ValueError):
        return None
    return round(cost, 6)


def _status(error: BaseException | None) -> tuple[str, int | None]:
    if error is None:
        return "ok", 200
    if isinstance(error, httpx.TimeoutException):
        return "timeout", None
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        return ("rate_limited" if code == 429 else "error"), code
    return "error", None


def record(purpose: str, operation: str, model: str, started: float, error: BaseException | None = None,
           prompt_tokens: int | None = None, output_tokens: int | None = None) -> None:
    status, http_status = _status(error)
    latency = min(600000, max(0, int((time.monotonic() - started) * 1000)))
    # Structured, content-free log line for platform logs even without a scope.
    logger.info("llm_call purpose=%s operation=%s model=%s status=%s http=%s latency_ms=%s prompt_tokens=%s output_tokens=%s",
                purpose, operation, model, status, http_status, latency, prompt_tokens, output_tokens)
    scope = _scope.get()
    if scope is None:
        return
    scope.calls.append({
        "trace_id": str(scope.trace_id), "job_id": str(scope.job_id) if scope.job_id else None,
        "purpose": purpose, "operation": operation, "model": model, "status": status, "http_status": http_status,
        "prompt_tokens": prompt_tokens, "output_tokens": output_tokens, "latency_ms": latency,
        "cost_usd": estimate_cost(model, prompt_tokens, output_tokens),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    if scope.tokens_used is not None:
        scope.tokens_used += (prompt_tokens or 0) + (output_tokens or 0)
    if len(scope.calls) >= MAX_BUFFER:
        flush(scope)


def check_budget() -> None:
    """Raise before a model call when today's tokens already reach the configured budget."""
    limit, scope = daily_token_budget(), _scope.get()
    if not limit or scope is None:
        return
    if scope.tokens_used is None:
        scope.tokens_used = _today_tokens(scope.token)
    if scope.tokens_used >= limit:
        raise BudgetExceeded(scope.tokens_used, limit)


def _today_tokens(token: str) -> int:
    from focusos_api.database import DatabaseUnavailable, scoped_client
    from focusos_api.profiles import read_profile
    try:
        profile = read_profile(token)
        with scoped_client(token) as (_, client):
            usage = client.rpc("focusos_llm_usage", {"p_days": 1, "p_timezone": profile.timezone if profile else "UTC"}).execute().data
        return int((usage or {}).get("today_tokens") or 0)
    except (DatabaseUnavailable, ValueError, TypeError, AttributeError):
        # An unreadable budget must not block work; the call is still recorded.
        logger.warning("Daily token usage unavailable; budget not enforced for this step")
        return 0


def flush(scope: Scope) -> None:
    calls, scope.calls = scope.calls, []
    if not calls:
        return
    from focusos_api.database import scoped_client
    try:
        with scoped_client(scope.token) as (_, client):
            client.rpc("focusos_record_llm_calls", {"p_calls": calls}).execute()
    except Exception as exc:  # noqa: BLE001 - telemetry must never fail the request.
        logger.warning("Telemetry flush failed: error=%s calls=%s", type(exc).__name__, len(calls))


def open_scope(token: str, job_id: UUID | str | None = None):
    job = UUID(str(job_id)) if job_id else None
    scope = Scope(token=token, trace_id=job or uuid4(), job_id=job)
    return scope, _scope.set(scope)


def close_scope(reset) -> None:
    _scope.reset(reset)


@contextmanager
def bound(token: str | None, job_id: UUID | str | None = None) -> Iterator[Scope | None]:
    """Collect model calls made in this context and write them when it ends."""
    if not token:
        yield None
        return
    scope, reset = open_scope(token, job_id)
    try:
        yield scope
    finally:
        close_scope(reset)
        flush(scope)
