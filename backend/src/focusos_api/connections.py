# Owner-scoped metadata for an optional Google connection.

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from focusos_api.database import DatabaseUnavailable, scoped_client


class GoogleConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    provider: Literal["google"]
    display_email: str | None
    granted_scopes: list[str]
    status: Literal["connected", "reconnect_required", "disconnected"]
    last_refresh_at: datetime | None


class GoogleConnectionEnvelope(BaseModel):
    connection: GoogleConnection | None


def read_google_connection(access_token: str) -> GoogleConnection | None:
    with scoped_client(access_token) as (user_id, supabase):
        rows = (
            supabase.table("connections")
            .select("id,provider,display_email,granted_scopes,status,last_refresh_at")
            .eq("user_id", user_id)
            .eq("provider", "google")
            .limit(1)
            .execute()
            .data
        )

    if not rows:
        return None
    if not isinstance(rows, list) or len(rows) != 1:
        raise DatabaseUnavailable("Unexpected connection response")
    return GoogleConnection.model_validate(rows[0])
