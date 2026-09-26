-- Verify project dedupe, owner association, and cross-owner reference denial; all rows roll back.
begin;

do $$
declare
  owner_id uuid;
begin
  select id into owner_id from auth.users order by created_at limit 1;
  if owner_id is null then
    raise exception 'Create a disposable Auth user before running the project probe';
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
  first_project jsonb;
  duplicate_project jsonb;
  first_existing boolean;
  duplicate_existing boolean;
  task_row jsonb;
  task_project_available boolean;
  first_project_id uuid;
begin
  select result.project, result.existing into first_project, first_existing
  from public.focusos_create_project('FocusOS Project Association Probe') as result;
  first_project_id := (first_project ->> 'id')::uuid;
  perform pg_catalog.set_config('focusos.test.project_id', first_project_id::text, true);

  select result.project, result.existing into duplicate_project, duplicate_existing
  from public.focusos_create_project('  focusos project association probe  ') as result;

  select result.task, result.project_available
  into task_row, task_project_available
  from public.focusos_create_task(
    'a8f9a24e-39a6-41b3-a5b0-6d59b7ed8cf1',
    pg_catalog.repeat('c', 64),
    'Task linked to owned project',
    null,
    'normal',
    'none',
    null,
    null,
    null,
    null,
    first_project_id
  ) as result;

  if first_existing or not duplicate_existing
    or first_project_id <> (duplicate_project ->> 'id')::uuid
    or not task_project_available
    or (task_row ->> 'project_id')::uuid <> first_project_id
  then
    raise exception 'Owned project association or normalized-name dedupe failed';
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
  visible_count integer;
  task_row jsonb;
  project_available boolean;
begin
  select count(*) into visible_count
  from public.projects
  where id = pg_catalog.current_setting('focusos.test.project_id')::uuid;
  if visible_count <> 0 then
    raise exception 'A different Auth subject can read a foreign project';
  end if;

  select result.task, result.project_available into task_row, project_available
  from public.focusos_create_task(
    '6c0e36bd-f6be-42a7-95a1-f76e56f05f11',
    pg_catalog.repeat('d', 64),
    'Cross-owner project attempt',
    null,
    'normal',
    'none',
    null,
    null,
    null,
    null,
    pg_catalog.current_setting('focusos.test.project_id')::uuid
  ) as result;

  if task_row is not null or project_available then
    raise exception 'A different Auth subject linked a foreign project';
  end if;
end;
$$;

rollback;

