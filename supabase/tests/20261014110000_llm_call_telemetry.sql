-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid(); other uuid:=gen_random_uuid();
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@telemetry-test.invalid'),
   (other,'authenticated','authenticated',other::text||'@telemetry-test.invalid');
 perform set_config('focusos.telemetry.owner',o::text,true);
 perform set_config('focusos.telemetry.other',other::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.telemetry.owner'),true);
do $$
declare usage jsonb; trace uuid:=gen_random_uuid();
begin
 if public.focusos_record_llm_calls(jsonb_build_array(
   jsonb_build_object('trace_id',trace,'purpose','intent','operation','generate','model','gemini-3.5-flash-lite','status','ok',
     'http_status',200,'prompt_tokens',1200,'output_tokens',80,'latency_ms',900,'cost_usd',0.000152),
   jsonb_build_object('trace_id',trace,'purpose','answer','operation','generate','model','gemini-3.5-flash-lite','status','rate_limited',
     'http_status',429,'latency_ms',300),
   -- A future client timestamp is clamped to now().
   jsonb_build_object('trace_id',trace,'purpose','embed_query','operation','embed','model','gemini-embedding-2','status','ok',
     'latency_ms',120,'created_at',now()+interval '3 days')))<>3 then raise exception 'Batch not recorded'; end if;
 if exists(select 1 from public.llm_calls where created_at>now()) then raise exception 'Future timestamp accepted'; end if;
 usage:=public.focusos_llm_usage(7,'Asia/Jakarta');
 if (usage->'totals'->>'calls')::int<>3 or (usage->'totals'->>'rate_limited')::int<>1
    or (usage->>'today_tokens')::int<>1280 or jsonb_array_length(usage->'by_purpose')<>3
 then raise exception 'Unexpected usage summary: %',usage; end if;
 begin
  perform public.focusos_record_llm_calls(jsonb_build_array(jsonb_build_object('trace_id',trace,'purpose','Bad Purpose!',
    'operation','generate','model','m','status','ok','latency_ms',1)));
  raise exception 'Invalid purpose accepted';
 exception when check_violation then null; end;
 begin
  perform public.focusos_record_llm_calls('[]'::jsonb);
  raise exception 'Empty batch accepted';
 exception when sqlstate '22023' then null; end;
 begin
  perform public.focusos_llm_usage(7,'Not/AZone');
  raise exception 'Invalid timezone accepted';
 exception when sqlstate '22023' then null; end;
 -- Rows are written only through the function, never directly.
 begin
  insert into public.llm_calls(user_id,trace_id,purpose,operation,model,status,latency_ms)
  values((select auth.uid()),trace,'intent','generate','m','ok',1);
  raise exception 'Direct insert allowed';
 exception when insufficient_privilege then null; end;
end $$;
select set_config('request.jwt.claim.sub',current_setting('focusos.telemetry.other'),true);
do $$
begin
 if exists(select 1 from public.llm_calls) then raise exception 'Another user can read telemetry'; end if;
 if (public.focusos_llm_usage(7,'UTC')->'totals'->>'calls')::int<>0 then raise exception 'Usage leaked across users'; end if;
end $$;
rollback;
