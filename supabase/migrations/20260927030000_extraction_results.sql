-- Phase 4.5: one recoverable extraction claim per source/content/model contract.
create table public.extraction_results (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  source_id uuid not null,
  content_hash text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  schema_version text not null,
  prompt_version text not null,
  model_version text not null,
  status text not null check (status in ('processing','ready','failed')),
  validated_payload jsonb,
  safe_error text,
  claim_token uuid,
  lease_expires_at timestamptz,
  run_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  reviewed_at timestamptz,
  constraint extraction_source_owner foreign key (user_id,source_id)
    references public.source_items(user_id,id) on delete cascade,
  constraint extraction_run_fk foreign key (run_id)
    references public.agent_runs(id) on delete set null,
  constraint extraction_dedupe unique (source_id,content_hash,schema_version,prompt_version,model_version)
);
create index extraction_results_owner_status_idx on public.extraction_results (user_id,status,updated_at desc);
alter table public.extraction_results enable row level security;
revoke all on public.extraction_results from public,anon,authenticated;
grant select (id,user_id,source_id,content_hash,schema_version,prompt_version,model_version,
 status,validated_payload,safe_error,lease_expires_at,run_id,created_at,updated_at,reviewed_at)
 on public.extraction_results to authenticated;
create policy extraction_results_read_own on public.extraction_results for select to authenticated
 using ((select auth.uid()) = user_id);

create function public.focusos_claim_extraction(
 p_source_id uuid, p_content_hash text, p_schema text, p_prompt text, p_model text
) returns jsonb language plpgsql security definer set search_path = ''
as $$
declare v_owner uuid := (select auth.uid()); v_source public.source_items;
declare v_result public.extraction_results; v_token uuid;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext(v_owner::text));
 select * into v_source from public.source_items
  where id=p_source_id and user_id=v_owner and deleted_at is null;
 if v_source.id is null then return jsonb_build_object('state','missing'); end if;
 if v_source.normalized_body is null or v_source.body_expires_at<=now()
   or v_source.body_hash<>p_content_hash then
   return jsonb_build_object('state','source_unavailable');
 end if;
 select * into v_result from public.extraction_results
  where source_id=p_source_id and content_hash=p_content_hash
    and schema_version=p_schema and prompt_version=p_prompt and model_version=p_model
  for update;
 if v_result.id is not null and v_result.status='ready' then
   return jsonb_build_object('state','ready','id',v_result.id);
 end if;
 if v_result.id is not null and v_result.status='processing'
    and v_result.lease_expires_at>now() then
   return jsonb_build_object('state','processing','id',v_result.id);
 end if;
 if (select count(*) from public.agent_runs where user_id=v_owner
     and trigger='extraction' and started_at>now()-interval '10 minutes')>=5 then
   return jsonb_build_object('state','rate_limited');
 end if;
 v_token := gen_random_uuid();
 if v_result.id is null then
   insert into public.extraction_results
     (user_id,source_id,content_hash,schema_version,prompt_version,model_version,
      status,claim_token,lease_expires_at)
   values(v_owner,p_source_id,p_content_hash,p_schema,p_prompt,p_model,
      'processing',v_token,now()+interval '90 seconds')
   returning * into v_result;
 else
   update public.extraction_results set status='processing',validated_payload=null,
      safe_error=null,claim_token=v_token,lease_expires_at=now()+interval '90 seconds',
      updated_at=now()
   where id=v_result.id returning * into v_result;
 end if;
 return jsonb_build_object('state','claimed','id',v_result.id,'claim_token',v_token);
end;
$$;
revoke all on function public.focusos_claim_extraction(uuid,text,text,text,text) from public,anon;
grant execute on function public.focusos_claim_extraction(uuid,text,text,text,text) to authenticated;

create function public.focusos_finish_extraction(
 p_result_id uuid,p_claim_token uuid,p_status text,p_payload jsonb,
 p_safe_error text,p_run_id uuid
) returns boolean language plpgsql security definer set search_path = ''
as $$
declare v_owner uuid := (select auth.uid());
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_status not in ('ready','failed') or (p_status='ready' and p_payload is null)
   or (p_status='failed' and p_payload is not null) then
   raise exception 'Invalid extraction outcome' using errcode='22023';
 end if;
 update public.extraction_results set status=p_status,validated_payload=p_payload,
   safe_error=p_safe_error,run_id=p_run_id,claim_token=null,lease_expires_at=null,updated_at=now()
 where id=p_result_id and user_id=v_owner and claim_token=p_claim_token
   and status='processing' and lease_expires_at>now();
 return found;
end;
$$;
revoke all on function public.focusos_finish_extraction(uuid,uuid,text,jsonb,text,uuid)
 from public,anon;
grant execute on function public.focusos_finish_extraction(uuid,uuid,text,jsonb,text,uuid)
 to authenticated;
