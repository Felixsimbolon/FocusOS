-- Phase 4.4: redacted extraction telemetry, never prompts or credentials.
create table public.agent_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  source_id uuid not null,
  trigger text not null check (trigger in ('extraction', 'command', 'eval')),
  status text not null check (status in ('running', 'succeeded', 'failed')),
  provider text not null,
  model_version text not null,
  schema_version text not null,
  prompt_version text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  latency_ms integer check (latency_ms is null or latency_ms >= 0),
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0),
  safe_error text check (safe_error is null or safe_error in
    ('provider_unconfigured','source_unavailable','invalid_reference_time','timeout',
     'provider_error','oversize_response','incomplete','refused','malformed','invalid_output',
     'database_error')),
  constraint agent_runs_owned_source foreign key (user_id, source_id)
    references public.source_items(user_id,id) on delete cascade
);
create index agent_runs_owner_started_idx on public.agent_runs (user_id, started_at desc);
alter table public.agent_runs enable row level security;
revoke all on public.agent_runs from public, anon, authenticated;
grant select (id,user_id,source_id,trigger,status,provider,model_version,schema_version,
  prompt_version,started_at,finished_at,latency_ms,input_tokens,output_tokens,safe_error)
  on public.agent_runs to authenticated;
create policy agent_runs_read_own on public.agent_runs for select to authenticated
  using ((select auth.uid()) = user_id);

create function public.focusos_start_extraction_run(
  p_source_id uuid, p_model text, p_schema text, p_prompt text
) returns uuid language plpgsql security definer set search_path = ''
as $$
declare v_owner uuid := (select auth.uid()); v_id uuid;
begin
  if v_owner is null then raise exception 'Authentication required' using errcode = '28000'; end if;
  if not exists (select 1 from public.source_items where id=p_source_id and user_id=v_owner and deleted_at is null)
    then raise exception 'Source unavailable' using errcode = 'P0002'; end if;
  insert into public.agent_runs(user_id,source_id,trigger,status,provider,model_version,schema_version,prompt_version)
  values(v_owner,p_source_id,'extraction','running','openai',p_model,p_schema,p_prompt)
  returning id into v_id;
  return v_id;
end;
$$;
revoke all on function public.focusos_start_extraction_run(uuid,text,text,text) from public, anon;
grant execute on function public.focusos_start_extraction_run(uuid,text,text,text) to authenticated;

create function public.focusos_finish_extraction_run(
  p_run_id uuid, p_status text, p_latency_ms integer,
  p_input_tokens integer, p_output_tokens integer, p_safe_error text
) returns boolean language plpgsql security definer set search_path = ''
as $$
declare v_owner uuid := (select auth.uid());
begin
  if v_owner is null then raise exception 'Authentication required' using errcode = '28000'; end if;
  if p_status not in ('succeeded','failed') or p_latency_ms < 0
     or (p_safe_error is not null and p_safe_error not in
       ('provider_unconfigured','source_unavailable','invalid_reference_time','timeout',
        'provider_error','oversize_response','incomplete','refused','malformed','invalid_output',
        'database_error'))
     then raise exception 'Invalid run outcome' using errcode = '22023'; end if;
  update public.agent_runs set status=p_status,finished_at=now(),latency_ms=p_latency_ms,
    input_tokens=p_input_tokens,output_tokens=p_output_tokens,safe_error=p_safe_error
    where id=p_run_id and user_id=v_owner and status='running';
  return found;
end;
$$;
revoke all on function public.focusos_finish_extraction_run(uuid,text,integer,integer,integer,text)
  from public, anon;
grant execute on function public.focusos_finish_extraction_run(uuid,text,integer,integer,integer,text)
  to authenticated;
