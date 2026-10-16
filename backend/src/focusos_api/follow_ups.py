"""Replies to a request that asked the user a question.

A reply is its own request (own run, job and idempotency key) that points at the
request it answers. The server, not the browser, reads what is still open from the
earlier request, so the model only sees the user's own saved text and questions.
Parts the earlier request already completed are listed as done and never redone.
"""
from uuid import UUID

from focusos_api.agent_continuation import CommandRunNotFound, load_command_run
from focusos_api.database import scoped_client

MAX_COMMAND = 1000  # command_runs.command limit; the reply run stores earlier text + reply.
FINISHED = ("succeeded", "failed", "expired", "cancelled")


class FollowUpError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def open_questions(status: str, safe_error: str | None, result: dict) -> list[str]:
    """Questions a finished request left for the user."""
    questions = []
    if status == "failed" and safe_error == "request_ambiguous" and isinstance(result.get("message"), str):
        questions.append(result["message"])
    for item in result.get("schedules") or []:
        if isinstance(item, dict) and item.get("status") == "clarify" and isinstance(item.get("message"), str):
            questions.append(f"{item.get('title') or 'Schedule'}: {item['message']}")
    return [question[:300] for question in questions[:3]]


def already_done(result: dict) -> list[str]:
    done = []
    if result.get("tasks_saved"): done.append(f"saved {result['tasks_saved']} task(s)")
    if result.get("memories_saved"): done.append(f"saved {result['memories_saved']} note(s)")
    for item in result.get("schedules") or []:
        if isinstance(item, dict) and item.get("status") == "scheduled": done.append(f"scheduled {item.get('title')}"[:160])
    for answer in result.get("answers") or []:
        if isinstance(answer, dict) and answer.get("status") in ("answered", "no_reference"):
            done.append(f"answered: {answer.get('question')}"[:160])
    return done[:8]


def _parent_job(token: str, run_id: UUID) -> dict | None:
    with scoped_client(token) as (owner, client):
        rows = (client.table("work_jobs").select("status,result,safe_error").eq("user_id", owner)
                .eq("kind", "planning").eq("subject_id", str(run_id)).order("created_at", desc=True).limit(1).execute().data)
    return rows[0] if isinstance(rows, list) and rows else None


def follow_up(token: str, parent_id: UUID, reply: str) -> tuple[str, dict]:
    """The reply run's command (earlier text + reply) and the conversation context for the model."""
    try:
        parent = load_command_run(token, parent_id)
    except CommandRunNotFound as exc:
        raise FollowUpError("The request you are replying to was not found.") from exc
    if parent.checkpoint.get("entrypoint") != "unified":
        raise FollowUpError("Only requests written in the composer can be continued.")
    job = _parent_job(token, parent_id)
    if job is None or job.get("status") not in FINISHED:
        raise FollowUpError("Wait for the earlier request to finish before replying.")
    questions = open_questions(job["status"], job.get("safe_error"), job.get("result") or {})
    if not questions:
        raise FollowUpError("The earlier request has no open question. Write a new request instead.")
    command = f"{parent.command}\n{reply}"
    if len(command) > MAX_COMMAND:
        raise FollowUpError("This conversation is too long to continue. Write the full request again.")
    return command, {"previous_request": parent.command, "open_questions": questions,
                     "already_done": already_done(job.get("result") or {}), "reply_to": str(parent_id)}
