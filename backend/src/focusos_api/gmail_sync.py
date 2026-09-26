"""One bounded, checkpointed Gmail sync operation per request."""
from uuid import UUID
import re

import httpx
from pydantic import BaseModel, ConfigDict

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.gmail_fetch import fetch_selected_with_bearer
from focusos_api.gmail_normalize import GmailNormalizationError
from focusos_api.gmail_selection import (GMAIL_ROOT, ID_PATTERN, GmailMessageGone, GmailSelectionError,
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
            results = fetch_selected_with_bearer(client, bearer, label_id, ids, allow_unselected=True)
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


def _history_ids(data: dict, label_id: str) -> tuple[list[str], str | None, str]:
    rows = data.get("history", [])
    if not isinstance(rows, list) or len(rows) > 5:
        raise GmailSelectionError("Invalid Gmail history page")
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise GmailSelectionError("Invalid Gmail history entry")
        for key in ("messagesAdded", "labelsAdded"):
            changes = row.get(key, [])
            if not isinstance(changes, list):
                raise GmailSelectionError("Invalid Gmail history changes")
            for change in changes:
                if not isinstance(change, dict):
                    raise GmailSelectionError("Invalid Gmail history change")
                if key == "labelsAdded":
                    added_labels = change.get("labelIds")
                    if not isinstance(added_labels, list):
                        raise GmailSelectionError("Invalid Gmail history labels")
                    if label_id not in added_labels:
                        continue
                message = change.get("message")
                message_id = message.get("id") if isinstance(message, dict) else None
                if not isinstance(message_id, str) or not ID_PATTERN.fullmatch(message_id):
                    raise GmailSelectionError("Invalid Gmail history message ID")
                if message_id not in ids:
                    ids.append(message_id)
                if len(ids) > 30:
                    raise GmailSelectionError("Gmail history page exceeds staging limit")
    next_token = data.get("nextPageToken")
    if next_token is not None and (not isinstance(next_token, str) or
        len(next_token) > 1024 or not re.fullmatch(r"[A-Za-z0-9_=-]+", next_token)):
        raise GmailSelectionError("Invalid Gmail history page token")
    history_id = data.get("historyId")
    if not isinstance(history_id, str) or not history_id.isdigit() or len(history_id) > 30:
        raise GmailSelectionError("Invalid Gmail history ID")
    return ids, next_token, history_id


def _run_history_page(access_token: str, connection_id: UUID, client: httpx.Client,
                      bearer: str, label_id: str, claim: dict) -> GmailSyncStep:
    lease = claim["lease_token"]
    pending = claim.get("pending_ids") or []
    if not isinstance(pending, list):
        raise GmailSelectionError("Invalid staged Gmail IDs")
    if pending:
        batch = pending[:2]
        if any(not isinstance(item, str) or not ID_PATTERN.fullmatch(item) for item in batch):
            raise GmailSelectionError("Invalid staged Gmail ID")
        results = fetch_selected_with_bearer(client, bearer, label_id, batch,
                                             allow_unselected=True)
        imported = unavailable = 0
        for item in results:
            if item.status == "unavailable":
                unavailable += 1
            else:
                upsert_gmail_source(access_token, connection_id, item)
                imported += 1
        _finish(access_token, connection_id, lease, "pending_advanced",
                processed_count=len(batch))
        return GmailSyncStep(state="partial", mode="history",
                             imported=imported, unavailable=unavailable)
    history_id = claim.get("history_id")
    if not isinstance(history_id, str) or not history_id.isdigit():
        raise GmailSelectionError("History cursor missing")
    params = {"startHistoryId": history_id, "labelId": label_id, "maxResults": 5}
    if claim.get("history_page_token"):
        params["pageToken"] = claim["history_page_token"]
    try:
        data = provider_json(client, GMAIL_ROOT + "/history", bearer, params)
    except GmailMessageGone:
        _finish(access_token, connection_id, lease, "rescan",
                history_id=_history_anchor(client, bearer))
        return GmailSyncStep(state="rescan_required", mode="initial")
    ids, next_token, new_history_id = _history_ids(data, label_id)
    if ids:
        _finish(access_token, connection_id, lease, "history_staged",
                page_token=next_token, history_id=new_history_id, pending_ids=ids)
        return GmailSyncStep(state="partial", mode="history")
    _finish(access_token, connection_id, lease, "history_page",
            page_token=next_token, history_id=new_history_id)
    return GmailSyncStep(state="partial" if next_token else "complete", mode="history")
