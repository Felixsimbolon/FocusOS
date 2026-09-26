-- Phase 4.7: persistent reversible ignore decisions for review cards.
alter table public.extraction_results
  add column ignored_item_keys text[] not null default '{}';
grant select (ignored_item_keys) on public.extraction_results to authenticated;

create function public.focusos_set_extraction_ignored(
 p_extraction_id uuid,p_local_ref text,p_ignored boolean
) returns boolean language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_result public.extraction_results;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 select * into v_result from public.extraction_results
   where id=p_extraction_id and user_id=v_owner and status='ready' for update;
 if v_result.id is null then return false; end if;
 if not exists(select 1 from pg_catalog.jsonb_array_elements(v_result.validated_payload->'tasks') c
               where c->>'local_ref'=p_local_ref) then return false; end if;
 if p_ignored then
   update public.extraction_results
    set ignored_item_keys = case when p_local_ref=any(ignored_item_keys)
        then ignored_item_keys else pg_catalog.array_append(ignored_item_keys,p_local_ref) end,
        reviewed_at=coalesce(reviewed_at,now()),updated_at=now()
    where id=p_extraction_id;
 else
   update public.extraction_results
    set ignored_item_keys=pg_catalog.array_remove(ignored_item_keys,p_local_ref),updated_at=now()
    where id=p_extraction_id;
 end if;
 return true;
end;
$$;
revoke all on function public.focusos_set_extraction_ignored(uuid,text,boolean) from public,anon;
grant execute on function public.focusos_set_extraction_ignored(uuid,text,boolean) to authenticated;
