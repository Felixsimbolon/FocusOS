-- Synthetic data only; every write is rolled back. Run against migrated DB.
begin;
do $$
declare owner uuid:=gen_random_uuid(); other uuid:=gen_random_uuid();
begin
 insert into auth.users(id,aud,role,email) values(owner,'authenticated','authenticated','focusos-personal-probe@example.test'),(other,'authenticated','authenticated','focusos-other-probe@example.test');
 insert into public.profiles(id,timezone,working_hours) values(owner,'UTC','{"days":[1,2,3,4,5,6,7],"start_minute":0,"end_minute":1440}') on conflict(id) do nothing;
 perform set_config('probe.owner',owner::text,true);perform set_config('probe.other',other::text,true);
 perform set_config('probe.request',gen_random_uuid()::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('probe.owner'),true);
do $$
declare r jsonb; t uuid; m uuid; v integer;
begin
 r:=public.focusos_create_task_with_memory(current_setting('probe.request')::uuid,repeat('a',64),'{"title":"Original probe","priority":"normal","due_kind":"none","estimate_minutes":30}');
 t:=(r->'task'->>'id')::uuid;m:=(r->>'memory_id')::uuid;v:=(r->'task'->>'version')::integer;
 perform set_config('probe.memory',m::text,true);
 perform public.focusos_update_task(t,v,'{"title":"Updated probe","status":"done","estimate_minutes":45}');
 if not exists(select 1 from public.memories where id=m and text like '%Updated probe%' and text like '%done%' and embedding_status='pending' and evidence_quote='Updated probe') then raise exception 'Task memory is stale';end if;
 r:=public.focusos_create_task_with_memory(current_setting('probe.request')::uuid,repeat('a',64),'{"title":"Original probe","priority":"normal","due_kind":"none","estimate_minutes":30}');
 if r->'task' ? 'review_hash' or r->'task' ? 'user_id' then raise exception 'Internal task fields exposed';end if;
 if r->>'replayed'<>'true' or r->'task'->>'title'<>'Updated probe' then raise exception 'Edited task replay failed';end if;
 if has_function_privilege('authenticated','public.focusos_claim_job(uuid,uuid)','execute') or has_schema_privilege('authenticated','private','usage') then raise exception 'Private queue permissions leaked';end if;
end $$;
reset role;
set local role service_role;
do $$
declare id uuid:=gen_random_uuid(); key uuid:=gen_random_uuid(); r jsonb;c jsonb;
begin
 r:=public.focusos_enqueue_job(id,current_setting('probe.owner')::uuid,key,'embedding',current_setting('probe.memory')::uuid,'synthetic-ciphertext',1,now()+interval '10 minutes');
 perform set_config('probe.job',id::text,true);
 if (public.focusos_enqueue_job(gen_random_uuid(),current_setting('probe.owner')::uuid,key,'embedding',current_setting('probe.memory')::uuid,'synthetic-ciphertext',1,now()+interval '10 minutes')->>'id')<>id::text then raise exception 'Queue replay duplicated';end if;
 if public.focusos_claim_job(id,current_setting('probe.other')::uuid) is not null then raise exception 'Foreign claim accepted';end if;
 c:=public.focusos_claim_job(id,current_setting('probe.owner')::uuid);
 if c is null or c->>'ciphertext'<>'synthetic-ciphertext' then raise exception 'Claim failed';end if;
 if public.focusos_claim_job(id,current_setting('probe.owner')::uuid) is not null then raise exception 'Double claim accepted';end if;
 if public.focusos_finish_job(id,gen_random_uuid(),'succeeded','{}','{}',null) then raise exception 'Wrong lease accepted';end if;
 if not public.focusos_finish_job(id,(c->>'lease_token')::uuid,'queued','{"phase":"retry"}','{}','provider_unavailable',60,true) then raise exception 'Checkpoint failed';end if;
 if public.focusos_claim_job(id,current_setting('probe.owner')::uuid) is not null then raise exception 'Backoff ignored';end if;
end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('probe.other'),true);
do $$ begin
 if exists(select 1 from public.work_jobs where id=current_setting('probe.job')::uuid) then raise exception 'Foreign job visible';end if;
 if public.focusos_cancel_job(current_setting('probe.job')::uuid) then raise exception 'Foreign cancellation accepted';end if;
end $$;
select set_config('request.jwt.claim.sub',current_setting('probe.owner'),true);
do $$ begin
 if not exists(select 1 from public.work_jobs where id=current_setting('probe.job')::uuid) then raise exception 'Owned job missing';end if;
 if not public.focusos_cancel_job(current_setting('probe.job')::uuid) then raise exception 'Owner cancellation failed';end if;
end $$;
reset role;
do $$ begin
 if exists(select 1 from private.work_job_tokens where job_id=current_setting('probe.job')::uuid) then raise exception 'Cancelled session not removed';end if;
end $$;
rollback;
