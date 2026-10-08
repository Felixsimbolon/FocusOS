-- Recover parsed Gmail whose task/memory persistence or indexing did not finish.
-- Keep the older three-argument handoff available during the API rollout.
create function public.focusos_next_gmail_capture(
 p_schema text,p_prompt text,p_model text,p_excluded uuid[]
) returns uuid language plpgsql stable security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_id uuid;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if coalesce(cardinality(p_excluded),0)>64 then raise exception 'Too many excluded sources' using errcode='22023'; end if;
 select s.id into v_id
 from public.source_items s
 left join public.extraction_results r
   on r.user_id=s.user_id and r.source_id=s.id and r.content_hash=s.body_hash
   and r.schema_version=p_schema and r.prompt_version=p_prompt and r.model_version=p_model
 where s.user_id=v_owner and s.kind='gmail' and s.deleted_at is null
   and s.normalized_body is not null and s.body_expires_at>now()
   and not (s.id=any(coalesce(p_excluded,'{}'::uuid[])))
   and not (coalesce(r.status='processing' and r.lease_expires_at>now(),false))
   and (
     r.id is null or r.status<>'ready'
     or exists (
       select 1 from pg_catalog.jsonb_array_elements(coalesce(r.validated_payload->'tasks','[]'::jsonb)) c
       where not (c->>'local_ref'=any(r.ignored_item_keys))
       and not exists (
         select 1 from public.tasks t where t.user_id=v_owner
         and t.extraction_result_id=r.id and t.extraction_item_key=c->>'local_ref'
       )
     )
     or exists (
       select 1 from (
         select left(regexp_replace('Task: '||(c->>'title')||'. '||coalesce(c->>'description',''),
                    '^[[:space:]]+|[[:space:]]+$','','g'),500) as text,
                regexp_replace(c->'evidence'->0->>'quote','^[[:space:]]+|[[:space:]]+$','','g') as quote
         from pg_catalog.jsonb_array_elements(coalesce(r.validated_payload->'tasks','[]'::jsonb)) c
         where not (c->>'local_ref'=any(r.ignored_item_keys))
         union all
         select regexp_replace(c->>'text','^[[:space:]]+|[[:space:]]+$','','g'),regexp_replace(c->'evidence'->0->>'quote','^[[:space:]]+|[[:space:]]+$','','g')
         from pg_catalog.jsonb_array_elements(coalesce(r.validated_payload->'facts','[]'::jsonb)) c
       ) expected
       where not exists (
         -- Superseded evidence still counts as previously captured; never restore it.
         select 1 from public.memories m where m.user_id=v_owner and m.source_id=s.id
         and m.source_hash=s.body_hash and m.text=expected.text and m.evidence_quote=expected.quote
       ) or exists (
         select 1 from public.memories m where m.user_id=v_owner and m.source_id=s.id
         and m.source_hash=s.body_hash and m.text=expected.text and m.evidence_quote=expected.quote
         and m.status='active' and m.embedding_status<>'ready'
       )
     )
   )
 -- Restore persisted extraction first; it needs no new LLM extraction request.
 order by case when r.status='ready' then 0 else 1 end,s.created_at,s.id limit 1;
 return v_id;
end; $$;
revoke all on function public.focusos_next_gmail_capture(text,text,text,uuid[]) from public,anon;
grant execute on function public.focusos_next_gmail_capture(text,text,text,uuid[]) to authenticated;
