-- Google connection metadata is visible only to its owning authenticated user.
create table public.connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null check (provider = 'google'),
  provider_subject text not null,
  display_email text,
  granted_scopes text[] not null default '{}',
  status text not null default 'connected'
    check (status in ('connected', 'reconnect_required', 'disconnected')),
  last_refresh_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint connections_user_provider_unique unique (user_id, provider)
);

alter table public.connections enable row level security;
revoke all on table public.connections from public, anon, authenticated, service_role;
grant select (
  id, user_id, provider, display_email, granted_scopes, status,
  last_refresh_at, created_at, updated_at
) on public.connections to authenticated;
grant select, insert, update, delete on public.connections to service_role;

create policy focusos_connection_select_own
on public.connections for select to authenticated
using ((select auth.uid()) = user_id);

-- OAuth tokens are stored as authenticated ciphertext bytes produced by the API.
-- The API encryption key remains outside Postgres; key version enables rotation.
create schema if not exists private;
revoke all on schema private from public, anon, authenticated, service_role;

create table private.oauth_credentials (
  connection_id uuid primary key
    references public.connections(id) on delete cascade,
  encrypted_refresh_token bytea not null,
  encrypted_access_token bytea,
  access_token_expires_at timestamptz,
  encryption_key_version integer not null check (encryption_key_version > 0),
  token_version bigint not null default 1 check (token_version > 0),
  refresh_lease_until timestamptz,
  updated_at timestamptz not null default now()
);

alter table private.oauth_credentials enable row level security;
revoke all on table private.oauth_credentials from public, anon, authenticated, service_role;
