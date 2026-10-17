"""Email notifications from the user's own Gmail to the same address.

Two kinds: a morning brief (today's focus blocks, what is due or overdue, urgent email)
and a reminder shortly before each FocusOS block. Emails are written by plain templates,
not a model, so they are cheap, predictable and cannot invent anything.

They must go out while nobody is signed in. The worker tick (shared worker secret, every
few minutes) asks the database to plan and lease due emails; the database returns only
the fields each email needs, for owners who switched notifications on. Sending uses that
owner's stored Google token with the gmail.send permission, which the user grants once.
"""
import base64
import hmac
import logging
import os
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.job_routes import access, call
from focusos_api.jobs import _service_rpc

router = APIRouter()
logger = logging.getLogger(__name__)
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
BATCH = 20


class NotificationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    morning_brief: bool
    brief_minute: int = Field(ge=0, le=1439)
    block_reminders: bool
    reminder_minutes: Literal[5, 10, 15, 30]


def _local(value: str, zone: ZoneInfo) -> datetime:
    return datetime.fromisoformat(value).astimezone(zone)


def _hm(value: datetime) -> str:
    return f"{value:%H:%M}"


def app_link() -> str:
    return os.environ.get("FOCUSOS_WEB_URL", "").strip().rstrip("/")


def compose(item: dict, now: datetime) -> tuple[str, str] | None:
    """Subject and plain-text body for one outbox item; None when there is nothing worth sending."""
    zone = ZoneInfo(item.get("timezone") or "UTC")
    link = app_link()
    footer = f"\n\nOpen FocusOS: {link}" if link else ""
    footer += "\n\nYou get this because email notifications are on in FocusOS. Turn them off under Everything else, Email notifications."
    if item["kind"] == "block_reminder":
        block = item.get("block") or {}
        if not block or block.get("cancelled"): return None
        start, end = _local(block["start"], zone), _local(block["end"], zone)
        if start <= now.astimezone(zone): return None  # too late to be useful
        minutes = max(1, round((start - now).total_seconds() / 60))
        subject = f"In {minutes} min: {block['title']} ({_hm(start)}–{_hm(end)})"
        body = f"Your focus block \"{block['title']}\" starts at {_hm(start)} and runs until {_hm(end)}.{footer}"
        return subject[:180], body
    brief = item.get("brief") or {}
    today = now.astimezone(zone)
    blocks, due, overdue, urgent = (brief.get(key) or [] for key in ("blocks", "due_today", "overdue", "urgent_email"))
    lines = [f"Good morning. Here is {today:%A %d %B}."]
    if blocks:
        lines += ["", "Focus blocks today:"] + [f"  {_hm(_local(b['start'], zone))}–{_hm(_local(b['end'], zone))}  {b['title']}" for b in blocks]
    else:
        lines += ["", "No focus blocks are booked today. Ask FocusOS for time if something needs it."]
    if due: lines += ["", "Due today:"] + [f"  {title}" for title in due]
    if overdue: lines += ["", "Past the deadline:"] + [f"  {title}" for title in overdue]
    if urgent: lines += ["", "Urgent email:"] + [f"  {title}" for title in urgent]
    counts = [f"{len(due)} due" if due else None, f"{len(blocks)} focus block{'s' if len(blocks) != 1 else ''}" if blocks else None,
              f"{len(overdue)} overdue" if overdue else None]
    subject = f"Your day, {today:%a %d %b}: " + (", ".join(c for c in counts if c) or "a clear day")
    return subject[:180], "\n".join(lines) + footer


def raw_message(address: str, subject: str, body: str) -> str:
    message = EmailMessage()
    message["From"] = formataddr(("FocusOS", address))
    message["To"] = address
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _bearer(connection_id: UUID) -> str:
    from focusos_api.approval_execute import _get_bearer
    return _get_bearer(connection_id)


def send_one(item: dict, now: datetime, client: httpx.Client) -> tuple[str, str | None]:
    """Returns (status, safe_error): sent, failed (permanent) or pending (try again later)."""
    connection = item.get("connection") or {}
    if not connection.get("id") or not connection.get("email"): return "failed", "google_not_connected"
    if GMAIL_SEND_SCOPE not in (connection.get("scopes") or []): return "failed", "gmail_send_permission"
    composed = compose(item, now)
    if composed is None: return "sent", "nothing_to_send"
    try:
        bearer = _bearer(UUID(str(connection["id"])))
        response = client.post(SEND_URL, headers={"Authorization": "Bearer " + bearer},
                               json={"raw": raw_message(connection["email"], *composed)}, timeout=15.0)
    except Exception:  # noqa: BLE001 - token refresh or network failure: no token or body in logs.
        return "pending", "provider_unavailable"
    if response.status_code in (401, 403): return "failed", "gmail_send_rejected"
    if response.status_code == 429 or response.status_code >= 500: return "pending", "provider_unavailable"
    return ("sent", None) if response.status_code == 200 else ("failed", "gmail_send_rejected")


def send_due(now: datetime | None = None, owner: str | None = None, http_client: httpx.Client | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    planned = _service_rpc("focusos_plan_notifications", {"p_now": current.isoformat()}) if owner is None else 0
    items = _service_rpc("focusos_claim_notifications", {"p_now": current.isoformat(), "p_limit": BATCH, "p_owner": owner}) or []
    client = http_client or httpx.Client(timeout=15.0, follow_redirects=False)
    counts = {"planned": planned or 0, "sent": 0, "failed": 0, "retry": 0}
    try:
        for item in items:
            status, error = send_one(item, current, client)
            _service_rpc("focusos_finish_notification", {"p_id": item["id"], "p_status": status, "p_error": error})
            counts["sent" if status == "sent" else "failed" if status == "failed" else "retry"] += 1
    finally:
        if http_client is None: client.close()
    logger.info("notifications planned=%s sent=%s failed=%s retry=%s", counts["planned"], counts["sent"], counts["failed"], counts["retry"])
    return counts


def read_settings(token: str) -> dict:
    with scoped_client(token) as (owner, client):
        rows = client.table("notification_settings").select("morning_brief,brief_minute,block_reminders,reminder_minutes").eq("user_id", owner).limit(1).execute().data
        recent = (client.table("email_outbox").select("kind,status,sent_at,safe_error,created_at").eq("user_id", owner)
                  .order("created_at", desc=True).limit(8).execute().data)
        connection = (client.table("connections").select("display_email,granted_scopes,status").eq("user_id", owner)
                      .eq("provider", "google").limit(1).execute().data)
    settings = rows[0] if isinstance(rows, list) and rows else {"morning_brief": False, "brief_minute": 420, "block_reminders": False, "reminder_minutes": 10}
    google = connection[0] if isinstance(connection, list) and connection else {}
    return {**settings, "recent": recent if isinstance(recent, list) else [], "email": google.get("display_email"),
            "can_send": google.get("status") == "connected" and GMAIL_SEND_SCOPE in (google.get("granted_scopes") or [])}


def save_settings(token: str, settings: NotificationSettings) -> dict:
    with scoped_client(token) as (_, client):
        client.rpc("focusos_save_notification_settings", {"p_morning_brief": settings.morning_brief, "p_brief_minute": settings.brief_minute,
            "p_block_reminders": settings.block_reminders, "p_reminder_minutes": settings.reminder_minutes}).execute()
    return read_settings(token)


def send_test(token: str) -> dict:
    """Queue a brief for the signed-in user and send it now through the same path the worker uses."""
    try:
        with scoped_client(token) as (owner, client):
            client.rpc("focusos_queue_test_brief", {}).execute()
    except DatabaseUnavailable as exc:
        if getattr(exc.__cause__, "code", None) == "54000": raise HTTPException(429, "Three test emails per hour. Try again later.") from exc
        raise
    counts = send_due(owner=owner)
    if counts["sent"]: return {"sent": True}
    settings = read_settings(token)
    reason = (settings["recent"][0].get("safe_error") if settings["recent"] else None) or "provider_unavailable"
    return {"sent": False, "reason": reason}


@router.get("/notifications/settings")
def get_settings(token: str = Depends(access)): return call(read_settings, token)
@router.post("/notifications/settings")
def put_settings(settings: NotificationSettings, token: str = Depends(access)): return call(save_settings, token, settings)
@router.post("/notifications/test")
def test_email(token: str = Depends(access)): return call(send_test, token)


@router.post("/internal/notifications/tick")
def tick(authorization: str | None = Header(default=None)):
    secret = os.environ.get("FOCUSOS_WORKER_SECRET", "")
    if len(secret) < 32: raise HTTPException(503, "Worker trigger is not configured")
    if not authorization or not hmac.compare_digest(authorization, "Bearer " + secret): raise HTTPException(401, "Worker authentication required")
    return call(send_due)
