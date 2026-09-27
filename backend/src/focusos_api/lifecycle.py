"""Owner-scoped lifecycle controls; database RPCs perform atomic changes."""
from uuid import UUID
from pydantic import BaseModel
from focusos_api.database import DatabaseUnavailable, scoped_client

class DisconnectResult(BaseModel):
    disconnected: bool

class DeleteImportedSourceResult(BaseModel):
    deleted: bool
    tasks_deleted: int = 0
    command_runs_deleted: int = 0


def disconnect_google(access_token: str) -> DisconnectResult:
    with scoped_client(access_token) as (_, client):
        data = client.rpc("focusos_disconnect_google", {}).execute().data
    if not isinstance(data, dict):
        raise DatabaseUnavailable("Google disconnect unavailable")
    return DisconnectResult.model_validate(data)


def delete_imported_source(access_token: str, source_id: UUID) -> DeleteImportedSourceResult:
    with scoped_client(access_token) as (_, client):
        data = client.rpc("focusos_delete_gmail_source", {"p_source_id": str(source_id)}).execute().data
    if not isinstance(data, dict):
        raise DatabaseUnavailable("Imported source removal unavailable")
    return DeleteImportedSourceResult.model_validate(data)

