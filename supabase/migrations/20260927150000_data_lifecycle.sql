-- Phase 9.5: owner-scoped revocation and one selected Gmail-source erasure.
-- This migration defines controls only; it does not delete existing user data.
create function public.focusos_disconnect_google() returns jsonb
language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_id uuid;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 select id into v_id from public.connections where user_id=v_owner and provider='google' for update;
 if v_id is null then return jsonb_build_object('disconnected',false); end if;
 update public.connections set status='disconnected',granted_scopes='{}',display_email=null,
   provider_subject='disconnected:' || v_id::text,last_refresh_at=null,updated_at=now()
 where id=v_id and user_id=v_owner;
 delete from private.oauth_credentials where connection_id=v_id;
 delete from public.gmail_sync_state where connection_id=v_id and user_id=v_owner;
 update public.approval_requests set status='stale',status_version=status_version+1,
   safe_code='google_disconnected',lease_until=null
 where user_id=v_owner and connection_id=v_id and status in ('pending','approved');
 update public.approval_requests set status='unknown',status_version=status_version+1,
   safe_code='disconnected_during_execution',lease_until=now()+interval '30 seconds'
 where user_id=v_owner and connection_id=v_id and status='executing';
 return jsonb_build_object('disconnected',true);
end; $$;
revoke all on function public.focusos_disconnect_google() from public,anon;
grant execute on function public.focusos_disconnect_google() to authenticated;

-- Delete exactly one owned Gmail source and its linked snapshots/derived rows.
-- No Google event is deleted, and unrelated command runs remain untouched.
create function public.focusos_delete_gmail_source(p_source_id uuid) returns jsonb
language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_tasks integer; v_runs integer;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if not exists(select 1 from public.source_items where id=p_source_id and user_id=v_owner and kind='gmail' for update)
 then return jsonb_build_object('deleted',false); end if;
 perform pg_advisory_xact_lock(hashtextextended(v_owner::text,0));
 delete from public.command_runs where user_id=v_owner and (
   checkpoint::text like '%' || p_source_id::text || '%'
   or coalesce(result::text,'') like '%' || p_source_id::text || '%');
 get diagnostics v_runs = row_count;
 delete from public.tasks t where t.user_id=v_owner and (
   t.source_id=p_source_id or exists(select 1 from public.extraction_results r
     where r.id=t.extraction_result_id and r.user_id=v_owner and r.source_id=p_source_id));
 get diagnostics v_tasks = row_count;
 delete from public.source_items where id=p_source_id and user_id=v_owner and kind='gmail';
 return jsonb_build_object('deleted',true,'tasks_deleted',v_tasks,'command_runs_deleted',v_runs);
end; $$;
revoke all on function public.focusos_delete_gmail_source(uuid) from public,anon;
grant execute on function public.focusos_delete_gmail_source(uuid) to authenticated;
