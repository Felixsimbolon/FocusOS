-- Standalone Calendar blocks retain owner, saved-slot, and stable-event safeguards.
alter table public.approval_requests alter column task_id drop not null;

create or replace function public.focusos_propose_calendar_action(p_run_id uuid,p_block_index integer)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare
 v_owner uuid := (select auth.uid());
 v_run public.command_runs;
 v_task public.tasks;
 v_connection public.connections;
 v_zone text;
 v_title text;
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
 if v_block->>'task_id' is null then
  v_title := v_block->>'title';
  if v_run.checkpoint->>'entrypoint' is distinct from 'unified'
   or v_run.checkpoint->>'auto_calendar' is distinct from 'true'
   or v_run.checkpoint->>'standalone_title' is distinct from v_title
   or char_length(btrim(coalesce(v_title,''))) not between 1 and 200
   or strpos(lower(v_run.command),lower(v_title))=0
  then raise exception 'Standalone activity changed' using errcode='22023'; end if;
 else
  select * into v_task from public.tasks where id=(v_block->>'task_id')::uuid and user_id=v_owner and status='open';
  if not found or v_task.title is distinct from v_block->>'title' then
   raise exception 'Task changed' using errcode='22023'; end if;
  v_title := v_task.title;
 end if;
 select timezone into v_zone from public.profiles where id=v_owner;
 if v_zone is null then raise exception 'Scheduling profile unavailable' using errcode='22023'; end if;
 v_start := (v_block->>'start')::timestamptz;
 v_end := (v_block->>'end')::timestamptz;
 if v_start<=now()+interval '1 minute' or v_end<=v_start
  or v_end-v_start<interval '15 minutes' or v_end-v_start>interval '480 minutes'
  or (v_task.due_at is not null and v_end>v_task.due_at)
  or (v_task.due_kind='date' and v_end>((v_task.due_date+1)::timestamp at time zone v_zone))
 then raise exception 'Invalid proposed interval' using errcode='22023'; end if;
 select * into v_connection from public.connections where user_id=v_owner and provider='google' and status='connected'
  and granted_scopes @> array['https://www.googleapis.com/auth/calendar.events.owned',
   'https://www.googleapis.com/auth/calendar.events.owned.readonly']::text[];
 if not found then raise exception 'Calendar grant unavailable' using errcode='22023'; end if;
 v_id := gen_random_uuid();
 v_event_id := 'f'||replace(v_id::text,'-','');
 v_payload := jsonb_build_object(
  'schema_version','1','tool','calendar.create_event','run_id',p_run_id,
  'block_index',p_block_index,'task_id',v_task.id,'task_version',v_task.version,
  'connection_id',v_connection.id,'calendar_id','primary','event_id',v_event_id,
  'title',v_title,'start',v_block->>'start','end',v_block->>'end',
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

-- Compare saved Calendar slot instants, not UTC string spellings (Z vs +00:00).
-- Defense in depth: proposal RPC may only persist a slot from its saved read checkpoint.
create or replace function public.focusos_guard_approval_proposal() returns trigger
language plpgsql security definer set search_path=''
as $$
declare v_run public.command_runs; v_block jsonb; v_start timestamptz; v_end timestamptz;
begin
 if new.user_id is distinct from (select auth.uid()) or new.status<>'pending'
  or new.payload->>'schema_version' is distinct from '1'
  or new.payload->>'tool' is distinct from 'calendar.create_event'
  or new.payload->>'run_id' is distinct from new.run_id::text
  or new.payload->>'block_index' is distinct from new.block_index::text
  or new.payload->>'task_id' is distinct from new.task_id::text
  or new.payload->>'connection_id' is distinct from new.connection_id::text
  or new.payload->>'event_id' is distinct from new.event_id
  or new.payload->>'calendar_id' is distinct from 'primary'
  or new.payload->'guests' is distinct from '[]'::jsonb
  or new.payload->>'send_updates' is distinct from 'none'
 then raise exception 'Invalid approval identity' using errcode='22023'; end if;
 select * into v_run from public.command_runs where id=new.run_id and user_id=new.user_id
  and status='succeeded' and expires_at>now();
 if not found or v_run.result->>'status' is distinct from 'proposed'
  or v_run.result->>'actionable' is distinct from 'false'
  or jsonb_typeof(v_run.result->'blocks') is distinct from 'array'
  or jsonb_typeof(v_run.checkpoint->'free_time'->'slots') is distinct from 'array'
 then raise exception 'Run proposal unavailable' using errcode='22023'; end if;
 v_block := v_run.result->'blocks'->new.block_index;
 if v_block is null or v_block->>'task_id' is distinct from new.task_id::text
  or v_block->>'title' is distinct from new.payload->>'title'
  or v_block->>'start' is distinct from new.payload->>'start'
  or v_block->>'end' is distinct from new.payload->>'end'
  or not exists(select 1 from jsonb_array_elements(v_run.checkpoint->'free_time'->'slots') as slot
   where (slot->>'start')::timestamptz=(v_block->>'start')::timestamptz
     and (slot->>'end')::timestamptz=(v_block->>'end')::timestamptz)
 then raise exception 'Block is not a saved free slot' using errcode='22023'; end if;
 if new.task_id is null and (
   v_run.checkpoint->>'entrypoint' is distinct from 'unified'
   or v_run.checkpoint->>'auto_calendar' is distinct from 'true'
   or v_run.checkpoint->>'standalone_title' is distinct from new.payload->>'title'
   or char_length(btrim(coalesce(new.payload->>'title',''))) not between 1 and 200
   or strpos(lower(v_run.command),lower(new.payload->>'title'))=0
   or new.payload->'task_version' is distinct from 'null'::jsonb
   or new.payload->'source_id' is distinct from 'null'::jsonb
 ) then raise exception 'Invalid standalone activity' using errcode='22023'; end if;
 v_start := (new.payload->>'start')::timestamptz;
 v_end := (new.payload->>'end')::timestamptz;
 if v_start is null or v_end is null or v_start<=now()+interval '1 minute' or v_end<=v_start
 then raise exception 'Invalid approval time' using errcode='22023'; end if;
 return new;
end; $$;
