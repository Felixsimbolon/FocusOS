-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid();
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@routine-reuse-test.invalid');
 perform set_config('focusos.reuse.owner',o::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.reuse.owner'),true);
do $$
declare first jsonb; same jsonb; other jsonb;
begin
 first:=public.focusos_save_routine(gen_random_uuid(),'Olahraga',array[2,4]::smallint[],420,45,null);
 -- A new request saying the same routine (any case, any weekday order) gets the saved one back.
 same:=public.focusos_save_routine(gen_random_uuid(),' olahraga ',array[4,2]::smallint[],420,45,null);
 if same->>'id'<>first->>'id' then raise exception 'Same routine saved twice'; end if;
 other:=public.focusos_save_routine(gen_random_uuid(),'Olahraga',array[2,4]::smallint[],480,45,null);
 if other->>'id'=first->>'id' then raise exception 'A different time reused the routine'; end if;
 if (select count(*) from public.routines)<>2 then raise exception 'Unexpected routine count'; end if;
 -- A paused routine is not reused: saying it again starts a new one.
 perform public.focusos_set_routine_active((first->>'id')::uuid,false);
 same:=public.focusos_save_routine(gen_random_uuid(),'Olahraga',array[2,4]::smallint[],420,45,null);
 if same->>'id'=first->>'id' then raise exception 'A paused routine was reused'; end if;
end $$;
reset role;
do $$
begin
 -- Later schedule parts run on child runs; both guards must accept their entrypoint.
 if position('unified_schedule' in pg_get_functiondef('public.focusos_propose_calendar_action(uuid,integer)'::regprocedure))=0
  or position('unified_schedule' in pg_get_functiondef('public.focusos_guard_approval_proposal()'::regprocedure))=0
 then raise exception 'Child schedule runs are still refused'; end if;
end $$;
rollback;
