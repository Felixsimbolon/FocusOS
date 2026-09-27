-- Phase 8.1: an approval is one immutable proposed Calendar event.
create unique index connections_owner_id_for_approvals on public.connections(user_id,id);

create table public.approval_requests (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 run_id uuid not null,
 block_index integer not null check(block_index between 0 and 15),
 task_id uuid not null,
 connection_id uuid not null,
 calendar_id text not null default 'primary' check(calendar_id='primary'),
 event_id text not null check(event_id ~ '^[a-v0-9]{5,1024}$'),
 payload jsonb not null check(jsonb_typeof(payload)='object' and pg_column_size(payload)<=8192),
 payload_hash text not null check(payload_hash ~ '^[0-9a-f]{64}$'),
 status text not null default 'pending' check(status in ('pending','approved','rejected','expired','executing','succeeded','failed','unknown','stale')),
 status_version integer not null default 1 check(status_version>0),
 expires_at timestamptz not null default now()+interval '20 minutes',
 lease_until timestamptz,
 provider_event_id text,
 provider_link text,
 safe_code text check(safe_code is null or char_length(safe_code)<=80),
 created_at timestamptz not null default now(),
 decided_at timestamptz,
 updated_at timestamptz not null default now(),
 constraint approval_owned_run foreign key(user_id,run_id) references public.command_runs(user_id,id) on delete cascade,
 constraint approval_owned_task foreign key(user_id,task_id) references public.tasks(user_id,id),
 constraint approval_owned_connection foreign key(user_id,connection_id) references public.connections(user_id,id),
 unique(user_id,run_id,block_index),
 unique(user_id,calendar_id,event_id)
);
create index approval_owner_status_created on public.approval_requests(user_id,status,created_at desc);
alter table public.approval_requests enable row level security;
revoke all on public.approval_requests from public,anon,authenticated;
grant select(id,user_id,run_id,block_index,task_id,connection_id,calendar_id,event_id,payload,payload_hash,status,status_version,expires_at,lease_until,provider_event_id,provider_link,safe_code,created_at,decided_at,updated_at)
 on public.approval_requests to authenticated;
create policy approval_read_own on public.approval_requests for select to authenticated using ((select auth.uid())=user_id);

create function public.focusos_approval_immutable() returns trigger
language plpgsql security definer set search_path=''
as $$
begin
 if row(new.user_id,new.run_id,new.block_index,new.task_id,new.connection_id,new.calendar_id,new.event_id,new.payload,new.payload_hash,new.expires_at)
    is distinct from
    row(old.user_id,old.run_id,old.block_index,old.task_id,old.connection_id,old.calendar_id,old.event_id,old.payload,old.payload_hash,old.expires_at)
 then raise exception 'Approval payload is immutable' using errcode='22023'; end if;
 new.updated_at := now();
 return new;
end; $$;
revoke all on function public.focusos_approval_immutable() from public,anon,authenticated;
create trigger approval_immutable before update on public.approval_requests
 for each row execute function public.focusos_approval_immutable();
