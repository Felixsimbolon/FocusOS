-- Run with `supabase test db` against a disposable/local database after at least one Auth user exists.
-- The transaction is rolled back and creates no lasting task data.
begin;

do $$
declare
  owner_id uuid;
  task_id uuid;
begin
  select id into owner_id from auth.users order by created_at limit 1;
  if owner_id is null then
    raise exception 'Create a disposable Auth user before running the task RLS probe';
  end if;

  insert into public.tasks (user_id, title)
  values (owner_id, 'FocusOS RLS rollback probe')
  returning id into task_id;

  perform pg_catalog.set_config('focusos.test.owner_id', owner_id::text, true);
  perform pg_catalog.set_config('focusos.test.task_id', task_id::text, true);
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
  visible_count integer;
begin
  select count(*) into visible_count
  from public.tasks
  where id = pg_catalog.current_setting('focusos.test.task_id')::uuid;
  if visible_count <> 1 then
    raise exception 'Task owner cannot read their own row';
  end if;
end;
$$;

select pg_catalog.set_config(
  'request.jwt.claim.sub',
  '00000000-0000-4000-8000-000000000001',
  true
);

do $$
declare
  visible_count integer;
begin
  select count(*) into visible_count
  from public.tasks
  where id = pg_catalog.current_setting('focusos.test.task_id')::uuid;
  if visible_count <> 0 then
    raise exception 'A different Auth subject can read another user task';
  end if;
end;
$$;

rollback;
