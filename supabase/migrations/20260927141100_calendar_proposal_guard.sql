-- Defense in depth: proposal RPC may only persist a slot from its saved read checkpoint.
create function public.focusos_guard_approval_proposal() returns trigger
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
   where slot->>'start'=v_block->>'start' and slot->>'end'=v_block->>'end')
 then raise exception 'Block is not a saved free slot' using errcode='22023'; end if;
 v_start := (new.payload->>'start')::timestamptz;
 v_end := (new.payload->>'end')::timestamptz;
 if v_start is null or v_end is null or v_start<=now()+interval '1 minute' or v_end<=v_start
 then raise exception 'Invalid approval time' using errcode='22023'; end if;
 return new;
end; $$;
revoke all on function public.focusos_guard_approval_proposal() from public,anon,authenticated;
create trigger approval_proposal_guard before insert on public.approval_requests
 for each row execute function public.focusos_guard_approval_proposal();
