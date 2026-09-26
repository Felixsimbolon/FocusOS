-- Verify compare-and-swap updates, stale conflict data, and owner hiding; all rows roll back.
begin;

do $$
declare
  owner_id uuid;
begin
  select id into owner_id from auth.users order by created_at limit 1;
  if owner_id is null then
    raise exception 'Create a disposable Auth user before running the task version probe';
  end if;
  perform pg_catalog.set_config('focusos.test.owner_id', owner_id::text, true);
  perform pg_catalog.set_config(
    'focusos.test.other_id',
    '00000000-0000-4000-8000-000000000001',
    true
  );
end;
$$;

set local role authenticated;
select pg_catalog.set_config(
  'request.jwt.claim.sub',
  pg_catalog.current_setting('focusos.test.owner_id'),
  true
);

do $$
declare
  created_task jsonb;
  task_id uuid;
  outcome_value text;
  updated_task jsonb;
  stale_task jsonb;
begin
  select result.task into created_task
  from public.focusos_create_task(
    '2c564169-56f5-4541-b0f8-1a942febc4ce',
    pg_catalog.repeat('e', 64),
    'FocusOS version rollback probe',
    null,
    'normal',
    'none',
    null,
    null,
    null,
    null,
    null
  ) as result;
  task_id := (created_task ->> 'id')::uuid;
  perform pg_catalog.set_config('focusos.test.task_id', task_id::text, true);

  select result.outcome, result.task into outcome_value, updated_task
  from public.focusos_update_task(
    task_id,
    1,
    pg_catalog.jsonb_build_object('title', 'Updated title', 'status', 'done')
  ) as result;

  if outcome_value <> 'updated'
    or updated_task ->> 'title' <> 'Updated title'
    or updated_task ->> 'status' <> 'done'
    or updated_task ->> 'version' <> '2'
  then
    raise exception 'Expected a version-checked update to increment version';
  end if;

  select result.outcome, result.task into outcome_value, stale_task
  from public.focusos_update_task(
    task_id,
    1,
    pg_catalog.jsonb_build_object('title', 'Stale title')
  ) as result;

  if outcome_value <> 'stale'
    or stale_task ->> 'title' <> 'Updated title'
    or stale_task ->> 'version' <> '2'
  then
    raise exception 'Expected an old version to return the current row without overwriting it';
  end if;
end;
$$;

select pg_catalog.set_config(
  'request.jwt.claim.sub',
  pg_catalog.current_setting('focusos.test.other_id'),
  true
);

do $$
declare
  outcome_value text;
  task_row jsonb;
begin
  select result.outcome, result.task into outcome_value, task_row
  from public.focusos_update_task(
    pg_catalog.current_setting('focusos.test.task_id')::uuid,
    2,
    pg_catalog.jsonb_build_object('status', 'archived')
  ) as result;
  if outcome_value <> 'not_found' or task_row is not null then
    raise exception 'A different Auth subject updated or observed the task';
  end if;
end;
$$;

rollback;
