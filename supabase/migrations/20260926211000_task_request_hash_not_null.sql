-- Tighten the idempotency metadata pair: CHECK expressions that evaluate to NULL pass.
alter table public.tasks
  drop constraint tasks_create_request_pair,
  add constraint tasks_create_request_pair check (
    (create_request_id is null and create_request_hash is null)
    or (
      create_request_id is not null
      and create_request_hash is not null
      and create_request_hash ~ '^[0-9a-f]{64}$'
    )
  );
