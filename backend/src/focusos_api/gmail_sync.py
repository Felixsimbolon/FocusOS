"""One bounded, checkpointed Gmail sync operation per request."""
from uuid import UUID
import re

import httpx
from pydantic import BaseModel, ConfigDict

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.gmail_fetch import fetch_selected_with_bearer
from focusos_api.gmail_normalize import GmailNormalizationError
from focusos_api.gmail_selection import (GMAIL_ROOT, ID_PATTERN, GmailSelectionError,
    GmailSelectionReconnect, GmailSelectionUnavailable, google_bearer,
    provider_json, selected_label_id)
from focusos_api.gmail_sources import upsert_gmail_source

INITIAL_PAGE_SIZE = 2


class GmailSyncStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str
    mode: str | None = None
    imported: int = 0
    unavailable: int = 0


def _history_anchor(client: httpx.Client, bearer: str) -> str:
    profile = provider_json(client, GMAIL_ROOT + "/profile", bearer)
    history_id = profile.get("historyId")
    if not isinstance(history_id, str) or not history_id.isdigit() or len(history_id) > 30:
        raise GmailSelectionError("Invalid Gmail history anchor")
    return history_id


def _claim(access_token: str, connection_id: UUID, label_id: str, anchor: str) -> dict:
    with scoped_client(access_token) as (_, client):
        data = client.rpc("focusos_claim_gmail_sync", {
            "p_connection_id": str(connection_id),
            "p_label_id": label_id,
            "p_anchor_history_id": anchor,
        }).execute().data
    if not isinstance(data, dict):
        raise DatabaseUnavailable("Unexpected Gmail sync claim")
    return data


def _finish(access_token: str, connection_id: UUID, lease: str, action: str,
            *, page_token: str | None = None, history_id: str | None = None,
            pending_ids: list[str] | None = None, processed_count: int | None = None,
            retry_seconds: int | None = None, error: str | None = None) -> None:
    with scoped_client(access_token) as (_, client):
        result = client.rpc("focusos_finish_gmail_sync", {
            "p_connection_id": str(connection_id),
            "p_lease_token": lease,
            "p_action": action,
            "p_page_token": page_token,
            "p_history_id": history_id,
            "p_pending_ids": pending_ids,
            "p_processed_count": processed_count,
            "p_retry_seconds": retry_seconds,
            "p_error": error,
        }).execute().data
    if result is not True:
        raise DatabaseUnavailable("Gmail sync lease was lost")


def _initial_page(client: httpx.Client, bearer: str, label_id: str,
                  page_token: str | None) -> tuple[list[str], str | None]:
    params = {"labelIds": label_id, "maxResults": INITIAL_PAGE_SIZE,
              "includeSpamTrash": "false"}
    if page_token:
        params["pageToken"] = page_token
    data = provider_json(client, GMAIL_ROOT + "/messages", bearer, params)
    messages = data.get("messages", [])
    if not isinstance(messages, list) or len(messages) > INITIAL_PAGE_SIZE:
        raise GmailSelectionError("Invalid initial page")
    ids = []
    for item in messages:
        message_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(message_id, str) or not ID_PATTERN.fullmatch(message_id):
            raise GmailSelectionError("Invalid initial message ID")
        ids.append(message_id)
    next_token = data.get("nextPageToken")
    if next_token is not None and (not isinstance(next_token, str) or
        len(next_token) > 1024 or not re.fullmatch(r"[A-Za-z0-9_=-]+", next_token)):
        raise GmailSelectionError("Invalid initial page token")
    return ids, next_token


def run_one_sync_page(access_token: str, *, http_client: httpx.Client | None = None) -> GmailSyncStep:
    connection, bearer = google_bearer(access_token)
    own = http_client is None
    client = http_client or httpx.Client(timeout=10.0, follow_redirects=False)
    try:
        label_id = selected_label_id(client, bearer)
        anchor = _history_anchor(client, bearer)
        claim = _claim(access_token, connection.id, label_id, anchor)
        state = claim.get("state")
        if state == "reconnect":
            raise GmailSelectionReconnect()
        if state in ("busy", "backoff"):
            return GmailSyncStep(state=state)
        if state != "claimed":
            raise DatabaseUnavailable("Unexpected Gmail sync state")
        lease = claim["lease_token"]
        try:
            if claim.get("mode") == "history":
                return _run_history_page(access_token, connection.id, client, bearer, label_id, claim)
            if claim.get("mode") != "initial":
                raise GmailSelectionError("Invalid Gmail sync mode")
            ids, next_token = _initial_page(client, bearer, label_id, claim.get("initial_page_token"))
            results = fetch_selected_with_bearer(client, bearer, label_id, ids)
            imported = unavailable = 0
            for item in results:
                if item.status == "unavailable":
                    unavailable += 1
                else:
                    upsert_gmail_source(access_token, connection.id, item)
                    imported += 1
            _finish(access_token, connection.id, lease, "initial_page", page_token=next_token)
            return GmailSyncStep(state="partial" if next_token else "complete",
                                 mode="initial", imported=imported, unavailable=unavailable)
        except GmailSelectionUnavailable as exc:
            _finish(access_token, connection.id, lease, "retry",
                    retry_seconds=exc.retry_after or 60, error="provider_unavailable")
            return GmailSyncStep(state="retry_wait", mode=claim.get("mode"))
        except (GmailSelectionError, GmailNormalizationError) as exc:
            _finish(access_token, connection.id, lease, "error", error="invalid_provider_response")
            raise
    finally:
        if own:
            client.close()


def _run_history_page(access_token: str, connection_id: UUID, client: httpx.Client,
                      bearer: str, label_id: str, claim: dict) -> GmailSyncStep:
    # Implemented in 5.6b; initial checkpoint is already durable.
    raise GmailSelectionError("History synchronization is not ready")
