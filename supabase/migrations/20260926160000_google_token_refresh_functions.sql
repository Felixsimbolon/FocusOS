-- Narrow service-only SQL boundary for the private encrypted token table.
alter table private.oauth_credentials
  add column refresh_lease_id uuid,
  add constraint oauth_credentials_refresh_ciphertext_size
    check (octet_length(encrypted_refresh_token) >= 28),
  add constraint oauth_credentials_access_ciphertext_size
    check (encrypted_access_token is null or octet_length(encrypted_access_token) >= 28);

create function public.focusos_read_google_credentials(p_connection_id uuid)
returns table (
  connection_id uuid,
  status text,
  encrypted_refresh_token bytea,
  encrypted_access_token bytea,
  access_token_expires_at timestamptz,
  encryption_key_version integer,
  token_version bigint
)
language sql
stable
security definer
set search_path = ''
as $$
  select c.id, c.status, o.encrypted_refresh_token, o.encrypted_access_token,
         o.access_token_expires_at, o.encryption_key_version, o.token_version
  from public.connections as c
  join private.oauth_credentials as o on o.connection_id = c.id
  where c.id = p_connection_id;
$$;

create function public.focusos_claim_google_refresh(
  p_connection_id uuid,
  p_expected_token_version bigint,
  p_lease_id uuid,
  p_lease_seconds integer
)
returns table (
  connection_id uuid,
  status text,
  encrypted_refresh_token bytea,
  encrypted_access_token bytea,
  access_token_expires_at timestamptz,
  encryption_key_version integer,
  token_version bigint
)
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if p_lease_id is null or p_lease_seconds not between 5 and 120 then
    raise exception 'Invalid refresh lease';
  end if;

  return query
    update private.oauth_credentials as o
       set refresh_lease_id = p_lease_id,
           refresh_lease_until = pg_catalog.now()
             + pg_catalog.make_interval(secs => p_lease_seconds),
           updated_at = pg_catalog.now()
      from public.connections as c
     where c.id = o.connection_id
       and c.id = p_connection_id
       and c.status = 'connected'
       and o.token_version = p_expected_token_version
       and (o.refresh_lease_until is null or o.refresh_lease_until <= pg_catalog.now())
    returning c.id, c.status, o.encrypted_refresh_token, o.encrypted_access_token,
              o.access_token_expires_at, o.encryption_key_version, o.token_version;
end;
$$;

create function public.focusos_save_google_refresh(
  p_connection_id uuid,
  p_expected_token_version bigint,
  p_lease_id uuid,
  p_encrypted_access_token bytea,
  p_encrypted_refresh_token bytea,
  p_access_token_expires_at timestamptz,
  p_encryption_key_version integer
)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  saved_version bigint;
begin
  if p_encrypted_access_token is null
     or pg_catalog.octet_length(p_encrypted_access_token) < 28
     or p_encrypted_refresh_token is null
     or pg_catalog.octet_length(p_encrypted_refresh_token) < 28
     or p_encryption_key_version < 1
     or p_lease_id is null
  then
    return false;
  end if;

  update private.oauth_credentials as o
     set encrypted_access_token = p_encrypted_access_token,
         encrypted_refresh_token = p_encrypted_refresh_token,
         access_token_expires_at = p_access_token_expires_at,
         encryption_key_version = p_encryption_key_version,
         token_version = o.token_version + 1,
         refresh_lease_id = null,
         refresh_lease_until = null,
         updated_at = pg_catalog.now()
    from public.connections as c
   where c.id = o.connection_id
     and c.id = p_connection_id
     and c.status = 'connected'
     and o.token_version = p_expected_token_version
     and o.refresh_lease_id = p_lease_id
     and o.refresh_lease_until > pg_catalog.now()
  returning o.token_version into saved_version;

  if saved_version is null then
    return false;
  end if;

  update public.connections
     set last_refresh_at = pg_catalog.now(),
         updated_at = pg_catalog.now()
   where id = p_connection_id;
  return true;
end;
$$;

create function public.focusos_release_google_refresh(
  p_connection_id uuid,
  p_lease_id uuid
)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  released boolean;
begin
  update private.oauth_credentials
     set refresh_lease_id = null,
         refresh_lease_until = null,
         updated_at = pg_catalog.now()
   where connection_id = p_connection_id
     and refresh_lease_id = p_lease_id
  returning true into released;
  return coalesce(released, false);
end;
$$;

create function public.focusos_mark_google_reconnect_required(
  p_connection_id uuid,
  p_lease_id uuid
)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  changed boolean;
begin
  update public.connections as c
     set status = 'reconnect_required',
         updated_at = pg_catalog.now()
    from private.oauth_credentials as o
   where c.id = p_connection_id
     and o.connection_id = c.id
     and o.refresh_lease_id = p_lease_id
  returning true into changed;

  if coalesce(changed, false) then
    update private.oauth_credentials
       set refresh_lease_id = null,
           refresh_lease_until = null,
           updated_at = pg_catalog.now()
     where connection_id = p_connection_id;
  end if;
  return coalesce(changed, false);
end;
$$;

revoke all on function public.focusos_read_google_credentials(uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.focusos_claim_google_refresh(uuid, bigint, uuid, integer)
  from public, anon, authenticated, service_role;
revoke all on function public.focusos_save_google_refresh(uuid, bigint, uuid, bytea, bytea, timestamptz, integer)
  from public, anon, authenticated, service_role;
revoke all on function public.focusos_release_google_refresh(uuid, uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.focusos_mark_google_reconnect_required(uuid, uuid)
  from public, anon, authenticated, service_role;

grant execute on function public.focusos_read_google_credentials(uuid) to service_role;
grant execute on function public.focusos_claim_google_refresh(uuid, bigint, uuid, integer) to service_role;
grant execute on function public.focusos_save_google_refresh(uuid, bigint, uuid, bytea, bytea, timestamptz, integer) to service_role;
grant execute on function public.focusos_release_google_refresh(uuid, uuid) to service_role;
grant execute on function public.focusos_mark_google_reconnect_required(uuid, uuid) to service_role;
