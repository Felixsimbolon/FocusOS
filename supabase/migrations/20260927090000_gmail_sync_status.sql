-- Phase 5.7: owner-scoped status counts for the manual sync dashboard.
create function public.focusos_gmail_sync_status(
 p_connection_id uuid,p_schema text,p_prompt text,p_model text
) returns jsonb language plpgsql stable security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_state public.gmail_sync_state;
declare v_total integer; v_ready integer; v_failed integer; v_pending integer;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if not exists(select 1 from public.connections where id=p_connection_id and user_id=v_owner)
 then return null; end if;
 select * into v_state from public.gmail_sync_state
   where connection_id=p_connection_id and user_id=v_owner;
 select count(*) into v_total from public.source_items
   where connection_id=p_connection_id and user_id=v_owner and kind='gmail' and deleted_at is null;
 select count(*) filter(where r.status='ready'),
        count(*) filter(where r.status='failed'),
        count(*) filter(where r.id is null or r.status='failed'
          or (r.status='processing' and r.lease_expires_at<=now()))
 into v_ready,v_failed,v_pending
 from public.source_items s
 left join public.extraction_results r on r.source_id=s.id and r.user_id=s.user_id
   and r.content_hash=s.body_hash and r.schema_version=p_schema
   and r.prompt_version=p_prompt and r.model_version=p_model
 where s.connection_id=p_connection_id and s.user_id=v_owner and s.kind='gmail'
   and s.deleted_at is null and s.normalized_body is not null
   and s.body_expires_at>now();
 return jsonb_build_object(
   'mode',v_state.mode,'last_status',coalesce(v_state.last_status,'idle'),
   'last_error',v_state.last_error,'retry_after',v_state.retry_after,
   'last_attempt_at',v_state.last_attempt_at,'last_success_at',v_state.last_success_at,
   'lease_until',v_state.lease_until,
   'pending_staged',coalesce(cardinality(v_state.pending_ids),0),
   'page_pending',v_state.initial_page_token is not null
      or v_state.history_page_token is not null
      or coalesce(cardinality(v_state.pending_ids),0)>0,
   'source_count',v_total,'ready_count',coalesce(v_ready,0),
   'failed_count',coalesce(v_failed,0),'pending_count',coalesce(v_pending,0));
end;
$$;
revoke all on function public.focusos_gmail_sync_status(uuid,text,text,text) from public,anon;
grant execute on function public.focusos_gmail_sync_status(uuid,text,text,text) to authenticated;
