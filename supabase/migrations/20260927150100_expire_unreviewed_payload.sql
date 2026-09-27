-- Phase 9.5: bounded lazy expiry removes raw source text and unreviewed extraction payload.
-- Confirmed tasks/memories remain until the user explicitly deletes their source.
create or replace function public.focusos_expire_source_bodies(p_limit integer default 100)
returns integer language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_count integer;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_limit < 1 or p_limit > 100 then raise exception 'Invalid limit' using errcode='22023'; end if;
 with expired as (
  select s.id from public.source_items s
  where s.user_id=v_owner and s.body_expires_at<=now() and
   (s.normalized_body is not null or exists(select 1 from public.extraction_results r
      where r.source_id=s.id and r.user_id=v_owner and (r.validated_payload is not null or r.status='processing')))
  order by s.body_expires_at,s.id limit p_limit for update of s skip locked
 ), cleared as (
  update public.extraction_results r set validated_payload=null,status='failed',
   safe_error='source_expired',claim_token=null,lease_expires_at=null,updated_at=now()
  where r.user_id=v_owner and r.source_id in (select id from expired)
   and (r.validated_payload is not null or r.status='processing') returning r.id
 )
 update public.source_items s set normalized_body=null
 where s.user_id=v_owner and s.id in (select id from expired);
 get diagnostics v_count = row_count;
 return v_count;
end; $$;
