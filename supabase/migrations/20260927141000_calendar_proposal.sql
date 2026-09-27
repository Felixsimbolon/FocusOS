-- Phase 8.2: propose exactly one persisted plan block. No provider write exists here.
alter table public.approval_requests add constraint approval_payload_hash_exact
 check(payload_hash=encode(sha256(convert_to(payload::text,'UTF8')),'hex'));

create function public.focusos_propose_calendar_action(p_run_id uuid,p_block_index integer)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare
 v_owner uuid := (select auth.uid());
 v_run public.command_runs;
 v_task public.tasks;
 v_connection public.connections;
 v_zone text;
 v_block jsonb;
 v_id uuid;
 v_event_id text;
 v_start timestamptz;
 v_end timestamptz;
 v_payload jsonb;
 v_row public.approval_requests;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_block_index not between 0 and 15 then raise exception 'Invalid block' using errcode='22023'; end if;
 select * into v_row from public.approval_requests where user_id=v_owner and run_id=p_run_id and block_index=p_block_index;
 if found then return to_jsonb(v_row); end if;
 select * into v_run from public.command_runs where id=p_run_id and user_id=v_owner
  and status='succeeded' and expires_at>now();
 if not found or v_run.result->>'status'<>'proposed' or v_run.result->>'actionable'<>'false'
  or jsonb_typeof(v_run.result->'blocks')<>'array'
 then raise exception 'No active proposal' using errcode='22023'; end if;
 v_block := v_run.result->'blocks'->p_block_index;
 if v_block is null or jsonb_typeof(v_block)<>'object' then
  raise exception 'Unknown proposal block' using errcode='22023'; end if;
 select * into v_task from public.tasks where id=(v_block->>'task_id')::uuid and user_id=v_owner and status='open';
 if not found or v_task.title<>v_block->>'title' then
  raise exception 'Task changed' using errcode='22023'; end if;
 if v_task.due_kind='date' then raise exception 'Timed deadline required' using errcode='22023'; end if;
 v_start := (v_block->>'start')::timestamptz;
 v_end := (v_block->>'end')::timestamptz;
 if v_start<=now()+interval '1 minute' or v_end<=v_start
  or v_end-v_start<interval '15 minutes' or v_end-v_start>interval '480 minutes'
  or (v_task.due_at is not null and v_end>v_task.due_at)
 then raise exception 'Invalid proposed interval' using errcode='22023'; end if;
 select * into v_connection from public.connections where user_id=v_owner and provider='google' and status='connected'
  and granted_scopes @> array['https://www.googleapis.com/auth/calendar.events.owned',
   'https://www.googleapis.com/auth/calendar.events.owned.readonly']::text[];
 if not found then raise exception 'Calendar grant unavailable' using errcode='22023'; end if;
 select timezone into v_zone from public.profiles where id=v_owner;
 if v_zone is null then raise exception 'Scheduling profile unavailable' using errcode='22023'; end if;
 v_id := gen_random_uuid();
 v_event_id := 'f'||replace(v_id::text,'-','');
 v_payload := jsonb_build_object(
  'schema_version','1','tool','calendar.create_event','run_id',p_run_id,
  'block_index',p_block_index,'task_id',v_task.id,'task_version',v_task.version,
  'connection_id',v_connection.id,'calendar_id','primary','event_id',v_event_id,
  'title',v_task.title,'start',v_block->>'start','end',v_block->>'end',
  'timezone',v_zone,'source_id',v_task.source_id,'guests','[]'::jsonb,'send_updates','none');
 insert into public.approval_requests(id,user_id,run_id,block_index,task_id,connection_id,
  event_id,payload,payload_hash)
 values(v_id,v_owner,p_run_id,p_block_index,v_task.id,v_connection.id,v_event_id,v_payload,
  encode(sha256(convert_to(v_payload::text,'UTF8')),'hex'))
 on conflict(user_id,run_id,block_index) do nothing;
 select * into v_row from public.approval_requests where user_id=v_owner and run_id=p_run_id and block_index=p_block_index;
 return to_jsonb(v_row);
end; $$;
revoke all on function public.focusos_propose_calendar_action(uuid,integer) from public,anon;
grant execute on function public.focusos_propose_calendar_action(uuid,integer) to authenticated;
