-- Semantic floor 0.2 -> 0.6. gemini-embedding-2 (256 dims) scores almost every memory above 0.5,
-- so 0.2 never filtered anything. On the live eval corpus (2026-10-16) relevant memories scored
-- 0.67-0.88; at 0.6 all were kept and 81% fewer unrelated memories reached the answer model.
create or replace function public.focusos_search_memories_hybrid(
 p_query text,p_terms text[],p_vector text,p_limit integer
) returns jsonb language plpgsql stable security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_result jsonb; v_query tsquery;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if char_length(btrim(p_query)) not between 1 and 1000 or p_limit not between 1 and 10
   or coalesce(pg_catalog.array_length(p_terms,1),0)>16
   or exists(select 1 from pg_catalog.unnest(coalesce(p_terms,'{}'::text[])) t where t !~ '^[a-z0-9]{2,40}$')
 then raise exception 'Invalid memory search' using errcode='22023'; end if;
 if p_vector is not null and extensions.vector_dims(p_vector::extensions.vector)<>256
 then raise exception 'Invalid query vector dimension' using errcode='22023'; end if;
 if coalesce(pg_catalog.array_length(p_terms,1),0)>0 then
   select pg_catalog.to_tsquery('pg_catalog.simple'::regconfig,pg_catalog.string_agg(t||':*',' | '))
   into v_query from pg_catalog.unnest(p_terms) t;
 end if;
 with eligible as (
   select m.id,m.text,m.evidence_quote,m.source_id,m.project_id,s.source_ref,
      case when p_vector is not null and m.embedding_status='ready'
        and m.embedding_model='gemini-embedding-2' and m.embedding_dim=256
        then 1-(m.embedding OPERATOR(extensions.<=>) p_vector::extensions.vector(256))
        else null end as semantic_score,
      -- ts_rank alone gives unrelated rows a tiny positive score (1e-20), so require a real match.
      case when v_query is not null and pg_catalog.to_tsvector('pg_catalog.simple'::regconfig,m.text||' '||m.evidence_quote) @@ v_query
        then pg_catalog.ts_rank(pg_catalog.to_tsvector('pg_catalog.simple'::regconfig,m.text||' '||m.evidence_quote),v_query)
        else 0::real end as lexical_score
   from public.memories m
   join public.source_items s on s.id=m.source_id and s.user_id=m.user_id
   where m.user_id=v_owner and m.status='active' and s.deleted_at is null
     and s.body_hash=m.source_hash
 ), ranked as (
   select *,
     case when semantic_score>=0.6 then pg_catalog.row_number() over (order by semantic_score desc nulls last,id) end as semantic_rank,
     case when lexical_score>0 then pg_catalog.row_number() over (order by lexical_score desc,id) end as lexical_rank
   from eligible
 ), fused as (
   -- Reciprocal-rank fusion: agreement between both signals ranks highest.
   select id,text,evidence_quote,source_id,project_id,source_ref,
     case when semantic_rank is not null and lexical_rank is not null then 'hybrid'
          when lexical_rank is not null then 'lexical' else 'semantic' end as match_kind,
     coalesce(1.0/(60+semantic_rank),0)+coalesce(1.0/(60+lexical_rank),0) as score
   from ranked where semantic_rank is not null or lexical_rank is not null
 )
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r)),'[]'::jsonb) into v_result
 from (select * from fused order by score desc,id limit p_limit) r;
 return v_result;
end; $$;
revoke all on function public.focusos_search_memories_hybrid(text,text[],text,integer) from public,anon;
grant execute on function public.focusos_search_memories_hybrid(text,text[],text,integer) to authenticated;
