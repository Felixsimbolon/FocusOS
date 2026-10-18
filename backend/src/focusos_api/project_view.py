"""Projects as a place: each project's tasks, assignments, notes and upcoming focus blocks."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from focusos_api.database import scoped_client
from focusos_api.job_routes import access, call

router = APIRouter()


def _rows(data) -> list[dict]:
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _gather(token: str) -> dict:
    with scoped_client(token) as (owner, client):
        return {
            "projects": _rows(client.table("projects").select("id,name,created_at").eq("user_id", owner).order("name").limit(100).execute().data),
            "tasks": _rows(client.table("tasks").select("id,title,status,priority,due_kind,due_date,due_at,estimate_minutes,project_id,version")
                           .eq("user_id", owner).neq("status", "archived").not_.is_("project_id", "null").limit(1000).execute().data),
            "notes": _rows(client.table("notes").select("id,title,project_id,updated_at").eq("user_id", owner).not_.is_("project_id", "null").limit(1000).execute().data),
            "assignments": _rows(client.table("assignments").select("id,title,status,project_id,created_at").eq("user_id", owner).limit(200).execute().data),
            "files": _rows(client.table("project_files").select("id,project_id,assignment_id,name,mime_type,size_bytes,created_at")
                           .eq("user_id", owner).order("created_at", desc=True).limit(500).execute().data),
            "blocks": _rows(client.table("approval_requests").select("id,task_id,payload,status,cancellation_status")
                            .eq("user_id", owner).eq("status", "succeeded").order("created_at", desc=True).limit(200).execute().data),
        }


def _due(task: dict) -> str | None:
    return task.get("due_date") if task.get("due_kind") == "date" else (task.get("due_at") or "")[:10] or None


def _blocks(blocks: list[dict], task_ids: set[str], now: datetime, past: bool = False) -> list[dict]:
    """The project's booked focus blocks: still to come (soonest first), or already over (latest first)."""
    found = []
    for block in blocks:
        payload = block.get("payload") or {}
        if str(block.get("task_id")) not in task_ids or block.get("cancellation_status") == "cancelled": continue
        try:
            if (datetime.fromisoformat(payload["end"]) <= now) != past: continue
        except (KeyError, TypeError, ValueError):
            continue
        found.append({"id": block["id"], "task_id": block.get("task_id"), "title": payload.get("title"), "start": payload["start"],
                      "end": payload["end"], "timezone": payload.get("timezone")})
    return sorted(found, key=lambda item: item["start"], reverse=past)


def _upcoming(blocks: list[dict], task_ids: set[str], now: datetime) -> list[dict]:
    return _blocks(blocks, task_ids, now)


def _files(data: dict, project_id: str) -> list[dict]:
    """Files kept with the project, and the briefs of its assignments."""
    assignments = {item["id"]: item.get("title") for item in data["assignments"] if item.get("project_id") == project_id}
    return [{**item, "assignment": assignments.get(item.get("assignment_id"))} for item in data.get("files", [])
            if item.get("project_id") == project_id or item.get("assignment_id") in assignments]


def overview(token: str, now: datetime | None = None) -> list[dict]:
    current = now or datetime.now(timezone.utc)
    data = _gather(token)
    result = []
    for project in data["projects"]:
        pid = project["id"]
        tasks = [task for task in data["tasks"] if task.get("project_id") == pid]
        open_tasks = [task for task in tasks if task["status"] == "open"]
        upcoming = _upcoming(data["blocks"], {task["id"] for task in tasks}, current)
        deadlines = sorted(due for task in open_tasks if (due := _due(task)))
        result.append({**project, "open_tasks": len(open_tasks), "done_tasks": len(tasks) - len(open_tasks),
                       "notes": sum(note.get("project_id") == pid for note in data["notes"]),
                       "assignments": sum(item.get("project_id") == pid for item in data["assignments"]),
                       "files": len(_files(data, pid)),
                       "next_deadline": deadlines[0] if deadlines else None,
                       "next_block": upcoming[0] if upcoming else None})
    return result


def detail(token: str, project_id: UUID, now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    data = _gather(token)
    project = next((item for item in data["projects"] if item["id"] == str(project_id)), None)
    if project is None: raise HTTPException(404, "Project not found")
    tasks = [task for task in data["tasks"] if task.get("project_id") == project["id"]]
    tasks.sort(key=lambda task: (task["status"] != "open", _due(task) or "9999", task["title"]))
    dues = sorted(due for task in tasks if task["status"] == "open" and (due := _due(task)))
    # The summit of the project's trail: its last open deadline.
    return {**project, "deadline": dues[-1] if dues else None, "tasks": tasks[:100],
            "notes": sorted((note for note in data["notes"] if note.get("project_id") == project["id"]), key=lambda note: note["updated_at"], reverse=True),
            "assignments": [item for item in data["assignments"] if item.get("project_id") == project["id"]],
            "files": _files(data, project["id"]),
            "upcoming": _upcoming(data["blocks"], {task["id"] for task in tasks}, current)[:20],
            "past": _blocks(data["blocks"], {task["id"] for task in tasks}, current, past=True)[:10]}


@router.get("/projects/overview")
def projects_overview(token: str = Depends(access)): return call(overview, token)
@router.get("/projects/{project_id}/detail")
def project_detail(project_id: UUID, token: str = Depends(access)): return call(detail, token, project_id)
