-- Phase 7.1: run-scoped command state and a redacted, owner-scoped tool ledger.
create table public.command_runs (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 request_key uuid not null,
 command text not null check(char_length(command) between 1 and 1000),
 status text not null default 'pending' check(status in ('pending','running','waiting','succeeded','clarify','failed')),
 stage text not null default 'start' check(stage in ('start','tasks','calendar','memory','planning','done')),
 version integer not null default 1 check(version>0),
 model_turns integer not null default 0 check(model_turns between 0 and 4),
 tool_calls_count integer not null default 0 check(tool_calls_count between 0 and 8),
 checkpoint jsonb not null default '{}'::jsonb check(jsonb_typeof(checkpoint)='object' and pg_column_size(checkpoint)<=32768),
 result jsonb check(result is null or (jsonb_typeof(result)='object' and pg_column_size(result)<=32768)),
 safe_error text,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 expires_at timestamptz not null default now()+interval '15 minutes',
 unique(user_id,request_key),
 unique(user_id,id)
);
create index command_runs_owner_created_idx on public.command_runs(user_id,created_at desc);
alter table public.command_runs enable row level security;
revoke all on public.command_runs from public,anon,authenticated;
grant select(id,user_id,request_key,command,status,stage,version,model_turns,tool_calls_count,checkpoint,result,safe_error,created_at,updated_at,expires_at)
 on public.command_runs to authenticated;
create policy command_runs_read_own on public.command_runs for select to authenticated
 using ((select auth.uid())=user_id);

create table public.agent_tool_calls (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null,
 run_id uuid not null,
 ordinal integer not null check(ordinal between 1 and 8),
 name text not null check(name in ('tasks.list','calendar.get_events','calendar.find_free_time','memory.search')),
 arguments_hash text not null check(arguments_hash ~ '^[0-9a-f]{64}$'),
 status text not null check(status in ('requested','succeeded','rejected','failed')),
 safe_code text,
 created_at timestamptz not null default now(),
 unique(run_id,ordinal),
 constraint tool_calls_owned_run foreign key(user_id,run_id)
  references public.command_runs(user_id,id) on delete cascade
);
create index agent_tool_calls_run_idx on public.agent_tool_calls(user_id,run_id,ordinal);
alter table public.agent_tool_calls enable row level security;
revoke all on public.agent_tool_calls from public,anon,authenticated;
grant select(id,user_id,run_id,ordinal,name,arguments_hash,status,safe_code,created_at)
 on public.agent_tool_calls to authenticated;
create policy agent_tool_calls_read_own on public.agent_tool_calls for select to authenticated
 using ((select auth.uid())=user_id);

create function public.focusos_start_command_run(p_request_key uuid,p_command text)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.command_runs;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_request_key is null or char_length(btrim(p_command)) not between 1 and 1000
 then raise exception 'Invalid command' using errcode='22023'; end if;
 insert into public.command_runs(user_id,request_key,command)
 values(v_owner,p_request_key,btrim(p_command))
 on conflict(user_id,request_key) do nothing;
 select * into v_row from public.command_runs
 where user_id=v_owner and request_key=p_request_key;
 if v_row.command<>btrim(p_command) then
   raise exception 'Request key reused for different command' using errcode='23505';
 end if;
 return jsonb_build_object('id',v_row.id,'status',v_row.status,'version',v_row.version);
end; $$;
revoke all on function public.focusos_start_command_run(uuid,text) from public,anon;
grant execute on function public.focusos_start_command_run(uuid,text) to authenticated;

create function public.focusos_checkpoint_command_run(
 p_run_id uuid,p_expected_version integer,p_status text,p_stage text,
 p_checkpoint jsonb,p_result jsonb,p_model_turns integer,p_tool_calls_count integer,p_safe_error text
) returns boolean language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid());
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_status not in ('pending','running','waiting','succeeded','clarify','failed')
 or p_stage not in ('start','tasks','calendar','memory','planning','done')
 or p_model_turns not between 0 and 4 or p_tool_calls_count not between 0 and 8
 or p_checkpoint is null or jsonb_typeof(p_checkpoint)<>'object'
 or pg_column_size(p_checkpoint)>32768
 or (p_result is not null and (jsonb_typeof(p_result)<>'object' or pg_column_size(p_result)>32768))
 or char_length(coalesce(p_safe_error,''))>80
 then raise exception 'Invalid checkpoint' using errcode='22023'; end if;
 update public.command_runs set status=p_status,stage=p_stage,checkpoint=p_checkpoint,
   result=p_result,model_turns=p_model_turns,tool_calls_count=p_tool_calls_count,
   safe_error=p_safe_error,version=version+1,updated_at=now()
 where id=p_run_id and user_id=v_owner and version=p_expected_version
   and status not in ('succeeded','clarify','failed') and expires_at>now()
   and model_turns<=p_model_turns and tool_calls_count<=p_tool_calls_count;
 return found;
end; $$;
revoke all on function public.focusos_checkpoint_command_run(uuid,integer,text,text,jsonb,jsonb,integer,integer,text)
 from public,anon;
grant execute on function public.focusos_checkpoint_command_run(uuid,integer,text,text,jsonb,jsonb,integer,integer,text)
 to authenticated;

create function public.focusos_log_tool_call(
 p_run_id uuid,p_ordinal integer,p_name text,p_arguments_hash text,p_status text,p_safe_code text
) returns boolean language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid());
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_ordinal not between 1 and 8 or p_name not in ('tasks.list','calendar.get_events','calendar.find_free_time','memory.search')
 or p_arguments_hash !~ '^[0-9a-f]{64}$'
 or p_status not in ('requested','succeeded','rejected','failed')
 or char_length(coalesce(p_safe_code,''))>80
 then raise exception 'Invalid tool log' using errcode='22023'; end if;
 if not exists(select 1 from public.command_runs
   where id=p_run_id and user_id=v_owner and status not in ('succeeded','clarify','failed') and expires_at>now())
 then return false; end if;
 insert into public.agent_tool_calls(user_id,run_id,ordinal,name,arguments_hash,status,safe_code)
 values(v_owner,p_run_id,p_ordinal,p_name,p_arguments_hash,p_status,p_safe_code)
 on conflict(run_id,ordinal) do update set
   status=excluded.status,safe_code=excluded.safe_code
 where public.agent_tool_calls.user_id=v_owner
   and public.agent_tool_calls.name=excluded.name
   and public.agent_tool_calls.arguments_hash=excluded.arguments_hash;
 return found;
end; $$;
revoke all on function public.focusos_log_tool_call(uuid,integer,text,text,text,text) from public,anon;
grant execute on function public.focusos_log_tool_call(uuid,integer,text,text,text,text) to authenticated;
