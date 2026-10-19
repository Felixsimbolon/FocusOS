"""Notes: free-form writing, each kept in a project.

A note is plain text the user owns and edits; nothing is extracted from it unless the user
asks ("Turn into tasks"), so editing a note never creates duplicate tasks. Each saved
version gets an embedding (best effort), so questions in the composer can cite notes the
same way they cite memories. Saves use an optimistic version check: an edit made in
another tab is never silently overwritten.
"""
import re
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.job_routes import access, call
from focusos_api.jobs import JobInput, enqueue_job
from focusos_api.memory_embeddings import EmbeddingError, embed_text
from focusos_api.memory_search import query_terms, vector_literal
from focusos_api.sources import ManualSourceInput, create_manual_source

router = APIRouter()
EMBED_CHARS = 2000
NOTE_REFERENCES = 3


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=50000)
    expected_version: int = Field(ge=0)


class CaptureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID


def _code(exc: Exception) -> str | None:
    return getattr(exc.__cause__, "code", None)


def list_notes(token: str, project_id: UUID | None = None) -> list[dict]:
    with scoped_client(token) as (owner, client):
        query = client.table("notes").select("id,project_id,title,body,version,updated_at").eq("user_id", owner)
        if project_id: query = query.eq("project_id", str(project_id))
        rows = query.order("updated_at", desc=True).limit(200).execute().data
    return [{**{k: v for k, v in row.items() if k != "body"}, "excerpt": " ".join(str(row.get("body") or "").split())[:160]}
            for row in rows] if isinstance(rows, list) else []


def read_note(token: str, note_id: UUID) -> dict:
    with scoped_client(token) as (owner, client):
        rows = client.table("notes").select("id,project_id,title,body,version,updated_at").eq("user_id", owner).eq("id", str(note_id)).limit(1).execute().data
    if not isinstance(rows, list) or not rows: raise HTTPException(404, "Note not found")
    return rows[0]


def embed_note(token: str, note: dict) -> bool:
    """Best effort: a note without a vector is still found by its words."""
    try:
        vector = embed_text((note["title"] + "\n" + note["body"])[:EMBED_CHARS].strip(), purpose="embed_note")
        with scoped_client(token) as (_, client):
            return client.rpc("focusos_set_note_embedding", {"p_id": str(note["id"]), "p_version": note["version"],
                                                             "p_vector": vector_literal(vector)}).execute().data is True
    except (EmbeddingError, DatabaseUnavailable):
        return False


def save_note(token: str, note_id: UUID, note: NoteInput) -> dict:
    if note.project_id is None: raise HTTPException(422, "Choose a project for this note.")
    try:
        with scoped_client(token) as (_, client):
            saved = client.rpc("focusos_save_note", {"p_id": str(note_id), "p_project_id": str(note.project_id) if note.project_id else None,
                "p_title": note.title, "p_body": note.body, "p_expected_version": note.expected_version}).execute().data
    except DatabaseUnavailable as exc:
        code = _code(exc)
        if code == "40001": raise HTTPException(409, "This note changed in another window. Reload it before saving again.") from exc
        if code == "P0002": raise HTTPException(404, "Note or project not found") from exc
        if code == "23502": raise HTTPException(422, "Choose a project for this note.") from exc
        if code == "54000": raise HTTPException(429, "You have reached 2,000 notes.") from exc
        raise
    if not isinstance(saved, dict): raise DatabaseUnavailable("Note was not saved")
    saved["indexed"] = embed_note(token, saved)
    return saved


def delete_note(token: str, note_id: UUID) -> dict:
    with scoped_client(token) as (_, client):
        deleted = client.rpc("focusos_delete_note", {"p_id": str(note_id)}).execute().data
    if deleted is not True: raise HTTPException(404, "Note not found")
    return {"deleted": True}


def capture_note(token: str, note_id: UUID, request: CaptureInput) -> dict:
    """Run the usual extraction on this note's text, on request; the note itself is unchanged."""
    note = read_note(token, note_id)
    if not note["body"].strip(): raise HTTPException(422, "This note is empty.")
    source = create_manual_source(token, request.request_key, ManualSourceInput(title=f"Note: {note['title']}"[:200], text=note["body"][:25000])).source
    job = enqueue_job(token, JobInput(request_key=uuid5(request.request_key, "capture"), kind="source", subject_id=source.id))
    return {"source_id": str(source.id), "background_job": job.model_dump(mode="json")}


PROJECT_NOTES = 5
PROJECT_EXCERPT = 1500


def _normal(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", text.casefold())) + " "


def mentioned_projects(projects: list[dict], question: str) -> list[dict]:
    """Projects whose whole name appears in the question ("progress Skripsi?" names Skripsi)."""
    asked = _normal(question)
    return [project for project in projects if len(_normal(project["name"]).strip()) >= 3 and _normal(project["name"]) in asked]


def project_notes(token: str, questions: list[str]) -> list[dict]:
    """A project's own notes, whole excerpts, when a question names that project: they are part of the project."""
    with scoped_client(token) as (owner, client):
        projects = client.table("projects").select("id,name").eq("user_id", owner).limit(100).execute().data
        named = {project["id"]: project for question in questions
                 for project in mentioned_projects(projects if isinstance(projects, list) else [], question)}
        if not named: return []
        rows = (client.table("notes").select("id,title,body,project_id").eq("user_id", owner).in_("project_id", list(named))
                .order("updated_at", desc=True).limit(PROJECT_NOTES).execute().data)
    return [{"id": row["id"], "title": row["title"], "excerpt": str(row.get("body") or "")[:PROJECT_EXCERPT],
             "project": named[row["project_id"]]["name"]} for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def note_matches(token: str, question: str, vector: list[float] | None) -> list[dict]:
    terms = query_terms(question)[:16]
    if not terms and vector is None: return []
    with scoped_client(token) as (_, client):
        rows = client.rpc("focusos_search_notes", {"p_terms": terms, "p_vector": vector_literal(vector) if vector is not None else None,
                                                   "p_limit": NOTE_REFERENCES}).execute().data
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


@router.get("/notes")
def notes(project_id: UUID | None = None, token: str = Depends(access)): return call(list_notes, token, project_id)
@router.get("/notes/{note_id}")
def note(note_id: UUID, token: str = Depends(access)): return call(read_note, token, note_id)
@router.post("/notes/{note_id}")
def save(note_id: UUID, note_input: NoteInput, token: str = Depends(access)): return call(save_note, token, note_id, note_input)
@router.post("/notes/{note_id}/delete")
def delete(note_id: UUID, token: str = Depends(access)): return call(delete_note, token, note_id)
@router.post("/notes/{note_id}/capture", status_code=202)
def capture(note_id: UUID, request_input: CaptureInput, token: str = Depends(access)): return call(capture_note, token, note_id, request_input)
