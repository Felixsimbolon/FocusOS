-- Phase 4.1: one owned, replay-safe manual source with bounded retained text.
create table public.source_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null default 'manual' check (kind in ('manual', 'gmail', 'document')),
  title text not null check (char_length(title) between 1 and 200),
  source_ref text generated always as ('manual:' || id::text) stored,
  normalized_body text,
  body_hash text not null check (body_hash ~ '^[0-9a-f]{64}$'),
  normalization_version text not null default '1',
  body_truncated boolean not null default false,
  request_id uuid not null,
  request_hash text not null check (request_hash ~ '^[0-9a-f]{64}$'),
  received_at timestamptz not null,
  created_at timestamptz not null default now(),
  body_expires_at timestamptz not null default (now() + interval '30 days'),
  deleted_at timestamptz,
  constraint source_body_size check (normalized_body is null or octet_length(normalized_body) <= 20480),
  constraint source_replay unique (user_id, request_id),
  constraint source_owned_id unique (user_id, id)
);
create index source_items_owner_received_idx on public.source_items (user_id, received_at desc);
create index source_items_expiry_idx on public.source_items (user_id, body_expires_at)
  where normalized_body is not null;
alter table public.source_items enable row level security;
revoke all on public.source_items from public, anon, authenticated;
grant select (id, user_id, kind, title, source_ref, normalized_body, body_hash,
  normalization_version, body_truncated, request_id, request_hash, received_at,
  created_at, body_expires_at, deleted_at)
  on public.source_items to authenticated;
create policy source_items_read_own on public.source_items for select to authenticated
  using ((select auth.uid()) = user_id);

create function public.focusos_create_manual_source(
  p_request_id uuid, p_request_hash text, p_title text, p_body text,
  p_body_hash text, p_received_at timestamptz
) returns jsonb language plpgsql security definer set search_path = ''
as $$
declare v_owner uuid := (select auth.uid());
declare v_row public.source_items;
declare v_existing boolean := false;
begin
  if v_owner is null then raise exception 'Authentication required' using errcode = '28000'; end if;
  if p_request_hash !~ '^[0-9a-f]{64}$' or p_body_hash !~ '^[0-9a-f]{64}$'
    or octet_length(p_body) > 20480 or octet_length(p_body) < 1
    or char_length(p_title) not between 1 and 200 then
    raise exception 'Invalid source' using errcode = '22023';
  end if;
  insert into public.source_items
    (user_id, title, normalized_body, body_hash, request_id, request_hash, received_at)
  values (v_owner, p_title, p_body, p_body_hash, p_request_id, p_request_hash, p_received_at)
  on conflict (user_id, request_id) do nothing
  returning * into v_row;
  if v_row.id is null then
    v_existing := true;
    select * into v_row from public.source_items
      where user_id = v_owner and request_id = p_request_id;
  end if;
  return jsonb_build_object('source', to_jsonb(v_row), 'replayed', v_existing,
    'conflict', v_row.request_hash is distinct from p_request_hash);
end;
$$;
revoke all on function public.focusos_create_manual_source(uuid,text,text,text,text,timestamptz)
  from public, anon;
grant execute on function public.focusos_create_manual_source(uuid,text,text,text,text,timestamptz)
  to authenticated;

create function public.focusos_expire_source_bodies(p_limit integer default 100)
returns integer language plpgsql security definer set search_path = ''
as $$
declare v_owner uuid := (select auth.uid()); v_count integer;
begin
  if v_owner is null then raise exception 'Authentication required' using errcode = '28000'; end if;
  if p_limit < 1 or p_limit > 100 then raise exception 'Invalid limit' using errcode = '22023'; end if;
  with expired as (
    select id from public.source_items
    where user_id = v_owner and normalized_body is not null and body_expires_at <= now()
    order by body_expires_at, id limit p_limit for update skip locked
  )
  update public.source_items s set normalized_body = null
  from expired where s.id = expired.id;
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;
revoke all on function public.focusos_expire_source_bodies(integer) from public, anon;
grant execute on function public.focusos_expire_source_bodies(integer) to authenticated;
