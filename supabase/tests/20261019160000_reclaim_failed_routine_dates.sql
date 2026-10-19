-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid();
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@routine-reclaim-test.invalid');
 perform set_config('focusos.reclaim.owner',o::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.reclaim.owner'),true);
do $$
declare r jsonb; id uuid; first_run uuid:=gen_random_uuid(); second_run uuid:=gen_random_uuid(); d1 date:=current_date+1; d2 date:=current_date+3;
begin
 r:=public.focusos_save_routine(gen_random_uuid(),'Olahraga',array[2,4]::smallint[],420,45,null); id:=(r->>'id')::uuid;
 if public.focusos_claim_routine_dates(id,array[d1,d2],first_run)<>array[d1,d2] then raise exception 'First claim wrong'; end if;
 perform public.focusos_finish_routine_date(id,d1,first_run,'booked');
 perform public.focusos_finish_routine_date(id,d2,first_run,'failed');
 -- The failed date is free again; the booked one is not.
 if public.focusos_claim_routine_dates(id,array[d1,d2],second_run)<>array[d2] then raise exception 'Failed date not reclaimed'; end if;
 if public.focusos_claim_routine_dates(id,array[d1,d2],first_run)<>array[d1] then raise exception 'Old run kept a reclaimed date'; end if;
end $$;
rollback;
