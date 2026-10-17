"""Personal-product diagnostics, history, bounded exports and focus-block management."""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from fastapi.responses import JSONResponse
from focusos_api.job_routes import access
from focusos_api.database import DatabaseUnavailable, InvalidSession, scoped_client
from focusos_api.calendar_cancel import CancellationUnavailable, cancel_focus_block
from focusos_api.token_crypto import TokenCipher, TokenCipherError
from focusos_api.extractor import MODEL
from focusos_api.memory_embeddings import EMBED_MODEL, EMBED_DIM
from focusos_api.profiles import read_profile
from focusos_api import estimates, email_triage, knowledge_graph, weekly_review
from focusos_api.calendar_conflicts import find_conflicts
from focusos_api.calendar_fetch import CalendarFetchError
from focusos_api.google_calendar import CalendarReconnectRequired

router=APIRouter(prefix="/product")
EXPORT_FIELDS={
 "profiles":"timezone,working_hours",
 "projects":"id,name,created_at",
 "tasks":"id,title,description,status,priority,due_kind,due_date,due_at,due_timezone,estimate_minutes,project_id,source_id,version,created_at,updated_at",
 "source_items":"id,kind,title,source_ref,normalized_body,body_hash,received_at,body_expires_at,created_at",
 "memories":"id,source_id,project_id,text,evidence_quote,status,embedding_status,created_at",
 "approval_requests":"id,run_id,task_id,status,payload,provider_link,cancellation_status,created_at",
 "work_sessions":"id,approval_id,task_id,project_id,planned_minutes,actual_minutes,outcome,created_at,updated_at",
}
CHECK_IN_DAYS=7  # blocks that ended within this many days are offered for check-in


class CheckInRejected(Exception):
 pass


class ItemNotFound(Exception):
 pass


class CheckInInput(BaseModel):
 model_config=ConfigDict(extra="forbid",strict=True)
 outcome: Literal["done","partial","skipped"]
 actual_minutes: int|None=Field(default=None,ge=1,le=1440)
 @model_validator(mode="after")
 def minutes_match_outcome(self):
  if (self.outcome=="skipped")!=(self.actual_minutes is None): raise ValueError("Minutes are required unless the block was skipped")
  return self


def protected(fn,*args):
 try: return fn(*args)
 except InvalidSession as exc: raise HTTPException(401,"Authentication required") from exc
 except CancellationUnavailable as exc: raise HTTPException(409,"Only a saved successful FocusOS event can be cancelled") from exc
 except CheckInRejected as exc: raise HTTPException(409,"This block is not open for check-in") from exc
 except ItemNotFound as exc: raise HTTPException(404,"Not found") from exc
 except CalendarReconnectRequired as exc: raise HTTPException(409,"Reconnect Google Calendar to check for conflicts") from exc
 except CalendarFetchError as exc: raise HTTPException(503,"Calendar is unavailable") from exc
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

def usage(token: str) -> dict:
 """Seven days of model usage in the user's timezone, plus the configured daily budget."""
 from focusos_api.observability import cost_configured, daily_token_budget
 profile=read_profile(token)
 with scoped_client(token) as (_,client):
  data=client.rpc("focusos_llm_usage",{"p_days":7,"p_timezone":profile.timezone if profile else "UTC"}).execute().data
 if not isinstance(data,dict): raise DatabaseUnavailable("Usage unavailable")
 budget=daily_token_budget()
 return {**data,"timezone":profile.timezone if profile else "UTC","daily_token_budget":budget or None,
   "budget_used_ratio":round(data.get("today_tokens",0)/budget,4) if budget else None,
   "cost_configured":cost_configured()}

def pending_check_ins(token: str, now: datetime|None=None) -> list[dict]:
 """FocusOS blocks that have started, ended within a week, and have no check-in yet."""
 current=now or datetime.now(timezone.utc)
 with scoped_client(token) as (owner,client):
  blocks=client.table("approval_requests").select("id,task_id,status,payload,cancellation_status").eq("user_id",owner).eq("status","succeeded").order("created_at",desc=True).limit(100).execute().data
  done=client.table("work_sessions").select("approval_id").eq("user_id",owner).gte("created_at",(current-timedelta(days=CHECK_IN_DAYS+1)).isoformat()).limit(200).execute().data
 if not isinstance(blocks,list) or not isinstance(done,list): raise DatabaseUnavailable("Check-ins unavailable")
 checked={str(row.get("approval_id")) for row in done if isinstance(row,dict)}
 pending=[]
 for row in blocks:
  payload=row.get("payload") if isinstance(row,dict) else None
  if not isinstance(payload,dict) or row.get("cancellation_status")=="cancelled" or str(row.get("id")) in checked: continue
  try: start=datetime.fromisoformat(payload["start"]); end=datetime.fromisoformat(payload["end"])
  except (KeyError,TypeError,ValueError): continue
  if start>current or end<current-timedelta(days=CHECK_IN_DAYS): continue
  pending.append({"id":row["id"],"task_id":row.get("task_id"),"title":payload.get("title"),"start":payload["start"],"end":payload["end"],
   "timezone":payload.get("timezone"),"planned_minutes":max(1,round((end-start).total_seconds()/60))})
 return sorted(pending,key=lambda item:item["start"])[:10]


def record_check_in(token: str,action_id: UUID,check_in: CheckInInput) -> dict:
 try:
  with scoped_client(token) as (_,client):
   return client.rpc("focusos_record_work_session",{"p_approval_id":str(action_id),"p_outcome":check_in.outcome,
    "p_actual_minutes":check_in.actual_minutes}).execute().data
 except DatabaseUnavailable as exc:
  # The RPC refuses blocks that are not the caller's, not finished, cancelled or too old.
  if getattr(exc.__cause__,"code",None) in ("P0002","22023"): raise CheckInRejected() from exc
  raise


@router.get("/diagnostics")
def diag(token: str=Depends(access)): return protected(diagnostics,token)
@router.get("/usage")
def usage_route(token: str=Depends(access)): return protected(usage,token)
@router.get("/history")
def runs(token: str=Depends(access)): return protected(history,token)
@router.get("/export")
def export(token: str=Depends(access)):
 return JSONResponse(protected(export_data,token),headers={"Cache-Control":"no-store","Content-Disposition":"attachment; filename=focusos-export.json"})
@router.get("/focus-blocks")
def blocks(token: str=Depends(access)): return protected(focus_blocks,token)
@router.get("/estimates")
def estimates_route(token: str=Depends(access)): return protected(estimates.summary,token)
class TriageInput(BaseModel):
 model_config=ConfigDict(extra="forbid",strict=True)
 priority: Literal["urgent","normal","fyi"]


def correct_triage(token: str,source_id: UUID,triage: TriageInput) -> dict:
 try: return email_triage.save(token,source_id,triage.priority,None,True)
 except DatabaseUnavailable as exc:
  if getattr(exc.__cause__,"code",None)=="P0002": raise ItemNotFound() from exc
  raise


WEEKS={"current":0,"previous":-1}
@router.get("/review/{which}")
def review_read(which: Literal["current","previous"],token: str=Depends(access)): return protected(weekly_review.read_review,token,WEEKS[which])
@router.post("/review/{which}")
def review_generate(which: Literal["current","previous"],token: str=Depends(access)): return protected(weekly_review.generate_review,token,WEEKS[which])
@router.get("/graph")
def graph_stats(token: str=Depends(access)): return protected(knowledge_graph.stats,token)
@router.post("/graph/backfill")
def graph_backfill(token: str=Depends(access)): return protected(knowledge_graph.backfill,token)
@router.get("/triage")
def triage_list(token: str=Depends(access)): return protected(email_triage.recent,token)
@router.post("/triage/{source_id}")
def triage_correct(source_id: UUID,triage: TriageInput,token: str=Depends(access)): return protected(correct_triage,token,source_id,triage)
def calendar_month(token: str,month: str) -> dict:
 from focusos_api.calendar_month import MonthOutOfRange,month_events
 try: return month_events(token,month)
 except MonthOutOfRange as exc: raise ItemNotFound() from exc


@router.get("/calendar/{month}")
def calendar_month_route(month: str=Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),token: str=Depends(access)): return protected(calendar_month,token,month)
@router.get("/conflicts")
def conflicts(token: str=Depends(access)): return protected(find_conflicts,token)
@router.get("/check-ins")
def check_ins(token: str=Depends(access)): return protected(pending_check_ins,token)
@router.post("/focus-blocks/{action_id}/check-in")
def check_in(action_id: UUID,check_in_input: CheckInInput,token: str=Depends(access)): return protected(record_check_in,token,action_id,check_in_input)
@router.post("/focus-blocks/{action_id}/cancel")
def cancel(action_id: UUID,token: str=Depends(access)): return protected(cancel_focus_block,token,action_id)
