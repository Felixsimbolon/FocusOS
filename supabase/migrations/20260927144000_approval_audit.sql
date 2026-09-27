-- Phase 8.7: append-only, owner-readable status trail; no secrets or event body.
alter table public.approval_requests add constraint approvals_owner_id_unique unique(user_id,id);
create table public.approval_action_events (
 id bigint generated always as identity primary key,
 user_id uuid not null,
 run_id uuid not null,
 approval_id uuid not null,
 block_index integer not null,
 status text not null check(status in ('pending','approved','rejected','expired','executing','succeeded','failed','unknown','stale')),
 status_version integer not null check(status_version>0),
 safe_code text,
 occurred_at timestamptz not null default now(),
 unique(approval_id,status_version),
 constraint action_event_owned_approval foreign key(user_id,approval_id)
  references public.approval_requests(user_id,id) on delete cascade
);
create index action_events_run_idx on public.approval_action_events(user_id,run_id,occurred_at,id);
alter table public.approval_action_events enable row level security;
revoke all on public.approval_action_events from public,anon,authenticated;
grant select(id,run_id,approval_id,block_index,status,status_version,safe_code,occurred_at)
 on public.approval_action_events to authenticated;
create policy action_event_read_own on public.approval_action_events for select to authenticated
 using((select auth.uid())=user_id);

create function public.focusos_record_approval_transition() returns trigger
language plpgsql security definer set search_path=''
as $$
begin
 if tg_op='INSERT' or new.status is distinct from old.status then
  insert into public.approval_action_events(user_id,run_id,approval_id,block_index,status,status_version,safe_code,occurred_at)
  values(new.user_id,new.run_id,new.id,new.block_index,new.status,new.status_version,new.safe_code,
   case when tg_op='INSERT' then new.created_at else new.updated_at end);
 end if;
 return new;
end; $$;
revoke all on function public.focusos_record_approval_transition() from public,anon,authenticated;
create trigger approval_action_insert after insert on public.approval_requests
 for each row execute function public.focusos_record_approval_transition();
create trigger approval_action_update after update of status on public.approval_requests
 for each row execute function public.focusos_record_approval_transition();
insert into public.approval_action_events(user_id,run_id,approval_id,block_index,status,status_version,safe_code,occurred_at)
select user_id,run_id,id,block_index,status,status_version,safe_code,updated_at
from public.approval_requests on conflict(approval_id,status_version) do nothing;
