"""Personal-product diagnostics, history, bounded exports and focus-block management."""
import json
import os
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from focusos_api.job_routes import access
from focusos_api.database import DatabaseUnavailable, InvalidSession, scoped_client
from focusos_api.calendar_cancel import CancellationUnavailable, cancel_focus_block
from focusos_api.token_crypto import TokenCipher, TokenCipherError
from focusos_api.extractor import MODEL
from focusos_api.memory_embeddings import EMBED_MODEL, EMBED_DIM

router=APIRouter(prefix="/product")
EXPORT_FIELDS={
 "profiles":"timezone,working_hours",
 "projects":"id,name,created_at",
 "tasks":"id,title,description,status,priority,due_kind,due_date,due_at,due_timezone,estimate_minutes,project_id,source_id,version,created_at,updated_at",
 "source_items":"id,kind,title,source_ref,normalized_body,body_hash,received_at,body_expires_at,created_at",
 "memories":"id,source_id,project_id,text,evidence_quote,status,embedding_status,created_at",
 "approval_requests":"id,run_id,task_id,status,payload,provider_link,cancellation_status,created_at",
}


def protected(fn,*args):
 try: return fn(*args)
 except InvalidSession as exc: raise HTTPException(401,"Authentication required") from exc
 except CancellationUnavailable as exc: raise HTTPException(409,"Only a saved successful FocusOS event can be cancelled") from exc
 except DatabaseUnavailable as exc: raise HTTPException(503,"Product data unavailable") from exc


def diagnostics(token: str) -> dict:
 with scoped_client(token) as (owner,client):
  client.table("profiles").select("timezone").eq("id",owner).limit(1).execute()
  try:
   client.table("work_jobs").select("id").eq("user_id",owner).limit(1).execute()
   queue_ready=True
  except Exception: queue_ready=False
  try:
   client.table("approval_requests").select("cancellation_status").eq("user_id",owner).limit(1).execute()
   lifecycle_ready=True
  except Exception: lifecycle_ready=False
 try: TokenCipher.from_environment(); encryption=True
 except TokenCipherError: encryption=False
 settings={name:bool(os.environ.get(name,"").strip()) for name in (
   "GEMINI_API_KEY","FOCUSOS_SUPABASE_SERVICE_ROLE_KEY","FOCUSOS_GOOGLE_CLIENT_ID","FOCUSOS_GOOGLE_CLIENT_SECRET")}
 return {"database":"reachable", "queue_ready":queue_ready,"lifecycle_ready":lifecycle_ready,
   "configured":settings,"encryption_ready":encryption,"worker_trigger_configured":len(os.environ.get("FOCUSOS_WORKER_SECRET",""))>=32,
   "generation_model":MODEL,"embedding_model":EMBED_MODEL,"embedding_dimensions":EMBED_DIM,
   "provider_live_tested":False,"session_job_limit_minutes":15,"export_schema_version":1}


def export_data(token: str) -> dict:
 tables={};truncated={}
 with scoped_client(token) as (owner,client):
  for table,fields in EXPORT_FIELDS.items():
   query=client.table(table).select(fields).eq("id" if table=="profiles" else "user_id",owner)
   if table!="profiles": query=query.order("created_at").order("id")
   rows=query.limit(1001).execute().data
   if not isinstance(rows,list): raise DatabaseUnavailable("Export unavailable")
   tables[table]=rows[:1000];truncated[table]=len(rows)>1000
 result={"schema_version":1,"exported_at":datetime.now(timezone.utc).isoformat(),"tables":tables,"truncated":truncated,
   "note":"Application data only. No OAuth/session credentials, embeddings, queue tokens or database secrets. Calendar events are not recreated by this export."}
 if len(json.dumps(result).encode())>8_000_000: raise DatabaseUnavailable("Export exceeds safe size")
 return result


def history(token: str):
 with scoped_client(token) as (owner,client):
  return client.table("command_runs").select("id,command,status,stage,safe_error,model_turns,tool_calls_count,created_at,updated_at,expires_at").eq("user_id",owner).order("created_at",desc=True).limit(50).execute().data


def focus_blocks(token: str):
 with scoped_client(token) as (owner,client):
  rows=client.table("approval_requests").select("id,run_id,task_id,status,payload,provider_link,safe_code,cancellation_status,cancellation_error,created_at").eq("user_id",owner).order("created_at",desc=True).limit(100).execute().data
 return rows

@router.get("/diagnostics")
def diag(token: str=Depends(access)): return protected(diagnostics,token)
@router.get("/history")
def runs(token: str=Depends(access)): return protected(history,token)
@router.get("/export")
def export(token: str=Depends(access)):
 return JSONResponse(protected(export_data,token),headers={"Cache-Control":"no-store","Content-Disposition":"attachment; filename=focusos-export.json"})
@router.get("/focus-blocks")
def blocks(token: str=Depends(access)): return protected(focus_blocks,token)
@router.post("/focus-blocks/{action_id}/cancel")
def cancel(action_id: UUID,token: str=Depends(access)): return protected(cancel_focus_block,token,action_id)
