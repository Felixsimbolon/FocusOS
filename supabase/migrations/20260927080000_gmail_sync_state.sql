-- Phase 5.6a: durable bounded Gmail sync state and short database leases.
create table public.gmail_sync_state (
 connection_id uuid primary key,
 user_id uuid not null references auth.users(id) on delete cascade,
 label_id text not null,
 mode text not null default 'initial' check (mode in ('initial','history')),
 anchor_history_id text not null,
 history_id text,
 initial_page_token text,
 history_page_token text,
 pending_ids text[] not null default '{}',
 pending_next_page_token text,
 pending_new_history_id text,
 lease_token uuid,
 lease_until timestamptz,
 retry_after timestamptz,
 last_status text not null default 'idle',
 last_error text,
 last_attempt_at timestamptz,
 last_success_at timestamptz,
 updated_at timestamptz not null default now(),
 constraint gmail_sync_owned_connection foreign key(user_id,connection_id)
   references public.connections(user_id,id) on delete cascade
);
alter table public.gmail_sync_state enable row level security;
revoke all on public.gmail_sync_state from public,anon,authenticated;
grant select(connection_id,user_id,label_id,mode,anchor_history_id,history_id,
 initial_page_token,history_page_token,pending_ids,retry_after,last_status,last_error,
 last_attempt_at,last_success_at,updated_at)
 on public.gmail_sync_state to authenticated;
create policy gmail_sync_read_own on public.gmail_sync_state for select to authenticated
 using ((select auth.uid())=user_id);

create function public.focusos_claim_gmail_sync(
 p_connection_id uuid,p_label_id text,p_anchor_history_id text
) returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_state public.gmail_sync_state; v_token uuid;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_label_id !~ '^[A-Za-z0-9_-]{1,128}$' or p_anchor_history_id !~ '^[0-9]{1,30}$'
 then raise exception 'Invalid Gmail sync anchor' using errcode='22023'; end if;
 if not exists(select 1 from public.connections
   where id=p_connection_id and user_id=v_owner and status='connected'
   and 'https://www.googleapis.com/auth/gmail.readonly'=any(granted_scopes)) then
   return jsonb_build_object('state','reconnect');
 end if;
 insert into public.gmail_sync_state(connection_id,user_id,label_id,anchor_history_id)
 values(p_connection_id,v_owner,p_label_id,p_anchor_history_id)
 on conflict(connection_id) do nothing;
 select * into v_state from public.gmail_sync_state
   where connection_id=p_connection_id and user_id=v_owner for update;
 if v_state.label_id<>p_label_id then
   update public.gmail_sync_state set label_id=p_label_id,mode='initial',
     anchor_history_id=p_anchor_history_id,history_id=null,
     initial_page_token=null,history_page_token=null,pending_ids='{}',
     pending_next_page_token=null,pending_new_history_id=null,retry_after=null,
     last_status='rescan_required',updated_at=now()
   where connection_id=p_connection_id returning * into v_state;
 end if;
 if v_state.retry_after>now() then
   return jsonb_build_object('state','backoff','retry_after',v_state.retry_after);
 end if;
 if v_state.lease_until>now() then
   return jsonb_build_object('state','busy','lease_until',v_state.lease_until);
 end if;
 v_token := gen_random_uuid();
 update public.gmail_sync_state set lease_token=v_token,
   lease_until=now()+interval '90 seconds',last_attempt_at=now(),
   last_status='running',updated_at=now()
 where connection_id=p_connection_id returning * into v_state;
 return jsonb_build_object('state','claimed','lease_token',v_token,
   'mode',v_state.mode,'label_id',v_state.label_id,
   'anchor_history_id',v_state.anchor_history_id,'history_id',v_state.history_id,
   'initial_page_token',v_state.initial_page_token,
   'history_page_token',v_state.history_page_token,
   'pending_ids',to_jsonb(v_state.pending_ids));
end;
$$;
revoke all on function public.focusos_claim_gmail_sync(uuid,text,text) from public,anon;
grant execute on function public.focusos_claim_gmail_sync(uuid,text,text) to authenticated;

create function public.focusos_finish_gmail_sync(
 p_connection_id uuid,p_lease_token uuid,p_action text,
 p_page_token text default null,p_history_id text default null,
 p_pending_ids text[] default null,p_processed_count integer default null,
 p_retry_seconds integer default null,p_error text default null
) returns boolean language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_state public.gmail_sync_state;
declare v_remaining text[];
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 select * into v_state from public.gmail_sync_state
   where connection_id=p_connection_id and user_id=v_owner
     and lease_token=p_lease_token and lease_until>now() for update;
 if v_state.connection_id is null then return false; end if;
 if p_page_token is not null and (char_length(p_page_token)>1024
   or p_page_token !~ '^[A-Za-z0-9_=-]+$') then
   raise exception 'Invalid page token' using errcode='22023';
 end if;
 if p_history_id is not null and p_history_id !~ '^[0-9]{1,30}$' then
   raise exception 'Invalid history ID' using errcode='22023';
 end if;
 if p_action='initial_page' and v_state.mode='initial' then
   update public.gmail_sync_state set
     initial_page_token=p_page_token,
     mode=case when p_page_token is null then 'history' else 'initial' end,
     history_id=case when p_page_token is null then anchor_history_id else history_id end,
     last_status=case when p_page_token is null then 'complete' else 'partial' end,
     last_success_at=now(),last_error=null,retry_after=null
     where connection_id=p_connection_id;
 elsif p_action='history_staged' and v_state.mode='history'
   and cardinality(v_state.pending_ids)=0 then
   if p_pending_ids is null or cardinality(p_pending_ids)<1
      or cardinality(p_pending_ids)>30 or p_history_id is null
      or exists(select 1 from unnest(p_pending_ids) x where x !~ '^[A-Za-z0-9_-]{1,128}$')
   then raise exception 'Invalid staged IDs' using errcode='22023'; end if;
   update public.gmail_sync_state set pending_ids=p_pending_ids,
     pending_next_page_token=p_page_token,pending_new_history_id=p_history_id,
     last_status='partial',last_error=null,retry_after=null
     where connection_id=p_connection_id;
 elsif p_action='pending_advanced' and v_state.mode='history'
   and cardinality(v_state.pending_ids)>0 then
   if p_processed_count is null or p_processed_count<1
     or p_processed_count>2 or p_processed_count>cardinality(v_state.pending_ids)
   then raise exception 'Invalid processed count' using errcode='22023'; end if;
   v_remaining := v_state.pending_ids[p_processed_count+1:];
   update public.gmail_sync_state set pending_ids=coalesce(v_remaining,'{}'),
     history_page_token=case when cardinality(v_remaining)=0 then pending_next_page_token else history_page_token end,
     history_id=case when cardinality(v_remaining)=0 and pending_next_page_token is null
       then pending_new_history_id else history_id end,
     pending_next_page_token=case when cardinality(v_remaining)=0 then null else pending_next_page_token end,
     pending_new_history_id=case when cardinality(v_remaining)=0 then null else pending_new_history_id end,
     last_status=case when cardinality(v_remaining)=0 and v_state.pending_next_page_token is null
       then 'complete' else 'partial' end,
     last_success_at=now(),last_error=null,retry_after=null
     where connection_id=p_connection_id;
 elsif p_action='history_page' and v_state.mode='history'
   and cardinality(v_state.pending_ids)=0 and p_history_id is not null then
   update public.gmail_sync_state set history_page_token=p_page_token,
     history_id=case when p_page_token is null then p_history_id else history_id end,
     last_status=case when p_page_token is null then 'complete' else 'partial' end,
     last_success_at=now(),last_error=null,retry_after=null
     where connection_id=p_connection_id;
 elsif p_action='rescan' and p_history_id is not null then
   update public.gmail_sync_state set mode='initial',anchor_history_id=p_history_id,
     history_id=null,initial_page_token=null,history_page_token=null,
     pending_ids='{}',pending_next_page_token=null,pending_new_history_id=null,
     last_status='rescan_required',last_error='history_expired',retry_after=null
     where connection_id=p_connection_id;
 elsif p_action='retry' and p_retry_seconds between 1 and 3600
   and p_error in ('provider_unavailable','rate_limited') then
   update public.gmail_sync_state set retry_after=now()+make_interval(secs=>p_retry_seconds),
     last_status='retry_wait',last_error=p_error where connection_id=p_connection_id;
 elsif p_action='error' and p_error in ('invalid_provider_response','oversize_history','source_error') then
   update public.gmail_sync_state set last_status='error',last_error=p_error
     where connection_id=p_connection_id;
 else
   raise exception 'Invalid Gmail sync transition' using errcode='22023';
 end if;
 update public.gmail_sync_state set lease_token=null,lease_until=null,updated_at=now()
   where connection_id=p_connection_id;
 return true;
end;
$$;
revoke all on function public.focusos_finish_gmail_sync(
 uuid,uuid,text,text,text,text[],integer,integer,text) from public,anon;
grant execute on function public.focusos_finish_gmail_sync(
 uuid,uuid,text,text,text,text[],integer,integer,text) to authenticated;
