-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid();
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@routine-test.invalid');
 insert into public.command_runs(user_id,request_key,command,status,stage,checkpoint,result)
 values(o,gen_random_uuid(),'Book routines probe','pending','start','{}'::jsonb,null);
 perform set_config('focusos.routine.owner',o::text,true);
 perform set_config('focusos.routine.run',(select id::text from public.command_runs where user_id=o),true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.routine.owner'),true);
do $$
declare key uuid:=gen_random_uuid(); r jsonb; again jsonb; claimed date[]; run uuid:=current_setting('focusos.routine.run')::uuid; other_run uuid:=gen_random_uuid();
 d1 date:=current_date+1; d2 date:=current_date+3;
begin
 r:=public.focusos_save_routine(key,'Belajar Python',array[2,4,2]::smallint[],420,60,null);
 if r->'weekdays'<>'[2, 4]'::jsonb then raise exception 'Weekdays not normalized: %',r; end if;
 again:=public.focusos_save_routine(key,'Something else',array[1]::smallint[],60,30,null);
 if again->>'id'<>r->>'id' then raise exception 'Replay created a second routine'; end if;
 claimed:=public.focusos_claim_routine_dates((r->>'id')::uuid,array[d1,d2],run);
 if claimed<>array[d1,d2] then raise exception 'First claim wrong: %',claimed; end if;
 -- A retry of the same request keeps its dates; another request gets none of them.
 if public.focusos_claim_routine_dates((r->>'id')::uuid,array[d1,d2],run)<>array[d1,d2] then raise exception 'Retry lost its dates'; end if;
 if cardinality(public.focusos_claim_routine_dates((r->>'id')::uuid,array[d1,d2],other_run))<>0 then raise exception 'Date booked twice'; end if;
 if not public.focusos_finish_routine_date((r->>'id')::uuid,d1,run,'booked') then raise exception 'Finish failed'; end if;
 if public.focusos_finish_routine_date((r->>'id')::uuid,d2,other_run,'booked') then raise exception 'Another request finished a date it does not own'; end if;
 if not public.focusos_set_routine_active((r->>'id')::uuid,false) then raise exception 'Pause failed'; end if;
 begin
  perform public.focusos_claim_routine_dates((r->>'id')::uuid,array[current_date+5],gen_random_uuid());
  raise exception 'Paused routine booked';
 exception when sqlstate 'P0002' then null; end;
 begin
  perform public.focusos_save_routine(gen_random_uuid(),'Late',array[1]::smallint[],1430,60,null);
  raise exception 'Routine past midnight accepted';
 exception when check_violation then null; end;
 begin
  perform public.focusos_save_routine(gen_random_uuid(),'Bad "quote"',array[1]::smallint[],60,30,null);
  raise exception 'Quote in title accepted';
 exception when check_violation then null; end;
 begin
  insert into public.routines(user_id,request_key,title,weekdays,start_minute,duration_minutes) values(auth.uid(),gen_random_uuid(),'x','{1}',60,30);
  raise exception 'Direct write allowed';
 exception when insufficient_privilege then null; end;
end $$;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000005',true);
do $$
begin
 if exists(select 1 from public.routines) or exists(select 1 from public.routine_occurrences) then raise exception 'Another user can read routines'; end if;
end $$;
rollback;
