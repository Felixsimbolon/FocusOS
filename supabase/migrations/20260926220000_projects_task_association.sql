-- Phase 3.5: typed relational projects and same-owner task association.
create table public.projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 100),
  normalized_name text generated always as (lower(btrim(name))) stored,
  created_at timestamptz not null default now(),
  constraint projects_user_id_normalized_name_unique unique (user_id, normalized_name),
  constraint projects_user_id_id_unique unique (user_id, id)
);

alter table public.tasks add column project_id uuid;
alter table public.tasks
  add constraint tasks_owner_project_fk
  foreign key (user_id, project_id)
  references public.projects (user_id, id)
  on delete set null (project_id);

create index tasks_user_project_idx on public.tasks (user_id, project_id);

grant select (project_id) on public.tasks to authenticated;
alter table public.projects enable row level security;
revoke all on table public.projects from public, anon, authenticated;
grant select (id, user_id, name, normalized_name, created_at) on public.projects to authenticated;

create policy focusos_projects_select_own
on public.projects for select to authenticated
using ((select auth.uid()) = user_id);

create function public.focusos_create_project(p_name text)
returns table (project jsonb, existing boolean)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  caller_id uuid := auth.uid();
  saved_project public.projects;
  was_existing boolean := false;
begin
  if caller_id is null then
    raise exception 'Authentication required';
  end if;

  insert into public.projects (user_id, name)
  values (caller_id, pg_catalog.btrim(p_name))
  on conflict (user_id, normalized_name) do nothing
  returning * into saved_project;

  if not found then
    was_existing := true;
    select * into saved_project
    from public.projects
    where user_id = caller_id
      and normalized_name = pg_catalog.lower(pg_catalog.btrim(p_name));
  end if;

  if saved_project.id is null then
    raise exception 'Project request could not be resolved';
  end if;

  return query
  select pg_catalog.jsonb_build_object(
    'id', saved_project.id,
    'name', saved_project.name,
    'created_at', saved_project.created_at
  ), was_existing;
end;
$$;

revoke all on function public.focusos_create_project(text) from public, anon;
grant execute on function public.focusos_create_project(text) to authenticated;

drop function public.focusos_create_task(
  uuid, text, text, text, text, text, date, timestamptz, text, integer
);

create function public.focusos_create_task(
  p_create_request_id uuid,
  p_create_request_hash text,
  p_title text,
  p_description text,
  p_priority text,
  p_due_kind text,
  p_due_date date,
  p_due_at timestamptz,
  p_due_timezone text,
  p_estimate_minutes integer,
  p_project_id uuid
)
returns table (task jsonb, replayed boolean, stored_request_hash text, project_available boolean)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  caller_id uuid := auth.uid();
  saved_task public.tasks;
  was_replayed boolean := false;
begin
  if caller_id is null then
    raise exception 'Authentication required';
  end if;

  if p_project_id is not null and not exists (
    select 1 from public.projects
    where id = p_project_id and user_id = caller_id
  ) then
    return query select null::jsonb, false, null::text, false;
    return;
  end if;

  insert into public.tasks (
    user_id, title, description, priority, due_kind, due_date, due_at,
    due_timezone, estimate_minutes, estimate_origin,
    create_request_id, create_request_hash, project_id
  )
  values (
    caller_id, p_title, p_description, p_priority, p_due_kind, p_due_date, p_due_at,
    p_due_timezone, p_estimate_minutes,
    case when p_estimate_minutes is null then null else 'explicit' end,
    p_create_request_id, p_create_request_hash, p_project_id
  )
  on conflict (user_id, create_request_id) where create_request_id is not null do nothing
  returning * into saved_task;

  if not found then
    was_replayed := true;
    select * into saved_task
    from public.tasks
    where user_id = caller_id and create_request_id = p_create_request_id
    for update;
  end if;

  if saved_task.id is null then
    raise exception 'Task request could not be resolved';
  end if;

  return query
  select
    pg_catalog.jsonb_build_object(
      'id', saved_task.id,
      'title', saved_task.title,
      'description', saved_task.description,
      'status', saved_task.status,
      'priority', saved_task.priority,
      'due_kind', saved_task.due_kind,
      'due_date', saved_task.due_date,
      'due_at', saved_task.due_at,
      'due_timezone', saved_task.due_timezone,
      'estimate_minutes', saved_task.estimate_minutes,
      'estimate_origin', saved_task.estimate_origin,
      'project_id', saved_task.project_id,
      'version', saved_task.version,
      'created_at', saved_task.created_at,
      'updated_at', saved_task.updated_at
    ),
    was_replayed,
    saved_task.create_request_hash,
    true;
end;
$$;

revoke all on function public.focusos_create_task(
  uuid, text, text, text, text, text, date, timestamptz, text, integer, uuid
) from public, anon;
grant execute on function public.focusos_create_task(
  uuid, text, text, text, text, text, date, timestamptz, text, integer, uuid
) to authenticated;
