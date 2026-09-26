-- Upgrade only a matching owner + Google subject; stale or cross-account requests do nothing.
create function public.focusos_upgrade_google_credentials(
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
    raise exception 'Invalid Google credential upgrade';
  end if;

  update public.connections as c
     set display_email = p_display_email,
         granted_scopes = p_granted_scopes,
         status = 'connected',
         updated_at = pg_catalog.now()
   where c.id = p_connection_id
     and c.user_id = p_user_id
     and c.provider = 'google'
     and c.provider_subject = p_provider_subject
  returning c.id into saved_id;
  if saved_id is null then return; end if;

  update private.oauth_credentials as o
     set encrypted_refresh_token = p_encrypted_refresh_token,
         encrypted_access_token = p_encrypted_access_token,
         access_token_expires_at = p_access_token_expires_at,
         encryption_key_version = p_encryption_key_version,
         token_version = o.token_version + 1,
         refresh_lease_id = null,
         refresh_lease_until = null,
         updated_at = pg_catalog.now()
   where o.connection_id = saved_id;
  if not found then raise exception 'Google credentials are missing'; end if;

  return query select c.id, c.provider, c.display_email, c.granted_scopes, c.status, c.last_refresh_at
    from public.connections as c where c.id = saved_id;
end;
$$;

revoke all on function public.focusos_upgrade_google_credentials(uuid, uuid, text, text, text[], bytea, bytea, timestamptz, integer)
  from public, anon, authenticated, service_role;
grant execute on function public.focusos_upgrade_google_credentials(uuid, uuid, text, text, text[], bytea, bytea, timestamptz, integer)
  to service_role;
