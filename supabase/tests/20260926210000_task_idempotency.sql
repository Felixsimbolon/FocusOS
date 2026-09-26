-- Verify owner-bound replay and payload mismatch handling; all rows roll back.
begin;

do $$
declare
  owner_id uuid;
begin
  select id into owner_id from auth.users order by created_at limit 1;
  if owner_id is null then
    raise exception 'Create a disposable Auth user before running the task replay probe';
  end if;
  perform pg_catalog.set_config('focusos.test.owner_id', owner_id::text, true);
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
  first_id uuid;
  replay_id uuid;
  mismatch_id uuid;
  first_replayed boolean;
  replay_replayed boolean;
  mismatch_replayed boolean;
  replay_hash text;
  mismatch_hash text;
  mismatch_title text;
begin
  select (result.task ->> 'id')::uuid, result.replayed, result.stored_request_hash
  into first_id, first_replayed, replay_hash
  from public.focusos_create_task(
    'e5801581-e50a-44f4-8cea-9466d6f2f681',
    pg_catalog.repeat('a', 64),
    'FocusOS idempotency rollback probe',
    null,
    'normal',
    'none',
    null,
    null,
    null,
    null,
    null
  ) as result;

  select (result.task ->> 'id')::uuid, result.replayed, result.stored_request_hash
  into replay_id, replay_replayed, replay_hash
  from public.focusos_create_task(
    'e5801581-e50a-44f4-8cea-9466d6f2f681',
    pg_catalog.repeat('a', 64),
    'FocusOS idempotency rollback probe',
    null,
    'normal',
    'none',
    null,
    null,
    null,
    null,
    null
  ) as result;

  select
    (result.task ->> 'id')::uuid,
    result.replayed,
    result.stored_request_hash,
    result.task ->> 'title'
  into mismatch_id, mismatch_replayed, mismatch_hash, mismatch_title
  from public.focusos_create_task(
    'e5801581-e50a-44f4-8cea-9466d6f2f681',
    pg_catalog.repeat('b', 64),
    'Different payload',
    null,
    'normal',
    'none',
    null,
    null,
    null,
    null,
    null
  ) as result;

  if first_id is null or first_id <> replay_id or replay_id <> mismatch_id
    or first_replayed or not replay_replayed or not mismatch_replayed
    or replay_hash <> pg_catalog.repeat('a', 64)
    or mismatch_hash <> pg_catalog.repeat('a', 64)
    or mismatch_title <> 'FocusOS idempotency rollback probe'
  then
    raise exception 'Task replay/idempotency behavior did not match expectations';
  end if;
end;
$$;

rollback;
