-- Phase 3.6: compare-and-swap updates and a timezone-aware Today query.
create function public.focusos_task_json(p_task public.tasks)
returns jsonb
language sql
immutable
security invoker
set search_path = ''
as $$
  select pg_catalog.jsonb_build_object(
    'id', p_task.id,
    'title', p_task.title,
    'description', p_task.description,
    'status', p_task.status,
    'priority', p_task.priority,
    'due_kind', p_task.due_kind,
    'due_date', p_task.due_date,
    'due_at', p_task.due_at,
    'due_timezone', p_task.due_timezone,
    'estimate_minutes', p_task.estimate_minutes,
    'estimate_origin', p_task.estimate_origin,
    'project_id', p_task.project_id,
    'version', p_task.version,
    'created_at', p_task.created_at,
    'updated_at', p_task.updated_at
  );
$$;

revoke all on function public.focusos_task_json(public.tasks) from public, anon, authenticated;

create function public.focusos_update_task(
  p_task_id uuid,
  p_expected_version integer,
  p_changes jsonb
)
returns table (outcome text, task jsonb)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  caller_id uuid := auth.uid();
  saved_task public.tasks;
  deadline_keys text[] := array['due_kind', 'due_date', 'due_at', 'due_timezone'];
begin
  if caller_id is null then
    raise exception 'Authentication required';
  end if;
  if p_expected_version is null or p_expected_version < 1 or pg_catalog.jsonb_typeof(p_changes) is distinct from 'object'
    or p_changes = '{}'::jsonb
  then
    raise exception 'Task update payload is invalid';
  end if;

  if exists (
    select 1
    from pg_catalog.jsonb_object_keys(p_changes) as item(key)
    where item.key not in (
      'title', 'description', 'status', 'priority', 'due_kind', 'due_date',
      'due_at', 'due_timezone', 'estimate_minutes', 'project_id'
    )
  ) then
    raise exception 'Task update includes an unknown field';
  end if;

  if p_changes ?| deadline_keys and not (p_changes ?& deadline_keys) then
    raise exception 'Deadline fields must be updated together';
  end if;

  if p_changes ? 'project_id'
    and p_changes -> 'project_id' <> 'null'::jsonb
    and not exists (
      select 1 from public.projects
      where id = (p_changes ->> 'project_id')::uuid and user_id = caller_id
    )
  then
    return query select 'project_not_found'::text, null::jsonb;
    return;
  end if;

  update public.tasks as t
  set
    title = case when p_changes ? 'title' then p_changes ->> 'title' else t.title end,
    description = case when p_changes ? 'description' then p_changes ->> 'description' else t.description end,
    status = case when p_changes ? 'status' then p_changes ->> 'status' else t.status end,
    priority = case when p_changes ? 'priority' then p_changes ->> 'priority' else t.priority end,
    due_kind = case when p_changes ? 'due_kind' then p_changes ->> 'due_kind' else t.due_kind end,
    due_date = case
      when p_changes ? 'due_date' then (p_changes ->> 'due_date')::date
      else t.due_date
    end,
    due_at = case
      when p_changes ? 'due_at' then (p_changes ->> 'due_at')::timestamptz
      else t.due_at
    end,
    due_timezone = case
      when p_changes ? 'due_timezone' then p_changes ->> 'due_timezone'
      else t.due_timezone
    end,
    estimate_minutes = case
      when p_changes ? 'estimate_minutes' then (p_changes ->> 'estimate_minutes')::integer
      else t.estimate_minutes
    end,
    estimate_origin = case
      when p_changes ? 'estimate_minutes' then
        case when p_changes ->> 'estimate_minutes' is null then null else 'explicit' end
      else t.estimate_origin
    end,
    project_id = case
      when p_changes ? 'project_id' then (p_changes ->> 'project_id')::uuid
      else t.project_id
    end,
    version = t.version + 1
  where t.id = p_task_id
    and t.user_id = caller_id
    and t.version = p_expected_version
  returning t.* into saved_task;

  if found then
    return query select 'updated'::text, public.focusos_task_json(saved_task);
    return;
  end if;

  select * into saved_task
  from public.tasks
  where id = p_task_id and user_id = caller_id;

  if not found then
    return query select 'not_found'::text, null::jsonb;
    return;
  end if;

  return query select 'stale'::text, public.focusos_task_json(saved_task);
end;
$$;

revoke all on function public.focusos_update_task(uuid, integer, jsonb) from public, anon;
grant execute on function public.focusos_update_task(uuid, integer, jsonb) to authenticated;

