-- Per-user telemetry for model calls: timing, tokens, outcome and estimated cost.
-- Never stores prompt or response text. Rows are written in batches by the API
-- under the caller's session and kept for 90 days.
create table public.llm_calls (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 trace_id uuid not null,
 job_id uuid,
 purpose text not null check (purpose ~ '^[a-z_]{1,32}$'),
 operation text not null check (operation in ('generate','embed')),
 model text not null check (char_length(model) between 1 and 80),
 status text not null check (status in ('ok','rate_limited','timeout','error')),
 http_status integer check (http_status between 100 and 599),
 prompt_tokens integer check (prompt_tokens between 0 and 10000000),
 output_tokens integer check (output_tokens between 0 and 10000000),
 latency_ms integer not null check (latency_ms between 0 and 600000),
 cost_usd numeric(12,6) check (cost_usd >= 0),
 created_at timestamptz not null default now()
);
create index llm_calls_user_time on public.llm_calls(user_id, created_at desc);
alter table public.llm_calls enable row level security;
create policy llm_calls_select_own on public.llm_calls for select to authenticated using (user_id = (select auth.uid()));
grant select on public.llm_calls to authenticated;

create function public.focusos_record_llm_calls(p_calls jsonb) returns integer
language plpgsql security definer set search_path='' as $$
declare v_owner uuid := (select auth.uid()); v_count integer;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if jsonb_typeof(p_calls)<>'array' or jsonb_array_length(p_calls) not between 1 and 50
 then raise exception 'Invalid telemetry batch' using errcode='22023'; end if;
 insert into public.llm_calls(user_id,trace_id,job_id,purpose,operation,model,status,http_status,
   prompt_tokens,output_tokens,latency_ms,cost_usd,created_at)
 select v_owner,c.trace_id,c.job_id,c.purpose,c.operation,c.model,c.status,c.http_status,
   c.prompt_tokens,c.output_tokens,c.latency_ms,c.cost_usd,
   -- A client clock may only place a call in the recent past, never the future.
   least(now(),greatest(now()-interval '1 hour',coalesce(c.created_at,now())))
 from jsonb_to_recordset(p_calls) as c(trace_id uuid,job_id uuid,purpose text,operation text,model text,status text,
   http_status integer,prompt_tokens integer,output_tokens integer,latency_ms integer,cost_usd numeric,created_at timestamptz);
 get diagnostics v_count = row_count;
 delete from public.llm_calls where user_id=v_owner and created_at<now()-interval '90 days';
 return v_count;
end; $$;
revoke all on function public.focusos_record_llm_calls(jsonb) from public,anon;
grant execute on function public.focusos_record_llm_calls(jsonb) to authenticated;

-- Aggregates in the caller's timezone so "today" matches the user's day.
create function public.focusos_llm_usage(p_days integer,p_timezone text) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare v_owner uuid := (select auth.uid()); v_since timestamptz; v_result jsonb;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_days not between 1 and 90 or not exists(select 1 from pg_catalog.pg_timezone_names where name=p_timezone)
 then raise exception 'Invalid usage window' using errcode='22023'; end if;
 v_since := (date_trunc('day', now() at time zone p_timezone) - make_interval(days => p_days-1)) at time zone p_timezone;
 with calls as (
   select *, (created_at at time zone p_timezone)::date as day from public.llm_calls
   where user_id=v_owner and created_at>=v_since
 )
 select jsonb_build_object(
   'since', v_since,
   'totals', (select jsonb_build_object('calls',count(*),'errors',count(*) filter (where status<>'ok'),
       'rate_limited',count(*) filter (where status='rate_limited'),
       'prompt_tokens',coalesce(sum(prompt_tokens),0),'output_tokens',coalesce(sum(output_tokens),0),
       'cost_usd',sum(cost_usd),'p95_latency_ms',percentile_disc(0.95) within group (order by latency_ms)) from calls),
   'today_tokens', (select coalesce(sum(coalesce(prompt_tokens,0)+coalesce(output_tokens,0)),0) from calls
       where day=(now() at time zone p_timezone)::date),
   'by_day', coalesce((select jsonb_agg(d order by d->>'day') from (select jsonb_build_object('day',day,'calls',count(*),
       'tokens',coalesce(sum(coalesce(prompt_tokens,0)+coalesce(output_tokens,0)),0),'cost_usd',sum(cost_usd),
       'errors',count(*) filter (where status<>'ok')) d from calls group by day) days),'[]'::jsonb),
   'by_purpose', coalesce((select jsonb_agg(p order by (p->>'calls')::int desc) from (select jsonb_build_object('purpose',purpose,
       'calls',count(*),'errors',count(*) filter (where status<>'ok'),
       'tokens',coalesce(sum(coalesce(prompt_tokens,0)+coalesce(output_tokens,0)),0),
       'avg_latency_ms',round(avg(latency_ms))) p from calls group by purpose) purposes),'[]'::jsonb)
 ) into v_result;
 return v_result;
end; $$;
revoke all on function public.focusos_llm_usage(integer,text) from public,anon;
grant execute on function public.focusos_llm_usage(integer,text) to authenticated;
