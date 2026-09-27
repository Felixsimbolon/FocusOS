-- Claim response explicitly distinguishes this invocation from an in-flight claim.
create or replace function public.focusos_claim_approval_execution(p_user_id uuid,p_approval_id uuid)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_row public.approval_requests;
begin
 if (select auth.role())<>'service_role' or p_user_id is null then
  raise exception 'Service role required' using errcode='28000'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_user_id::text,0));
 select * into v_row from public.approval_requests
  where id=p_approval_id and user_id=p_user_id for update;
 if not found then return null; end if;
 if v_row.status='approved' and v_row.expires_at<=now() then
  update public.approval_requests set status='stale',status_version=status_version+1,
   safe_code='approval_expired',lease_until=null where id=v_row.id returning * into v_row;
  return jsonb_build_object('claimed',false,'approval',to_jsonb(v_row));
 end if;
 if v_row.status not in ('approved','executing','unknown') then
  return jsonb_build_object('claimed',false,'approval',to_jsonb(v_row)); end if;
 if v_row.status in ('executing','unknown') and v_row.lease_until>now() then
  return jsonb_build_object('claimed',false,'approval',to_jsonb(v_row)); end if;
 if exists(select 1 from public.approval_requests
   where user_id=p_user_id and id<>p_approval_id and (status='executing' or status='unknown'))
 then return jsonb_build_object('claimed',false,'approval',to_jsonb(v_row)); end if;
 update public.approval_requests set status='executing',status_version=status_version+1,
  lease_until=now()+interval '120 seconds',safe_code=null
 where id=v_row.id returning * into v_row;
 return jsonb_build_object('claimed',true,'approval',to_jsonb(v_row));
end; $$;
