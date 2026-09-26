-- Phase 7.6: owner/project/source-filtered exact vector and lexical memory retrieval.
create function public.focusos_search_memories(
 p_query text,p_vector text,p_project_id uuid,p_limit integer
) returns jsonb language plpgsql stable security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_result jsonb;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if char_length(btrim(p_query)) not between 1 and 1000 or p_limit not between 1 and 5
 then raise exception 'Invalid memory search' using errcode='22023'; end if;
 if p_vector is not null and pg_catalog.vector_dims(p_vector::extensions.vector)<>256
 then raise exception 'Invalid query vector dimension' using errcode='22023'; end if;
 if p_project_id is not null and not exists(select 1 from public.projects
   where id=p_project_id and user_id=v_owner) then return '[]'::jsonb; end if;
 with eligible as (
   select m.id,m.text,m.evidence_quote,m.source_id,m.project_id,s.source_ref,
      case when p_vector is not null and m.embedding_status='ready'
        and m.embedding_model='text-embedding-3-small' and m.embedding_dim=256
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
