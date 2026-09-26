"""Safe dashboard status for selected-label Gmail synchronization."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from focusos_api.connections import read_google_connection
from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.extractor import MODEL, PROMPT_VERSION, SCHEMA_VERSION
from focusos_api.google_gmail import GMAIL_READ_SCOPE


class GmailSyncStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    connection_status: str
    label_name: str = "FocusOS"
    trigger: str = "manual"
    mode: str | None = None
    last_status: str = "idle"
    last_error: str | None = None
    retry_after: datetime | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    lease_until: datetime | None = None
    pending_staged: int = 0
    page_pending: bool = False
    source_count: int = 0
    ready_count: int = 0
    failed_count: int = 0
    pending_count: int = 0


def read_gmail_sync_status(access_token: str) -> GmailSyncStatus:
    connection = read_google_connection(access_token)
    if connection is None:
        return GmailSyncStatus(connection_status="not_connected")
    if connection.status != "connected" or GMAIL_READ_SCOPE not in connection.granted_scopes:
        return GmailSyncStatus(connection_status="reconnect_required")
    with scoped_client(access_token) as (_, client):
        result = client.rpc("focusos_gmail_sync_status", {
            "p_connection_id": str(connection.id),
            "p_schema": SCHEMA_VERSION, "p_prompt": PROMPT_VERSION, "p_model": MODEL,
        }).execute().data
    if not isinstance(result, dict):
        raise DatabaseUnavailable("Unexpected Gmail sync status")
    return GmailSyncStatus(connection_status="connected", **result)
