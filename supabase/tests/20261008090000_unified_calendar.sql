begin;
do $$
declare o uuid:=gen_random_uuid(); c uuid; r uuid; bad uuid; offslot uuid; s text; e text; cp jsonb; proposal jsonb;
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated','unified-calendar-test@example.test');
 insert into public.profiles(id,timezone,working_hours) values(o,'UTC','{"days":[1,2,3,4,5,6,7],"start_minute":0,"end_minute":1440}')
 on conflict(id) do update set timezone=excluded.timezone,working_hours=excluded.working_hours;
 insert into public.connections(user_id,provider,provider_subject,granted_scopes,status)
 values(o,'google','unified-test',array['https://www.googleapis.com/auth/calendar.events.owned','https://www.googleapis.com/auth/calendar.events.owned.readonly'],'connected') returning id into c;
 s:=to_char(date_trunc('minute',now()+interval '2 hours') at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS"+00:00"');
 e:=to_char(date_trunc('minute',now()+interval '2 hours 45 minutes') at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS"+00:00"');
 cp:=jsonb_build_object('entrypoint','unified','auto_calendar',true,'standalone_title','Study Python','free_time',jsonb_build_object('slots',jsonb_build_array(jsonb_build_object('start',s,'end',e))));
 proposal:=jsonb_build_object('status','proposed','actionable',false,'blocks',jsonb_build_array(jsonb_build_object('task_id',null,'title','Study Python','start',s,'end',e)));
 insert into public.command_runs(user_id,request_key,command,status,stage,checkpoint,result)
 values(o,gen_random_uuid(),'Schedule Study Python for 45 minutes','succeeded','done',cp,proposal) returning id into r;
 insert into public.command_runs(user_id,request_key,command,status,stage,checkpoint,result)
 values(o,gen_random_uuid(),'Schedule something else','succeeded','done',cp,proposal) returning id into bad;
 insert into public.command_runs(user_id,request_key,command,status,stage,checkpoint,result)
 values(o,gen_random_uuid(),'Schedule Study Python','succeeded','done',jsonb_set(cp,'{free_time,slots}','[]'),proposal) returning id into offslot;
 perform set_config('focusos.test.owner',o::text,true);
 perform set_config('focusos.test.run',r::text,true);
 perform set_config('focusos.test.bad',bad::text,true);
 perform set_config('focusos.test.offslot',offslot::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.test.owner'),true);
do $$
declare a jsonb; n integer;
begin
 a:=public.focusos_propose_calendar_action(current_setting('focusos.test.run')::uuid,0);
 if a->>'task_id' is not null or a->'payload'->>'task_version' is not null or a->'payload'->>'source_id' is not null then raise exception 'Standalone event has task metadata'; end if;
 if a->'payload'->>'title'<>'Study Python' then raise exception 'Activity title changed'; end if;
 if public.focusos_propose_calendar_action(current_setting('focusos.test.run')::uuid,0)->>'id'<>a->>'id' then raise exception 'Duplicate action on replay'; end if;
 a:=public.focusos_authorize_automatic_calendar_action(current_setting('focusos.test.run')::uuid,0);
 if a->>'status'<>'approved' or a->>'authorization_mode'<>'automatic' then raise exception 'Automatic authorization unavailable'; end if;
 select count(*) into n from public.tasks where user_id=current_setting('focusos.test.owner')::uuid;
 if n<>0 then raise exception 'Standalone schedule created a task'; end if;
 begin
  perform public.focusos_propose_calendar_action(current_setting('focusos.test.bad')::uuid,0);
  raise exception 'Invented activity accepted';
 exception when sqlstate '22023' then null; end;
 begin
  perform public.focusos_propose_calendar_action(current_setting('focusos.test.offslot')::uuid,0);
  raise exception 'Unsaved slot accepted';
 exception when sqlstate '22023' then null; end;
end $$;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
do $$
declare n integer;
begin
 select count(*) into n from public.approval_requests where run_id=current_setting('focusos.test.run')::uuid;
 if n<>0 then raise exception 'Foreign standalone event visible'; end if;
 begin
  perform public.focusos_propose_calendar_action(current_setting('focusos.test.run')::uuid,0);
  raise exception 'Foreign standalone event replay allowed';
 exception when sqlstate '22023' then null; end;
end $$;
reset role;
do $$
declare o uuid:=current_setting('focusos.test.owner')::uuid; t uuid; r public.command_runs; saved uuid; expired uuid;
begin
 select * into r from public.command_runs where id=current_setting('focusos.test.run')::uuid;
 insert into public.tasks(user_id,title,due_kind,due_date) values(o,'Date deadline work','date',current_date+1) returning id into t;
 insert into public.command_runs(user_id,request_key,command,status,stage,checkpoint,result)
 values(o,gen_random_uuid(),'Schedule date deadline work','succeeded','done',r.checkpoint,
 jsonb_set(jsonb_set(r.result,'{blocks,0,task_id}',to_jsonb(t)),'{blocks,0,title}','"Date deadline work"')) returning id into saved;
 insert into public.tasks(user_id,title,due_kind,due_date) values(o,'Overdue date work','date',current_date-1) returning id into t;
 insert into public.command_runs(user_id,request_key,command,status,stage,checkpoint,result)
 values(o,gen_random_uuid(),'Schedule overdue date work','succeeded','done',r.checkpoint,
 jsonb_set(jsonb_set(r.result,'{blocks,0,task_id}',to_jsonb(t)),'{blocks,0,title}','"Overdue date work"')) returning id into expired;
 perform set_config('focusos.test.dated',saved::text,true);
 perform set_config('focusos.test.expired',expired::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.test.owner'),true);
do $$
declare a jsonb;
begin
 a:=public.focusos_propose_calendar_action(current_setting('focusos.test.dated')::uuid,0);
 if a->>'task_id' is null then raise exception 'Date task lost association'; end if;
 begin
  perform public.focusos_propose_calendar_action(current_setting('focusos.test.expired')::uuid,0);
  raise exception 'Overdue date task scheduled';
 exception when sqlstate '22023' then null; end;
end $$;
rollback;
