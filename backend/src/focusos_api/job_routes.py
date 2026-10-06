"""Owned job API and a secret-protected scheduler tick; no credentials in responses."""
import hmac
import os
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from focusos_api.database import DatabaseUnavailable, InvalidSession
from focusos_api.token_crypto import TokenCipherError
from focusos_api.jobs import JobInput, JobRecord, JobNotFound, JobLimit, JobConflict, enqueue_job, get_job, list_jobs, cancel_job, work_owned, work_one
router = APIRouter()
bearer = HTTPBearer(auto_error=False)
def access(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != "bearer": raise HTTPException(401, "Authentication required")
    return credentials.credentials

def call(fn, *args):
    try: return fn(*args)
    except InvalidSession as exc: raise HTTPException(401, "Sign in again") from exc
    except JobNotFound as exc: raise HTTPException(404, "Job not found") from exc
    except JobConflict as exc: raise HTTPException(409, "Job request changed") from exc
    except JobLimit as exc: raise HTTPException(429, "Job limit reached") from exc
    except (DatabaseUnavailable, TokenCipherError) as exc: raise HTTPException(503, "Background processing unavailable") from exc

@router.post("/jobs", response_model=JobRecord, status_code=202)
def create(request: JobInput, token: str = Depends(access)): return call(enqueue_job, token, request)
@router.get("/jobs", response_model=list[JobRecord])
def listing(token: str = Depends(access)): return call(list_jobs, token)
@router.get("/jobs/{job_id}", response_model=JobRecord)
def read(job_id: UUID, token: str = Depends(access)): return call(get_job, token, job_id)
@router.post("/jobs/{job_id}/work", response_model=JobRecord)
def work(job_id: UUID, token: str = Depends(access)): return call(work_owned, token, job_id)
@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: UUID, token: str = Depends(access)): return {"cancelled": call(cancel_job, token, job_id)}
@router.get("/internal/jobs/tick")
@router.post("/internal/jobs/tick")
def tick(authorization: str | None = Header(default=None)):
    secret = os.environ.get("FOCUSOS_WORKER_SECRET", "")
    if len(secret) < 32: raise HTTPException(503, "Worker trigger is not configured")
    if not authorization or not hmac.compare_digest(authorization, "Bearer " + secret): raise HTTPException(401, "Worker authentication required")
    return call(work_one)
