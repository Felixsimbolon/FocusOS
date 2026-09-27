-- Record whether a Calendar action was authorized by the new one-submit workflow.
alter table public.approval_requests
  add column authorization_mode text not null default 'manual'
  check (authorization_mode in ('manual','automatic'));
grant select(authorization_mode) on public.approval_requests to authenticated;

alter table public.approval_action_events
  add column authorization_mode text not null default 'manual'
  check (authorization_mode in ('manual','automatic'));
grant select(authorization_mode) on public.approval_action_events to authenticated;

create or replace function public.focusos_record_approval_transition() returns trigger
language plpgsql security definer set search_path=''
as $$
begin
 if tg_op='INSERT' or new.status is distinct from old.status then
  insert into public.approval_action_events(
    user_id,run_id,approval_id,block_index,status,status_version,
    safe_code,occurred_at,authorization_mode)
  values(new.user_id,new.run_id,new.id,new.block_index,new.status,new.status_version,
    new.safe_code,case when tg_op='INSERT' then new.created_at else new.updated_at end,
    new.authorization_mode);
 end if;
 return new;
end; $$;

-- The caller must own an active run explicitly started for automatic Calendar writes.
-- Proposal identity and payload still come from the existing server-owned RPC.
create function public.focusos_authorize_automatic_calendar_action(
 p_run_id uuid,p_block_index integer
) returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid());
declare v_run public.command_runs;
declare v_row public.approval_requests;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 select * into v_row from public.approval_requests
 where user_id=v_owner and run_id=p_run_id and block_index=p_block_index for update;
 if found and v_row.authorization_mode='automatic' then return to_jsonb(v_row); end if;
 select * into v_run from public.command_runs
 where id=p_run_id and user_id=v_owner and status='succeeded'
   and result->>'status'='proposed'
   and checkpoint->>'auto_calendar'='true'
   and expires_at>now();
 if not found then raise exception 'Automatic plan unavailable' using errcode='22023'; end if;
 if v_row.id is null then raise exception 'Calendar proposal unavailable' using errcode='22023'; end if;
 if v_row.status<>'pending' or v_row.expires_at<=now() then
   raise exception 'Calendar proposal is no longer pending' using errcode='22023';
 end if;
 update public.approval_requests
 set authorization_mode='automatic',status='approved',
     status_version=status_version+1,decided_at=now()
 where id=v_row.id returning * into v_row;
 return to_jsonb(v_row);
end; $$;
revoke all on function public.focusos_authorize_automatic_calendar_action(uuid,integer)
 from public,anon;
grant execute on function public.focusos_authorize_automatic_calendar_action(uuid,integer)
 to authenticated;
