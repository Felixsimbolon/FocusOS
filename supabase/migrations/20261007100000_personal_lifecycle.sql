-- Keep memory for manually created tasks current without rewriting Gmail evidence.
create function public.focusos_refresh_task_memory() returns trigger language plpgsql security definer set search_path='' as $$
declare s public.source_items; body text; hash text;
begin
 if row(new.title,new.description,new.status,new.priority,new.due_kind,new.due_date,new.due_at,new.estimate_minutes,new.project_id)
 is not distinct from row(old.title,old.description,old.status,old.priority,old.due_kind,old.due_date,old.due_at,old.estimate_minutes,old.project_id) then return new; end if;
 select * into s from public.source_items where id=new.source_id and user_id=new.user_id and kind='task' and deleted_at is null for update;
 if s.id is null then return new; end if;
 body:='Task: '||new.title||E'\nStatus: '||new.status||E'\nPriority: '||new.priority
 ||case when new.due_kind='date' then E'\nDue date: '||new.due_date::text when new.due_kind='datetime' then E'\nDue at: '||new.due_at::text else '' end
 ||coalesce(E'\nEstimate minutes: '||new.estimate_minutes::text,'')||coalesce(E'\nDetails: '||new.description,'');
 hash:=encode(pg_catalog.sha256(pg_catalog.convert_to(body,'UTF8')),'hex');
 update public.source_items set title=new.title,normalized_body=body,body_hash=hash,content_version=content_version+1,body_expires_at=now()+interval '30 days'
 where id=s.id and user_id=new.user_id;
 update public.memories set text=left(body,500),evidence_quote=new.title,source_hash=hash,project_id=new.project_id,
 embedding=null,embedding_status='pending',embedding_model=null,embedding_dim=null,embedding_hash=null,
 embedding_error=null,embedding_lease_token=null,embedding_lease_until=null,embedding_updated_at=null,updated_at=now()
 where source_id=s.id and user_id=new.user_id and request_key=new.create_request_id;
 return new;
end; $$;
revoke all on function public.focusos_refresh_task_memory() from public,anon,authenticated;
create trigger task_memory_refresh after update of title,description,status,priority,due_kind,due_date,due_at,estimate_minutes,project_id
 on public.tasks for each row execute function public.focusos_refresh_task_memory();

alter table public.approval_requests add column cancellation_status text not null default 'none'
 check(cancellation_status in ('none','running','cancelled','unknown','changed')),
 add column cancellation_lease uuid,add column cancellation_lease_until timestamptz,
 add column cancellation_error text;
grant select(cancellation_status,cancellation_error) on public.approval_requests to authenticated;
create function public.focusos_claim_calendar_cancellation(p_id uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare a public.approval_requests;
begin
 if (select auth.uid()) is null then raise exception 'Authentication required' using errcode='28000'; end if;
 select * into a from public.approval_requests where id=p_id and user_id=(select auth.uid()) and status='succeeded' for update;
 if a.id is null then return null; end if;
 if a.cancellation_status in ('cancelled','changed') or a.cancellation_status='running' and a.cancellation_lease_until>now()
 then return jsonb_build_object('claimed',false,'status',a.cancellation_status); end if;
 update public.approval_requests set cancellation_status='running',cancellation_lease=gen_random_uuid(),cancellation_lease_until=now()+interval '90 seconds',cancellation_error=null
 where id=a.id returning * into a;
 return jsonb_build_object('claimed',true,'approval',to_jsonb(a),'lease',a.cancellation_lease);
end; $$;
revoke all on function public.focusos_claim_calendar_cancellation(uuid) from public,anon;
grant execute on function public.focusos_claim_calendar_cancellation(uuid) to authenticated;
create function public.focusos_finish_calendar_cancellation(p_id uuid,p_lease uuid,p_status text,p_error text) returns boolean
language plpgsql security definer set search_path='' as $$
declare n integer;
begin
 if (select auth.uid()) is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_status not in ('cancelled','unknown','changed') or p_error is not null and p_error !~ '^[a-z_]{1,64}$' then raise exception 'Invalid cancellation result' using errcode='22023'; end if;
 update public.approval_requests set cancellation_status=p_status,cancellation_error=p_error,cancellation_lease=null,cancellation_lease_until=null
 where id=p_id and user_id=(select auth.uid()) and cancellation_status='running' and cancellation_lease=p_lease and cancellation_lease_until>now();
 get diagnostics n=row_count; return n=1;
end; $$;
revoke all on function public.focusos_finish_calendar_cancellation(uuid,uuid,text,text) from public,anon;
grant execute on function public.focusos_finish_calendar_cancellation(uuid,uuid,text,text) to authenticated;

create or replace function public.focusos_create_task_with_memory(
  p_request_id uuid, p_request_hash text, p_task jsonb
) returns jsonb language plpgsql volatile security definer set search_path=''
as $$
declare
  v_owner uuid := (select auth.uid());
  v_created record;
  v_task public.tasks;
  v_source_response jsonb;
  v_source_id uuid;
  v_memory public.memories;
  v_memory_response jsonb;
  v_body text;
  v_memory_text text;
  v_title text;
begin
  if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
  if p_request_id is null or p_request_hash !~ '^[0-9a-f]{64}$' or jsonb_typeof(p_task)<>'object'
    then raise exception 'Invalid task request' using errcode='22023'; end if;

  select * into v_created from public.focusos_create_task(
    p_request_id, p_request_hash, p_task->>'title', p_task->>'description',
    p_task->>'priority', p_task->>'due_kind', (p_task->>'due_date')::date,
    (p_task->>'due_at')::timestamptz, p_task->>'due_timezone',
    (p_task->>'estimate_minutes')::integer, (p_task->>'project_id')::uuid
  );
  if not v_created.project_available then
    return jsonb_build_object('task',null,'replayed',false,'stored_request_hash',p_request_hash,
      'project_available',false);
  end if;
  if v_created.stored_request_hash is distinct from p_request_hash then
    return jsonb_build_object('task',null,'replayed',true,
      'stored_request_hash',v_created.stored_request_hash,'project_available',true);
  end if;
  select * into v_task from public.tasks
    where id=(v_created.task->>'id')::uuid and user_id=v_owner for update;
  if v_task.id is null then raise exception 'Task unavailable' using errcode='22023'; end if;

  if v_created.replayed and v_task.source_id is not null then
    select * into v_memory from public.memories where user_id=v_owner and source_id=v_task.source_id and request_key=p_request_id;
    if v_memory.id is null then raise exception 'Task memory unavailable' using errcode='22023'; end if;
    return jsonb_build_object('task',to_jsonb(v_task)-'user_id'-'create_request_id'-'create_request_hash',
      'memory_id',v_memory.id,'replayed',true,'stored_request_hash',v_created.stored_request_hash,'project_available',true);
  end if;
  -- Keep the user's original input as the evidence for this memory.
  v_title := btrim(p_task->>'title');
  v_body := 'Task: ' || v_title
    || coalesce(E'\nDetails: ' || nullif(btrim(p_task->>'description'),''),'')
    || case when p_task->>'due_kind'='date' then E'\nDue date: ' || (p_task->>'due_date')
            when p_task->>'due_kind'='datetime' then E'\nDue at: ' || (p_task->>'due_at')
            else '' end;
  v_memory_text := left(v_body,500);
  v_source_response := public.focusos_create_manual_source(
    p_request_id, p_request_hash, v_title, v_body,
    encode(pg_catalog.sha256(pg_catalog.convert_to(v_body,'UTF8')),'hex'), now()
  );
  if v_source_response->>'conflict'='true' then
    raise exception 'Source request conflict' using errcode='23505'; end if;
  v_source_id := (v_source_response->'source'->>'id')::uuid;
  if v_source_id is null then raise exception 'Task source unavailable' using errcode='22023'; end if;
  update public.source_items set kind='task' where id=v_source_id and user_id=v_owner and kind='manual';

  select * into v_memory from public.memories
    where user_id=v_owner and request_key=p_request_id for update;
  if v_memory.id is null then
    v_memory_response := public.focusos_confirm_memory(
      p_request_id,v_source_id,(p_task->>'project_id')::uuid,v_memory_text,v_title);
    select * into v_memory from public.memories
      where id=(v_memory_response->>'id')::uuid and user_id=v_owner;
  elsif v_memory.source_id<>v_source_id
     or v_memory.project_id is distinct from (p_task->>'project_id')::uuid
     or v_memory.text<>v_memory_text or v_memory.evidence_quote<>v_title then
    raise exception 'Memory request conflict' using errcode='23505';
  end if;
  if v_memory.id is null then raise exception 'Task memory unavailable' using errcode='22023'; end if;
  if v_task.source_id is not null and v_task.source_id<>v_source_id then
    raise exception 'Task source conflict' using errcode='23505'; end if;
  update public.tasks set source_id=v_source_id
    where id=v_task.id and user_id=v_owner and source_id is null;
  select * into v_task from public.tasks where id=v_task.id and user_id=v_owner;
  return jsonb_build_object('task',v_created.task || jsonb_build_object(
      'source_id',v_source_id,'version',v_task.version,'updated_at',v_task.updated_at),
    'memory_id',v_memory.id,'replayed',v_created.replayed,
    'stored_request_hash',v_created.stored_request_hash,'project_available',true);
end; $$;
