-- Phase 8.3: owner-only review and atomic human decision. No provider call.
create function public.focusos_list_approvals(p_run_id uuid)
returns setof public.approval_requests language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid());
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 update public.approval_requests set status='expired',status_version=status_version+1
 where user_id=v_owner and status='pending' and expires_at<=now()
  and (p_run_id is null or run_id=p_run_id);
 return query select a.* from public.approval_requests a
 where a.user_id=v_owner and (p_run_id is null or a.run_id=p_run_id)
 order by a.created_at desc limit 32;
end; $$;
revoke all on function public.focusos_list_approvals(uuid) from public,anon;
grant execute on function public.focusos_list_approvals(uuid) to authenticated;

create function public.focusos_decide_approval(p_approval_id uuid,p_decision text)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.approval_requests; v_target text;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_decision not in ('approve','reject') then raise exception 'Invalid decision' using errcode='22023'; end if;
 v_target:=case when p_decision='approve' then 'approved' else 'rejected' end;
 select * into v_row from public.approval_requests
 where id=p_approval_id and user_id=v_owner for update;
 if not found then raise exception 'Approval unavailable' using errcode='22023'; end if;
 if v_row.status='pending' and v_row.expires_at<=now() then
  update public.approval_requests set status='expired',status_version=status_version+1
   where id=v_row.id returning * into v_row;
  return to_jsonb(v_row);
 end if;
 if v_row.status=v_target then return to_jsonb(v_row); end if;
 if v_row.status<>'pending' then raise exception 'Decision already final' using errcode='22023'; end if;
 update public.approval_requests set status=v_target,status_version=status_version+1,decided_at=now()
 where id=v_row.id returning * into v_row;
 return to_jsonb(v_row);
end; $$;
revoke all on function public.focusos_decide_approval(uuid,text) from public,anon;
grant execute on function public.focusos_decide_approval(uuid,text) to authenticated;
