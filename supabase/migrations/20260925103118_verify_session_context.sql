-- A read-only probe for verifying that PostgREST receives the caller's JWT.
create function public.focusos_session_uid()
returns uuid
language sql
stable
security invoker
set search_path = ''
as $$
  select auth.uid();
$$;

revoke execute on function public.focusos_session_uid() from public;
revoke execute on function public.focusos_session_uid() from anon;
grant execute on function public.focusos_session_uid() to authenticated;
