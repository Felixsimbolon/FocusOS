from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from uuid import UUID

from focusos_api.connections import GoogleConnectionEnvelope, read_google_connection
from focusos_api.database import (
    DatabaseUnavailable,
    InvalidSession,
    check_database_identity,
)
from focusos_api.google_calendar import (
    CalendarPageProbe,
    CalendarProbeError,
    CalendarProbeUnavailable,
    CalendarReconnectRequired,
    read_primary_calendar_page,
)
from focusos_api.google_gmail import (
    GmailProbeError,
    GmailProbeUnavailable,
    GmailReconnectRequired,
    GmailMessageProbe,
    read_selected_gmail_message,
)
from focusos_api.google_oauth import (
    GoogleAuthorizationInput,
    GoogleOAuthError,
    GoogleOAuthUnavailable,
    complete_calendar_write_upgrade,
    complete_google_authorization,
)
from focusos_api.profiles import (
    ProfileEnvelope,
    ProfileInput,
    read_profile,
    save_profile,
)
from focusos_api.tasks import (
    TaskCreate,
    TaskCreateEnvelope,
    TaskListEnvelope,
    ProjectCreate,
    ProjectEnvelope,
    ProjectListEnvelope,
    TaskProjectNotFound,
    TaskRequestConflict,
    TaskStatus,
    TaskUpdate,
    TaskUpdateEnvelope,
    TaskUpdateNotFound,
    TodayTaskEnvelope,
    create_project,
    create_task,
    list_projects,
    list_tasks,
    list_today_tasks,
    update_task,
)

app = FastAPI(title="FocusOS API", version="0.1.0")
bearer = HTTPBearer(auto_error=False)


def require_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    return credentials.credentials


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/database")
def database_health(access_token: str = Depends(require_access_token)) -> dict[str, str]:
    try:
        check_database_identity(access_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Database check unavailable") from exc
    return {"status": "ok"}


@app.get("/profile", response_model=ProfileEnvelope)
def profile_get(access_token: str = Depends(require_access_token)) -> ProfileEnvelope:
    try:
        return ProfileEnvelope(profile=read_profile(access_token))
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Profile unavailable") from exc


@app.put("/profile", response_model=ProfileEnvelope)
def profile_put(
    profile: ProfileInput,
    access_token: str = Depends(require_access_token),
) -> ProfileEnvelope:
    try:
        return ProfileEnvelope(profile=save_profile(access_token, profile))
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Profile unavailable") from exc


@app.get("/connections/google", response_model=GoogleConnectionEnvelope)
def google_connection_get(
    access_token: str = Depends(require_access_token),
) -> GoogleConnectionEnvelope:
    try:
        return GoogleConnectionEnvelope(connection=read_google_connection(access_token))
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Connection unavailable") from exc


@app.post("/connections/google/authorize", response_model=GoogleConnectionEnvelope)
def google_connection_authorize(
    request: GoogleAuthorizationInput,
    access_token: str = Depends(require_access_token),
) -> GoogleConnectionEnvelope:
    try:
        connection = complete_google_authorization(access_token, request)
        return GoogleConnectionEnvelope(connection=connection)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except GoogleOAuthUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GoogleOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Google connection unavailable") from exc


@app.get("/connections/google/gmail/messages/{message_id}", response_model=GmailMessageProbe)
def google_gmail_message_probe(
    message_id: str,
    access_token: str = Depends(require_access_token),
) -> GmailMessageProbe:
    try:
        return read_selected_gmail_message(access_token, message_id)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except GmailReconnectRequired as exc:
        raise HTTPException(status_code=409, detail="Google connection needs authorization") from exc
    except GmailProbeUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GmailProbeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail probe unavailable") from exc


@app.post("/connections/google/calendar-write/authorize", response_model=GoogleConnectionEnvelope)
def google_calendar_write_authorize(
    request: GoogleAuthorizationInput,
    access_token: str = Depends(require_access_token),
) -> GoogleConnectionEnvelope:
    try:
        connection = complete_calendar_write_upgrade(access_token, request)
        return GoogleConnectionEnvelope(connection=connection)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except GoogleOAuthUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GoogleOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Google connection unavailable") from exc


@app.get("/connections/google/calendar/probe", response_model=CalendarPageProbe)
def google_calendar_page_probe(
    access_token: str = Depends(require_access_token),
) -> CalendarPageProbe:
    try:
        return read_primary_calendar_page(access_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except CalendarReconnectRequired as exc:
        raise HTTPException(status_code=409, detail="Google connection needs authorization") from exc
    except CalendarProbeUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CalendarProbeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Calendar probe unavailable") from exc


@app.get("/tasks", response_model=TaskListEnvelope)
def tasks_get(
    status: TaskStatus | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    access_token: str = Depends(require_access_token),
) -> TaskListEnvelope:
    try:
        return list_tasks(access_token, status=status, limit=limit)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Task list unavailable") from exc


@app.post("/tasks", response_model=TaskCreateEnvelope)
def tasks_post(
    task: TaskCreate,
    request_id: UUID = Header(alias="Idempotency-Key"),
    access_token: str = Depends(require_access_token),
) -> TaskCreateEnvelope:
    try:
        return create_task(access_token, request_id, task)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except TaskProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except TaskRequestConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key was already used with a different task",
        ) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Task could not be saved") from exc


@app.get("/projects", response_model=ProjectListEnvelope)
def projects_get(
    access_token: str = Depends(require_access_token),
) -> ProjectListEnvelope:
    try:
        return list_projects(access_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Project list unavailable") from exc


@app.post("/projects", response_model=ProjectEnvelope)
def projects_post(
    project: ProjectCreate,
    access_token: str = Depends(require_access_token),
) -> ProjectEnvelope:
    try:
        return create_project(access_token, project)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Project could not be saved") from exc


@app.get("/tasks/today", response_model=TodayTaskEnvelope)
def tasks_today_get(
    access_token: str = Depends(require_access_token),
) -> TodayTaskEnvelope:
    try:
        return list_today_tasks(access_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Today tasks unavailable") from exc


@app.patch("/tasks/{task_id}", response_model=TaskUpdateEnvelope)
def tasks_patch(
    task_id: UUID,
    update: TaskUpdate,
    access_token: str = Depends(require_access_token),
) -> TaskUpdateEnvelope:
    try:
        result = update_task(access_token, task_id, update)
        if result.outcome == "stale":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Task changed since it was loaded",
                    "task": result.task.model_dump(mode="json"),
                },
            )
        return result
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except TaskUpdateNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except TaskProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Task could not be updated") from exc
