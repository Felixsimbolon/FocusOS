-- Manual task creation writes its source and searchable memory in one transaction.
alter table public.source_items drop constraint source_items_kind_check;
alter table public.source_items add constraint source_items_kind_check
  check (kind in ('manual', 'gmail', 'document', 'task'));

create function public.focusos_create_task_with_memory(
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
revoke all on function public.focusos_create_task_with_memory(uuid,text,jsonb) from public,anon;
grant execute on function public.focusos_create_task_with_memory(uuid,text,jsonb) to authenticated;