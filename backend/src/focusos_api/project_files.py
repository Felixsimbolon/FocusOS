"""Project files: the PDFs and photos that belong to a project, kept so they can be opened again.

The bytes go to a private Supabase Storage bucket under "<owner>/<file id>/<name>", written
with the caller's own token, so Storage's row-level security (the owner's folder only)
applies exactly as it does to the tables. A row in project_files links the file to a
project or to an assignment (whose brief it is). Files are opened through a short-lived
signed link; the bucket is never public.
"""
import logging
import re
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from focusos_api.database import DatabaseUnavailable, _settings, scoped_client
from focusos_api.documents import DocumentInput, DocumentRejected, MimeType, decode
from focusos_api.job_routes import access, call

router = APIRouter()
logger = logging.getLogger(__name__)
BUCKET = "project-files"
LINK_SECONDS = 300


class FileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID  # chosen by the client, so a retried upload is the same file
    filename: str = Field(min_length=1, max_length=120)
    mime_type: MimeType
    data: str = Field(min_length=8, max_length=4_100_000)  # base64


def _code(exc: Exception) -> str | None:
    return getattr(exc.__cause__, "code", None)


def safe_name(filename: str) -> str:
    """A storage key segment: letters, digits, dot, dash and underscore; the shown name is kept separately."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.strip()).strip("-.") or "file"
    return stem[-80:]


def _storage(token: str, method: str, path: str, **kwargs) -> httpx.Response:
    url, publishable_key = _settings()
    headers = {"apikey": publishable_key, "Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
    try:
        with httpx.Client(timeout=20.0) as client:
            return client.request(method, f"{url}/storage/v1/{path}", headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise DatabaseUnavailable("Storage unavailable") from exc


def _object(path: str) -> str:
    return f"object/{BUCKET}/{quote(path)}"


def store(token: str, file: FileInput, raw: bytes, project_id: UUID | None, assignment_id: UUID | None) -> dict:
    try:
        with scoped_client(token) as (owner, client):
            path = f"{owner}/{file.id}/{safe_name(file.filename)}"
            response = _storage(token, "POST", _object(path), content=raw, headers={"Content-Type": file.mime_type})
            # 409 is a retry of an upload that already reached Storage: same id, same path.
            if response.status_code not in (200, 201, 409):
                raise HTTPException(503, "Could not keep this file right now. Try again in a moment.")
            try:
                row = client.rpc("focusos_add_project_file", {"p_id": str(file.id), "p_project_id": str(project_id) if project_id else None,
                    "p_assignment_id": str(assignment_id) if assignment_id else None, "p_name": file.filename.strip(),
                    "p_mime_type": file.mime_type, "p_size": len(raw), "p_path": path}).execute().data
            except DatabaseUnavailable:
                _storage(token, "DELETE", _object(path))  # no row, so no orphaned bytes either
                raise
    except DatabaseUnavailable as exc:
        if _code(exc) == "P0002": raise HTTPException(404, "Project not found") from exc
        if _code(exc) == "54000": raise HTTPException(429, "You have reached 500 files.") from exc
        raise
    if not isinstance(row, dict): raise DatabaseUnavailable("File was not saved")
    return row


def upload_file(token: str, project_id: UUID, file: FileInput) -> dict:
    try:
        raw = decode(DocumentInput(request_key=file.id, filename=file.filename, mime_type=file.mime_type, data=file.data))
    except DocumentRejected as exc:
        raise HTTPException(422, exc.message) from exc
    return store(token, file, raw, project_id, None)


def keep_brief(token: str, document: DocumentInput, raw: bytes, assignment_id: UUID) -> bool:
    """Best effort: an assignment whose brief could not be kept still works from its transcription."""
    try:
        store(token, FileInput(id=document.request_key, filename=document.filename, mime_type=document.mime_type, data=document.data),
              raw, None, assignment_id)
        return True
    except Exception:  # noqa: BLE001 - the assignment is already saved; only the copy of its brief is missing.
        logger.warning("Assignment brief not kept")
        return False


def file_link(token: str, file_id: UUID) -> dict:
    with scoped_client(token) as (owner, client):
        rows = client.table("project_files").select("name,storage_path").eq("user_id", owner).eq("id", str(file_id)).limit(1).execute().data
    if not isinstance(rows, list) or not rows: raise HTTPException(404, "File not found")
    response = _storage(token, "POST", f"object/sign/{BUCKET}/{quote(rows[0]['storage_path'])}", json={"expiresIn": LINK_SECONDS})
    signed = response.json().get("signedURL") if response.status_code == 200 else None
    if not isinstance(signed, str): raise DatabaseUnavailable("Storage did not sign the link")
    url, _ = _settings()
    return {"url": f"{url}/storage/v1{signed if signed.startswith('/') else '/' + signed}", "name": rows[0]["name"], "expires_in": LINK_SECONDS}


def delete_file(token: str, file_id: UUID) -> dict:
    with scoped_client(token) as (_, client):
        path = client.rpc("focusos_delete_project_file", {"p_id": str(file_id)}).execute().data
    if not isinstance(path, str) or not path: raise HTTPException(404, "File not found")
    _storage(token, "DELETE", _object(path))  # best effort: the row is gone, so the file is no longer listed or linkable
    return {"deleted": True}


@router.post("/projects/{project_id}/files", status_code=201)
def add(project_id: UUID, file: FileInput, token: str = Depends(access)): return call(upload_file, token, project_id, file)
@router.get("/files/{file_id}/link")
def link(file_id: UUID, token: str = Depends(access)): return call(file_link, token, file_id)
@router.post("/files/{file_id}/delete")
def delete(file_id: UUID, token: str = Depends(access)): return call(delete_file, token, file_id)
