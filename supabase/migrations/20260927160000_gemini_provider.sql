-- Change vector provenance to Gemini while preserving confirmed memories.
-- Existing OpenAI vectors and in-flight leases cannot be reused across embedding spaces.
alter table public.memories drop constraint memory_embedding_shape;
update public.memories set embedding=null, embedding_model=null, embedding_dim=null,
  embedding_hash=null, embedding_status='pending', embedding_error=null,
  embedding_lease_token=null, embedding_lease_until=null, embedding_updated_at=now()
where embedding is not null or embedding_status='processing' or embedding_model is not null;
alter table public.memories add constraint memory_embedding_shape check(
  (embedding_status='ready' and embedding is not null and embedding_model='gemini-embedding-2'
   and embedding_dim=256 and embedding_hash ~ '^[0-9a-f]{64}$')
  or (embedding_status<>'ready' and embedding is null)
);

create or replace function public.focusos_claim_memory_embedding(
 p_memory_id uuid,p_model text,p_dim integer,p_content_hash text
) returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.memories; v_lease uuid;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_model<>'gemini-embedding-2' or p_dim<>256 or p_content_hash !~ '^[0-9a-f]{64}$'
 then raise exception 'Invalid embedding contract' using errcode='22023'; end if;
 select * into v_row from public.memories where id=p_memory_id and user_id=v_owner for update;
 if v_row.id is null or v_row.status<>'active' or not exists(
   select 1 from public.source_items s where s.id=v_row.source_id and s.user_id=v_owner
      and s.deleted_at is null and s.body_hash=v_row.source_hash)
 then return jsonb_build_object('state','unavailable'); end if;
 if v_row.embedding_status='ready' and v_row.embedding_model=p_model
    and v_row.embedding_dim=p_dim and v_row.embedding_hash=p_content_hash
 then return jsonb_build_object('state','reused'); end if;
 if v_row.embedding_status='processing' and v_row.embedding_lease_until>now()
 then return jsonb_build_object('state','busy'); end if;
 v_lease:=gen_random_uuid();
 update public.memories set embedding_status='processing',embedding=null,
   embedding_model=null,embedding_dim=null,embedding_hash=null,embedding_error=null,
   embedding_lease_token=v_lease,embedding_lease_until=now()+interval '45 seconds',
   embedding_updated_at=now()
 where id=p_memory_id and user_id=v_owner;
 return jsonb_build_object('state','claimed','lease_token',v_lease,
   'text',v_row.text,'quote',v_row.evidence_quote,'source_hash',v_row.source_hash);
end; $$;
revoke all on function public.focusos_claim_memory_embedding(uuid,text,integer,text) from public,anon;
grant execute on function public.focusos_claim_memory_embedding(uuid,text,integer,text) to authenticated;

create or replace function public.focusos_finish_memory_embedding(
 p_memory_id uuid,p_lease_token uuid,p_content_hash text,p_vector text,p_error text
) returns boolean language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid());
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_error is not null and p_error not in ('provider_unconfigured','provider_unavailable','invalid_vector')
 then raise exception 'Invalid embedding error' using errcode='22023'; end if;
 if p_error is null and (p_vector is null or p_content_hash !~ '^[0-9a-f]{64}$')
 then raise exception 'Invalid embedding result' using errcode='22023'; end if;
 if p_error is null then
   update public.memories m set embedding=p_vector::extensions.vector(256),
     embedding_model='gemini-embedding-2',embedding_dim=256,
     embedding_hash=p_content_hash,embedding_status='ready',embedding_error=null,
     embedding_lease_token=null,embedding_lease_until=null,embedding_updated_at=now()
   where m.id=p_memory_id and m.user_id=v_owner and m.status='active'
     and m.embedding_status='processing' and m.embedding_lease_token=p_lease_token
     and m.embedding_lease_until>now()
     and exists(select 1 from public.source_items s where s.id=m.source_id
       and s.user_id=v_owner and s.deleted_at is null and s.body_hash=m.source_hash);
 else
   update public.memories m set embedding_status='failed',embedding_error=p_error,
     embedding_lease_token=null,embedding_lease_until=null,embedding_updated_at=now()
   where m.id=p_memory_id and m.user_id=v_owner and m.status='active'
     and m.embedding_status='processing' and m.embedding_lease_token=p_lease_token
     and m.embedding_lease_until>now();
 end if;
 return found;
end; $$;
revoke all on function public.focusos_finish_memory_embedding(uuid,uuid,text,text,text) from public,anon;
grant execute on function public.focusos_finish_memory_embedding(uuid,uuid,text,text,text) to authenticated;

-- Phase 7.6: owner/project/source-filtered exact vector and lexical memory retrieval.
create or replace function public.focusos_search_memories(
 p_query text,p_vector text,p_project_id uuid,p_limit integer
) returns jsonb language plpgsql stable security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_result jsonb;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if char_length(btrim(p_query)) not between 1 and 1000 or p_limit not between 1 and 5
 then raise exception 'Invalid memory search' using errcode='22023'; end if;
 if p_vector is not null and extensions.vector_dims(p_vector::extensions.vector)<>256
 then raise exception 'Invalid query vector dimension' using errcode='22023'; end if;
 if p_project_id is not null and not exists(select 1 from public.projects
   where id=p_project_id and user_id=v_owner) then return '[]'::jsonb; end if;
 with eligible as (
   select m.id,m.text,m.evidence_quote,m.source_id,m.project_id,s.source_ref,
      case when p_vector is not null and m.embedding_status='ready'
        and m.embedding_model='gemini-embedding-2' and m.embedding_dim=256
        then 1-(m.embedding OPERATOR(extensions.<=>) p_vector::extensions.vector(256))
        else null end as semantic_score,
      pg_catalog.ts_rank(
        pg_catalog.to_tsvector('pg_catalog.simple'::regconfig,m.text||' '||m.evidence_quote),
        pg_catalog.plainto_tsquery('pg_catalog.simple'::regconfig,p_query)
      ) as lexical_score
   from public.memories m
   join public.source_items s on s.id=m.source_id and s.user_id=m.user_id
   where m.user_id=v_owner and m.status='active' and s.deleted_at is null
     and s.body_hash=m.source_hash
     and (p_project_id is null or m.project_id=p_project_id)
 ), ranked as (
   select id,text,evidence_quote,source_id,project_id,source_ref,
     case when semantic_score is not null and semantic_score>=0.2
       then 'semantic' else 'lexical' end as match_kind,
     case when semantic_score is not null and semantic_score>=0.2
       then semantic_score else lexical_score::float8 end as score
   from eligible where (semantic_score is not null and semantic_score>=0.2)
      or lexical_score>0
 )
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r)),'[]'::jsonb) into v_result
 from (select * from ranked order by
   case when match_kind='semantic' then 0 else 1 end,score desc,id
   limit p_limit) r;
 return v_result;
end; $$;
revoke all on function public.focusos_search_memories(text,text,uuid,integer) from public,anon;
grant execute on function public.focusos_search_memories(text,text,uuid,integer) to authenticated;

-- Preserve the provider actually used for new extraction telemetry.
create or replace function public.focusos_start_extraction_run(
  p_source_id uuid, p_model text, p_schema text, p_prompt text
) returns uuid language plpgsql security definer set search_path = ''
as $$
declare v_owner uuid := (select auth.uid()); v_id uuid;
begin
  if v_owner is null then raise exception 'Authentication required' using errcode = '28000'; end if;
  if not exists (select 1 from public.source_items where id=p_source_id and user_id=v_owner and deleted_at is null)
    then raise exception 'Source unavailable' using errcode = 'P0002'; end if;
  insert into public.agent_runs(user_id,source_id,trigger,status,provider,model_version,schema_version,prompt_version)
  values(v_owner,p_source_id,'extraction','running','gemini',p_model,p_schema,p_prompt)
  returning id into v_id;
  return v_id;
end;
$$;
revoke all on function public.focusos_start_extraction_run(uuid,text,text,text) from public, anon;
grant execute on function public.focusos_start_extraction_run(uuid,text,text,text) to authenticated;

