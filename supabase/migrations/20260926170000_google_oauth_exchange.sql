-- The API first reserves a stable connection id for token AAD, then stores ciphertext.
-- Both functions are callable only with the server's service_role key.
create function public.focusos_prepare_google_connection(
  p_user_id uuid,
  p_provider_subject text,
  p_display_email text
)
returns uuid
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  connection_id uuid;
begin
  if p_user_id is null or p_provider_subject is null or pg_catalog.length(p_provider_subject) not between 1 and 255
     or p_display_email is null or pg_catalog.length(p_display_email) not between 3 and 320 then
    raise exception 'Invalid Google connection identity';
  end if;

  insert into public.connections (user_id, provider, provider_subject, display_email, granted_scopes, status)
  values (p_user_id, 'google', p_provider_subject, p_display_email, '{}', 'reconnect_required')
  on conflict (user_id, provider) do nothing;

  select c.id into connection_id
    from public.connections as c
   where c.user_id = p_user_id and c.provider = 'google';
  return connection_id;
end;
$$;

create function public.focusos_store_google_credentials(
  p_connection_id uuid,
  p_user_id uuid,
  p_provider_subject text,
  p_display_email text,
  p_granted_scopes text[],
  p_encrypted_refresh_token bytea,
  p_encrypted_access_token bytea,
  p_access_token_expires_at timestamptz,
  p_encryption_key_version integer
)
returns table (
  id uuid,
  provider text,
  display_email text,
  granted_scopes text[],
  status text,
  last_refresh_at timestamptz
)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  saved_id uuid;
begin
  if p_connection_id is null or p_user_id is null
     or p_provider_subject is null or pg_catalog.length(p_provider_subject) not between 1 and 255
     or p_display_email is null or pg_catalog.length(p_display_email) not between 3 and 320
     or p_granted_scopes is null or pg_catalog.cardinality(p_granted_scopes) < 1
     or p_encrypted_refresh_token is null or pg_catalog.octet_length(p_encrypted_refresh_token) < 28
     or p_encrypted_access_token is null or pg_catalog.octet_length(p_encrypted_access_token) < 28
     or p_access_token_expires_at is null or p_encryption_key_version < 1 then
    raise exception 'Invalid Google credential payload';
  end if;

  update public.connections as c
     set provider_subject = p_provider_subject,
         display_email = p_display_email,
         granted_scopes = p_granted_scopes,
         status = 'connected',
         updated_at = pg_catalog.now()
   where c.id = p_connection_id and c.user_id = p_user_id and c.provider = 'google'
  returning c.id into saved_id;
  if saved_id is null then
    raise exception 'Google connection owner mismatch';
  end if;

  insert into private.oauth_credentials (
    connection_id, encrypted_refresh_token, encrypted_access_token,
    access_token_expires_at, encryption_key_version, token_version
  ) values (
    saved_id, p_encrypted_refresh_token, p_encrypted_access_token,
    p_access_token_expires_at, p_encryption_key_version, 1
  )
  on conflict (connection_id) do update
    set encrypted_refresh_token = excluded.encrypted_refresh_token,
        encrypted_access_token = excluded.encrypted_access_token,
        access_token_expires_at = excluded.access_token_expires_at,
        encryption_key_version = excluded.encryption_key_version,
        token_version = private.oauth_credentials.token_version + 1,
        refresh_lease_id = null,
        refresh_lease_until = null,
        updated_at = pg_catalog.now();

  return query select c.id, c.provider, c.display_email, c.granted_scopes, c.status, c.last_refresh_at
    from public.connections as c where c.id = saved_id;
end;
$$;

revoke all on function public.focusos_prepare_google_connection(uuid, text, text)
  from public, anon, authenticated, service_role;
revoke all on function public.focusos_store_google_credentials(uuid, uuid, text, text, text[], bytea, bytea, timestamptz, integer)
  from public, anon, authenticated, service_role;
grant execute on function public.focusos_prepare_google_connection(uuid, text, text) to service_role;
grant execute on function public.focusos_store_google_credentials(uuid, uuid, text, text, text[], bytea, bytea, timestamptz, integer) to service_role;
