-- Check-ins after FocusOS blocks: how long the work really took. Adaptive estimates
-- read these rows; nothing here changes Calendar or task data.
create table public.work_sessions (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 approval_id uuid not null references public.approval_requests(id) on delete cascade,
 task_id uuid,
 project_id uuid,
 planned_minutes integer not null check(planned_minutes between 1 and 1440),
 -- done: minutes the work took; partial: minutes spent plus minutes still needed; skipped: null.
 actual_minutes integer check(actual_minutes is null or actual_minutes between 1 and 1440),
 outcome text not null check(outcome in ('done','partial','skipped')),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique(user_id,approval_id),
 check((outcome='skipped')=(actual_minutes is null))
);
create index work_sessions_owner_created on public.work_sessions(user_id,created_at desc);
alter table public.work_sessions enable row level security;
revoke all on public.work_sessions from public,anon,authenticated;
grant select(id,user_id,approval_id,task_id,project_id,planned_minutes,actual_minutes,outcome,created_at,updated_at)
 on public.work_sessions to authenticated;
create policy work_sessions_read_owner on public.work_sessions for select to authenticated using(user_id=(select auth.uid()));

-- One check-in per block; a second call corrects the first.
create function public.focusos_record_work_session(p_approval_id uuid,p_outcome text,p_actual_minutes integer)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_block record; v_planned integer; v_project uuid; v_row public.work_sessions;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_outcome is null or p_outcome not in ('done','partial','skipped')
   or (p_outcome='skipped' and p_actual_minutes is not null)
   or (p_outcome<>'skipped' and (p_actual_minutes is null or p_actual_minutes not between 1 and 1440))
 then raise exception 'Invalid check-in' using errcode='22023'; end if;
 select a.id,a.task_id,(a.payload->>'start')::timestamptz as starts_at,(a.payload->>'end')::timestamptz as ends_at
 into v_block from public.approval_requests a
 where a.id=p_approval_id and a.user_id=v_owner and a.status='succeeded'
   and a.cancellation_status is distinct from 'cancelled';
 if not found then raise exception 'Focus block not found' using errcode='P0002'; end if;
 -- A block can be checked in once it has started, and for 30 days after it ends.
 if v_block.starts_at>now() or v_block.ends_at<now()-interval '30 days'
 then raise exception 'Focus block is not open for check-in' using errcode='22023'; end if;
 v_planned := greatest(1,least(1440,(extract(epoch from (v_block.ends_at-v_block.starts_at))/60)::integer));
 if v_block.task_id is not null then
   select t.project_id into v_project from public.tasks t where t.id=v_block.task_id and t.user_id=v_owner;
 end if;
 insert into public.work_sessions(user_id,approval_id,task_id,project_id,planned_minutes,actual_minutes,outcome)
 values(v_owner,v_block.id,v_block.task_id,v_project,v_planned,p_actual_minutes,p_outcome)
 on conflict(user_id,approval_id) do update set actual_minutes=excluded.actual_minutes,outcome=excluded.outcome,
   project_id=excluded.project_id,updated_at=now()
 returning * into v_row;
 return pg_catalog.jsonb_build_object('approval_id',v_row.approval_id,'outcome',v_row.outcome,
   'planned_minutes',v_row.planned_minutes,'actual_minutes',v_row.actual_minutes);
end; $$;
revoke all on function public.focusos_record_work_session(uuid,text,integer) from public,anon;
grant execute on function public.focusos_record_work_session(uuid,text,integer) to authenticated;
