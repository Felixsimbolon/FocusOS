-- Phase 5.5: find one owned eligible Gmail source for the existing extraction claim.
create function public.focusos_next_gmail_source(
 p_schema text,p_prompt text,p_model text
) returns uuid language sql stable security definer set search_path=''
as $$
 select s.id from public.source_items s
 where s.user_id=(select auth.uid()) and s.kind='gmail' and s.deleted_at is null
   and s.normalized_body is not null and s.body_expires_at>now()
   and not exists(
     select 1 from public.extraction_results r
     where r.user_id=s.user_id and r.source_id=s.id and r.content_hash=s.body_hash
       and r.schema_version=p_schema and r.prompt_version=p_prompt and r.model_version=p_model
       and (r.status='ready' or (r.status='processing' and r.lease_expires_at>now()))
   )
 order by s.created_at,s.id limit 1;
$$;
revoke all on function public.focusos_next_gmail_source(text,text,text) from public,anon;
grant execute on function public.focusos_next_gmail_source(text,text,text) to authenticated;
