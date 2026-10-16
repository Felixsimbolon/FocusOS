-- Priority for each synced email (urgent / normal / fyi) with a short reason. The model
-- proposes; a user's correction is kept and later shown to the model as an example.
create table public.email_triage (
 user_id uuid not null references auth.users(id) on delete cascade,
 source_id uuid not null references public.source_items(id) on delete cascade,
 priority text not null check(priority in ('urgent','normal','fyi')),
 model_priority text check(model_priority is null or model_priority in ('urgent','normal','fyi')),
 reason text check(reason is null or char_length(reason) between 1 and 200),
 corrected boolean not null default false,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 primary key(user_id,source_id)
);
create index email_triage_owner_updated on public.email_triage(user_id,updated_at desc);
create index email_triage_corrections on public.email_triage(user_id,updated_at desc) where corrected;
alter table public.email_triage enable row level security;
revoke all on public.email_triage from public,anon,authenticated;
grant select(user_id,source_id,priority,model_priority,reason,corrected,created_at,updated_at) on public.email_triage to authenticated;
create policy email_triage_read_owner on public.email_triage for select to authenticated using(user_id=(select auth.uid()));

-- p_by_user=false: the model's proposal; never overwrites a user's correction.
-- p_by_user=true: the user's correction; the model's original is kept for evaluation.
create function public.focusos_save_triage(p_source_id uuid,p_priority text,p_reason text,p_by_user boolean)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.email_triage;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_priority is null or p_priority not in ('urgent','normal','fyi') or p_by_user is null
   or (p_reason is not null and char_length(p_reason) not between 1 and 200)
 then raise exception 'Invalid triage' using errcode='22023'; end if;
 if not exists(select 1 from public.source_items s where s.id=p_source_id and s.user_id=v_owner
               and s.kind='gmail' and s.deleted_at is null)
 then raise exception 'Email not found' using errcode='P0002'; end if;
 if p_by_user then
   insert into public.email_triage(user_id,source_id,priority,reason,corrected)
   values(v_owner,p_source_id,p_priority,null,true)
   on conflict(user_id,source_id) do update set priority=excluded.priority,corrected=true,updated_at=now()
   returning * into v_row;
 else
   insert into public.email_triage(user_id,source_id,priority,model_priority,reason)
   values(v_owner,p_source_id,p_priority,p_priority,p_reason)
   on conflict(user_id,source_id) do update set model_priority=excluded.model_priority,reason=excluded.reason,
     priority=case when public.email_triage.corrected then public.email_triage.priority else excluded.priority end,
     updated_at=now()
   returning * into v_row;
 end if;
 return pg_catalog.jsonb_build_object('source_id',v_row.source_id,'priority',v_row.priority,
   'model_priority',v_row.model_priority,'corrected',v_row.corrected);
end; $$;
revoke all on function public.focusos_save_triage(uuid,text,text,boolean) from public,anon;
grant execute on function public.focusos_save_triage(uuid,text,text,boolean) to authenticated;
