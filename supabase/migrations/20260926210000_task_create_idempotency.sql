-- Phase 3.3: an owner-bound idempotency key makes task creation safe to retry.
alter table public.tasks
  add column create_request_id uuid,
  add column create_request_hash text,
  add constraint tasks_create_request_pair check (
    (create_request_id is null and create_request_hash is null)
    or (
      create_request_id is not null
      and create_request_hash ~ '^[0-9a-f]{64}$'
    )
  );

create unique index tasks_user_create_request_unique
on public.tasks (user_id, create_request_id)
where create_request_id is not null;

create or replace function public.focusos_create_task(
  p_create_request_id uuid,
  p_create_request_hash text,
  p_title text,
  p_description text,
  p_priority text,
  p_due_kind text,
  p_due_date date,
  p_due_at timestamptz,
  p_due_timezone text,
  p_estimate_minutes integer
)
returns table (task jsonb, replayed boolean, stored_request_hash text)
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

  insert into public.tasks (
    user_id, title, description, priority, due_kind, due_date, due_at,
    due_timezone, estimate_minutes, estimate_origin,
    create_request_id, create_request_hash
  )
  values (
    caller_id, p_title, p_description, p_priority, p_due_kind, p_due_date, p_due_at,
    p_due_timezone, p_estimate_minutes,
    case when p_estimate_minutes is null then null else 'explicit' end,
    p_create_request_id, p_create_request_hash
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
      'version', saved_task.version,
      'created_at', saved_task.created_at,
      'updated_at', saved_task.updated_at
    ),
    was_replayed,
    saved_task.create_request_hash;
end;
$$;

revoke all on function public.focusos_create_task(
  uuid, text, text, text, text, text, date, timestamptz, text, integer
) from public, anon;
grant execute on function public.focusos_create_task(
  uuid, text, text, text, text, text, date, timestamptz, text, integer
) to authenticated;
