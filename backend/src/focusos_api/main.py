from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from uuid import UUID
from datetime import datetime

from focusos_api.agent_continuation import (AgentRunInput, AgentRunState, continue_staged_run, load_command_run, list_run_tools, start_staged_run)
from focusos_api.approval_proposal import ApprovalRecord, ProposalInput, propose_calendar_event
from focusos_api.agent_model import AgentModelError
from focusos_api.agent_tools import ToolValidationError
from focusos_api.agent_tasks import CommandInput, CommandResult, run_tasks_command
from focusos_api.memory_embeddings import EmbeddingState, embed_memory
from focusos_api.memories import (MemoryEvidenceInvalid, MemoryInput, MemoryRecord, MemoryList, confirm_memory, list_memories, supersede_memory)
from focusos_api.confirmation import (ConfirmInput, ConfirmNotFound, ConfirmStale, ConfirmConflict, ConfirmProjectNotFound, confirm_candidate)
from focusos_api.connections import GoogleConnectionEnvelope, read_google_connection
from focusos_api.database import (
    DatabaseUnavailable,
    InvalidSession,
    check_database_identity,
)
from focusos_api.calendar_availability import (AvailabilityPreview, CalendarProfileRequired, build_availability_preview)
from focusos_api.calendar_domain import CalendarEventError
from focusos_api.calendar_free_time import CalendarPlanningError
from focusos_api.calendar_fetch import (CalendarFetchError, CalendarFetchUnavailable, CalendarWindowStatus, calendar_window_status, fetch_calendar_window)
from focusos_api.google_calendar import (
    CalendarPageProbe,
    CalendarProbeError,
    CalendarProbeUnavailable,
    CalendarReconnectRequired,
    read_primary_calendar_page,
)
from focusos_api.gmail_status import (GmailSyncStatus, read_gmail_sync_status)
from focusos_api.gmail_sync import (GmailSyncStep, run_one_sync_page)
from focusos_api.gmail_processing import (GmailProcessOne, process_one_gmail_source)
from focusos_api.gmail_sources import (GmailIngestEnvelope, ingest_selected_messages)
from focusos_api.gmail_normalize import GmailNormalizationError
from focusos_api.gmail_fetch import (SelectedFetchInput, SelectedFetchEnvelope, fetch_selected_status)
from focusos_api.gmail_selection import (GmailSelectedPage, GmailSelectionError, GmailSelectionMissing, GmailSelectionReconnect, GmailSelectionUnavailable, list_selected_metadata)
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
from focusos_api.extractions import (ExtractionEnvelopeResponse, ExtractionNotFound, ExtractionSourceExpired, ExtractionRateLimited, IgnoreInput, ExtractionRecord, process_extraction, read_extraction, set_extraction_ignored)
from focusos_api.sources import (ManualSourceInput, SourceConflict, SourceEnvelope, SourceListEnvelope, create_manual_source, list_sources, get_source)
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


@app.post("/memories", response_model=MemoryRecord)
def memory_confirm_post(request: MemoryInput,
                        access_token: str = Depends(require_access_token)) -> MemoryRecord:
    try:
        return confirm_memory(access_token, request)
    except MemoryEvidenceInvalid as exc:
        raise HTTPException(status_code=422, detail="Exact source quote required") from exc
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Memory confirmation unavailable") from exc


@app.get("/memories", response_model=MemoryList)
def memories_get(access_token: str = Depends(require_access_token)) -> MemoryList:
    try:
        return list_memories(access_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Memories unavailable") from exc


@app.post("/memories/{memory_id}/embed", response_model=EmbeddingState)
def memory_embed_post(memory_id: UUID,
                      access_token: str = Depends(require_access_token)) -> EmbeddingState:
    try:
        return embed_memory(access_token, memory_id)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Memory embedding unavailable") from exc


@app.post("/memories/{memory_id}/supersede")
def memory_supersede_post(memory_id: UUID,
                          access_token: str = Depends(require_access_token)) -> dict:
    try:
        return {"superseded": supersede_memory(access_token, memory_id)}
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Memory update unavailable") from exc


@app.post("/agent/runs", response_model=AgentRunState)
def agent_run_start(request: AgentRunInput,
                    access_token: str = Depends(require_access_token)) -> AgentRunState:
    try:
        return start_staged_run(access_token, request)
    except CalendarPlanningError as exc:
        raise HTTPException(status_code=409, detail="Save scheduling preferences first") from exc
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Agent run unavailable") from exc


@app.get("/agent/runs/{run_id}", response_model=AgentRunState)
def agent_run_get(run_id: UUID,
                  access_token: str = Depends(require_access_token)) -> AgentRunState:
    try:
        return load_command_run(access_token, run_id)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.get("/agent/runs/{run_id}/tools")
def agent_run_tools_get(run_id: UUID, access_token: str = Depends(require_access_token)) -> list[dict]:
    try:
        return list_run_tools(access_token, run_id)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.post("/agent/runs/{run_id}/propose-event", response_model=ApprovalRecord)
def agent_event_proposal_post(run_id: UUID, request: ProposalInput,
                              access_token: str = Depends(require_access_token)) -> ApprovalRecord:
    try:
        return propose_calendar_event(access_token, run_id, request)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=409, detail="Proposal unavailable or stale") from exc


@app.post("/agent/runs/{run_id}/continue", response_model=AgentRunState)
def agent_run_continue(run_id: UUID,
                       access_token: str = Depends(require_access_token)) -> AgentRunState:
    try:
        return continue_staged_run(access_token, run_id)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except CalendarReconnectRequired as exc:
        raise HTTPException(status_code=409, detail="Reconnect Google Calendar") from exc
    except (CalendarFetchError, CalendarPlanningError, CalendarEventError) as exc:
        raise HTTPException(status_code=422, detail="Calendar read or availability incomplete") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Agent continuation unavailable") from exc


@app.post("/agent/runs/tasks", response_model=CommandResult)
def agent_tasks_command_post(
    request: CommandInput,
    access_token: str = Depends(require_access_token),
) -> CommandResult:
    try:
        return run_tasks_command(access_token, request)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except ToolValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid read-only tool request") from exc
    except AgentModelError as exc:
        raise HTTPException(status_code=503, detail="Agent model unavailable or invalid") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Agent run unavailable") from exc


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


@app.get("/connections/google/calendar/availability", response_model=AvailabilityPreview)
def google_calendar_availability_get(
    days: int = Query(1, ge=1, le=7),
    duration_minutes: int = Query(60, ge=1, le=1440),
    allow_split: bool = Query(False),
    deadline_at: datetime | None = Query(None),
    access_token: str = Depends(require_access_token),
) -> AvailabilityPreview:
    try:
        return build_availability_preview(access_token, days=days,
            duration_minutes=duration_minutes, allow_split=allow_split,
            deadline_at=deadline_at)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except CalendarReconnectRequired as exc:
        raise HTTPException(status_code=409, detail="Reconnect Google with Calendar read access") from exc
    except CalendarProfileRequired as exc:
        raise HTTPException(status_code=409, detail="Save scheduling preferences first") from exc
    except CalendarFetchUnavailable as exc:
        raise HTTPException(status_code=503, detail="Calendar temporarily unavailable") from exc
    except (CalendarFetchError, CalendarEventError, CalendarPlanningError) as exc:
        raise HTTPException(status_code=422, detail="Calendar availability incomplete or invalid") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Calendar availability unavailable") from exc


@app.get("/connections/google/calendar/window", response_model=CalendarWindowStatus)
def google_calendar_window_get(
    start: datetime = Query(...), end: datetime = Query(...),
    access_token: str = Depends(require_access_token),
) -> CalendarWindowStatus:
    try:
        return calendar_window_status(fetch_calendar_window(access_token, start, end))
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except CalendarReconnectRequired as exc:
        raise HTTPException(status_code=409, detail="Reconnect Google with Calendar read access") from exc
    except CalendarFetchUnavailable as exc:
        raise HTTPException(status_code=503, detail="Calendar window unavailable") from exc
    except CalendarFetchError as exc:
        raise HTTPException(status_code=422, detail="Calendar window incomplete or invalid") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Calendar window unavailable") from exc


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


@app.post("/sources/manual", response_model=SourceEnvelope)
def sources_manual_post(
    source: ManualSourceInput,
    request_id: UUID = Header(alias="Idempotency-Key"),
    access_token: str = Depends(require_access_token),
) -> SourceEnvelope:
    try:
        return create_manual_source(access_token, request_id, source)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except SourceConflict as exc:
        raise HTTPException(status_code=409, detail="Source request key conflict") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Source unavailable") from exc


@app.get("/sources", response_model=SourceListEnvelope)
def sources_get(access_token: str = Depends(require_access_token)) -> SourceListEnvelope:
    try:
        return list_sources(access_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Source unavailable") from exc


@app.get("/sources/{source_id}", response_model=SourceEnvelope)
def source_get(source_id: UUID, access_token: str = Depends(require_access_token)) -> SourceEnvelope:
    try:
        source = get_source(access_token, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        return SourceEnvelope(source=source, replayed=False)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Source unavailable") from exc


@app.post("/sources/{source_id}/extract", response_model=ExtractionEnvelopeResponse)
def source_extract_post(source_id: UUID, access_token: str = Depends(require_access_token)) -> ExtractionEnvelopeResponse:
    try:
        return process_extraction(access_token, source_id)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except ExtractionNotFound as exc:
        raise HTTPException(status_code=404, detail="Source not found") from exc
    except ExtractionSourceExpired as exc:
        raise HTTPException(status_code=410, detail="Source text is unavailable") from exc
    except ExtractionRateLimited as exc:
        raise HTTPException(status_code=429, detail="Extraction limit reached") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Extraction unavailable") from exc


@app.get("/sources/{source_id}/extraction", response_model=ExtractionEnvelopeResponse)
def source_extraction_get(source_id: UUID, access_token: str = Depends(require_access_token)) -> ExtractionEnvelopeResponse:
    try:
        result = read_extraction(access_token, source_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Extraction not found")
        return ExtractionEnvelopeResponse(extraction=result, replayed=True)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except ExtractionNotFound as exc:
        raise HTTPException(status_code=404, detail="Source not found") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Extraction unavailable") from exc


@app.post("/extractions/{extraction_id}/confirm", response_model=TaskCreateEnvelope)
def extraction_confirm_post(
    extraction_id: UUID,
    request: ConfirmInput,
    access_token: str = Depends(require_access_token),
) -> TaskCreateEnvelope:
    try:
        return confirm_candidate(access_token, extraction_id, request)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except ConfirmNotFound as exc:
        raise HTTPException(status_code=404, detail="Extraction candidate not found") from exc
    except ConfirmStale as exc:
        raise HTTPException(status_code=409, detail="Extraction source changed or expired") from exc
    except ConfirmConflict as exc:
        raise HTTPException(status_code=409, detail="Candidate already confirmed with different details") from exc
    except ConfirmProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Confirmation unavailable") from exc


@app.post("/extractions/{extraction_id}/ignore", response_model=ExtractionRecord)
def extraction_ignore_post(
    extraction_id: UUID,
    request: IgnoreInput,
    access_token: str = Depends(require_access_token),
) -> ExtractionRecord:
    try:
        return set_extraction_ignored(access_token, extraction_id, request)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except ExtractionNotFound as exc:
        raise HTTPException(status_code=404, detail="Candidate not found") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Review unavailable") from exc


@app.get("/connections/google/gmail/selected", response_model=GmailSelectedPage)
def gmail_selected_get(
    page_token: str | None = Query(default=None, max_length=1024),
    access_token: str = Depends(require_access_token),
) -> GmailSelectedPage:
    try:
        return list_selected_metadata(access_token, page_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except GmailSelectionReconnect as exc:
        raise HTTPException(status_code=409, detail="Reconnect Google with Gmail read access") from exc
    except GmailSelectionMissing as exc:
        raise HTTPException(status_code=404, detail="Create a Gmail label named FocusOS") from exc
    except GmailSelectionUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail temporarily unavailable") from exc
    except GmailSelectionError as exc:
        raise HTTPException(status_code=502, detail="Gmail selection unavailable") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail selection unavailable") from exc


@app.post("/connections/google/gmail/selected/fetch", response_model=SelectedFetchEnvelope)
def gmail_selected_fetch_post(
    request: SelectedFetchInput,
    access_token: str = Depends(require_access_token),
) -> SelectedFetchEnvelope:
    try:
        return fetch_selected_status(access_token, request)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except GmailSelectionReconnect as exc:
        raise HTTPException(status_code=409, detail="Reconnect Google with Gmail read access") from exc
    except GmailSelectionMissing as exc:
        raise HTTPException(status_code=404, detail="Create a Gmail label named FocusOS") from exc
    except GmailSelectionUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail temporarily unavailable") from exc
    except GmailSelectionError as exc:
        raise HTTPException(status_code=422, detail="Selected Gmail messages are invalid or too large") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail temporarily unavailable") from exc


@app.post("/connections/google/gmail/selected/ingest", response_model=GmailIngestEnvelope)
def gmail_selected_ingest_post(
    request: SelectedFetchInput,
    access_token: str = Depends(require_access_token),
) -> GmailIngestEnvelope:
    try:
        return ingest_selected_messages(access_token, request)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except GmailSelectionReconnect as exc:
        raise HTTPException(status_code=409, detail="Reconnect Google with Gmail read access") from exc
    except GmailSelectionMissing as exc:
        raise HTTPException(status_code=404, detail="Create a Gmail label named FocusOS") from exc
    except GmailSelectionUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail temporarily unavailable") from exc
    except (GmailSelectionError, GmailNormalizationError) as exc:
        raise HTTPException(status_code=422, detail="Selected Gmail message could not be imported") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail import unavailable") from exc


@app.post("/connections/google/gmail/process-one", response_model=GmailProcessOne)
def gmail_process_one_post(access_token: str = Depends(require_access_token)) -> GmailProcessOne:
    try:
        return process_one_gmail_source(access_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except ExtractionRateLimited as exc:
        raise HTTPException(status_code=429, detail="Extraction limit reached") from exc
    except (ExtractionNotFound, ExtractionSourceExpired) as exc:
        raise HTTPException(status_code=409, detail="Pending source changed; retry") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail processing unavailable") from exc


@app.post("/connections/google/gmail/sync", response_model=GmailSyncStep)
def gmail_sync_post(access_token: str = Depends(require_access_token)) -> GmailSyncStep:
    try:
        return run_one_sync_page(access_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except GmailSelectionReconnect as exc:
        raise HTTPException(status_code=409, detail="Reconnect Google with Gmail read access") from exc
    except GmailSelectionMissing as exc:
        raise HTTPException(status_code=404, detail="Create a Gmail label named FocusOS") from exc
    except GmailSelectionUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail temporarily unavailable") from exc
    except (GmailSelectionError, GmailNormalizationError) as exc:
        raise HTTPException(status_code=502, detail="Gmail sync stopped on an invalid source") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail sync unavailable") from exc


@app.get("/connections/google/gmail/sync/status", response_model=GmailSyncStatus)
def gmail_sync_status_get(access_token: str = Depends(require_access_token)) -> GmailSyncStatus:
    try:
        return read_gmail_sync_status(access_token)
    except InvalidSession as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail="Gmail sync status unavailable") from exc
