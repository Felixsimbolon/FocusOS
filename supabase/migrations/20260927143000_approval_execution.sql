-- Phase 8.6: only the API's service credential can claim/finalize an approved action.
create unique index approval_one_executing_per_owner on public.approval_requests(user_id)
 where status='executing';

create function public.focusos_claim_approval_execution(p_user_id uuid,p_approval_id uuid)
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
  return to_jsonb(v_row);
 end if;
 if v_row.status not in ('approved','executing','unknown') then return to_jsonb(v_row); end if;
 if v_row.status in ('executing','unknown') and v_row.lease_until>now() then return to_jsonb(v_row); end if;
 if exists(select 1 from public.approval_requests
   where user_id=p_user_id and id<>p_approval_id
    and (status='executing' or status='unknown'))
 then return to_jsonb(v_row); end if;
 update public.approval_requests set status='executing',status_version=status_version+1,
  lease_until=now()+interval '120 seconds',safe_code=null
 where id=v_row.id returning * into v_row;
 return to_jsonb(v_row);
end; $$;
revoke all on function public.focusos_claim_approval_execution(uuid,uuid) from public,anon,authenticated;
grant execute on function public.focusos_claim_approval_execution(uuid,uuid) to service_role;

create function public.focusos_finish_approval_execution(
 p_user_id uuid,p_approval_id uuid,p_expected_version integer,p_status text,
 p_provider_event_id text,p_provider_link text,p_safe_code text)
returns boolean language plpgsql security definer set search_path=''
as $$
declare v_row public.approval_requests;
begin
 if (select auth.role())<>'service_role' or p_user_id is null then
  raise exception 'Service role required' using errcode='28000'; end if;
 if p_status not in ('succeeded','failed','unknown','stale','approved')
  or char_length(coalesce(p_safe_code,''))>80
  or char_length(coalesce(p_provider_link,''))>2048
 then raise exception 'Invalid execution result' using errcode='22023'; end if;
 select * into v_row from public.approval_requests
  where id=p_approval_id and user_id=p_user_id and status='executing'
   and status_version=p_expected_version for update;
 if not found then return false; end if;
 if p_status='succeeded' then
  if p_provider_event_id is distinct from v_row.event_id
   or (p_provider_link is not null and p_provider_link not like 'https://www.google.com/calendar/%'
       and p_provider_link not like 'https://calendar.google.com/%')
  then raise exception 'Invalid provider proof' using errcode='22023'; end if;
 else
  if p_provider_event_id is not null or p_provider_link is not null then
   raise exception 'Unproven provider result' using errcode='22023'; end if;
 end if;
 update public.approval_requests set status=p_status,status_version=status_version+1,
  provider_event_id=p_provider_event_id,provider_link=p_provider_link,safe_code=p_safe_code,
  lease_until=case when p_status='unknown' then now()+interval '30 seconds' else null end
 where id=v_row.id;
 return true;
end; $$;
revoke all on function public.focusos_finish_approval_execution(uuid,uuid,integer,text,text,text,text)
 from public,anon,authenticated;
grant execute on function public.focusos_finish_approval_execution(uuid,uuid,integer,text,text,text,text)
 to service_role;
