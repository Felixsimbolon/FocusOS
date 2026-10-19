-- Routine dates whose booking failed could never be booked again, even by a new request.
create or replace function public.focusos_claim_routine_dates(p_routine_id uuid,p_dates date[],p_run_id uuid)
returns date[] language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_claimed date[];
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if cardinality(p_dates)>7 or exists(select 1 from pg_catalog.unnest(p_dates) d where d<current_date-1 or d>current_date+8)
 then raise exception 'Invalid routine dates' using errcode='22023'; end if;
 if not exists(select 1 from public.routines r where r.id=p_routine_id and r.user_id=v_owner and r.active)
 then raise exception 'Routine not found' using errcode='P0002'; end if;
 insert into public.routine_occurrences(user_id,routine_id,occurs_on,run_id)
 select v_owner,p_routine_id,d,p_run_id from pg_catalog.unnest(p_dates) d
 on conflict(routine_id,occurs_on) do update set run_id=excluded.run_id,status='booking',updated_at=now()
  -- A date whose booking failed is free again for a later request; booked dates stay with their run.
  where public.routine_occurrences.status='failed' and public.routine_occurrences.run_id is distinct from excluded.run_id;
 -- A retried request may claim again: dates it already owns count as its own.
 select coalesce(array_agg(o.occurs_on order by o.occurs_on),'{}') into v_claimed from public.routine_occurrences o
 where o.routine_id=p_routine_id and o.user_id=v_owner and o.run_id=p_run_id and o.occurs_on=any(p_dates);
 return v_claimed;
end; $$;
