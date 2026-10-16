-- Synthetic rows only. All fixture changes, including the disabled guard, are rolled back.
begin;
-- The proposal guard only admits future blocks; check-ins need blocks that already ran.
alter table public.approval_requests disable trigger approval_proposal_guard;
do $$
declare o uuid:=gen_random_uuid(); v_task uuid; v_project uuid; v_connection uuid; v_run uuid; v_past uuid; v_future uuid;
 v_start timestamptz:=date_trunc('minute',now()-interval '3 hours');
 action jsonb; later jsonb;
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@sessions-test.invalid');
 insert into public.connections(user_id,provider,provider_subject,granted_scopes,status)
 values(o,'google','sessions-rollback-probe',array['https://www.googleapis.com/auth/calendar.events.owned'],'connected')
 returning id into v_connection;
 insert into public.projects(user_id,name) values(o,'Sessions probe') returning id into v_project;
 insert into public.tasks(user_id,title,project_id) values(o,'Sessions probe task',v_project) returning id into v_task;
 insert into public.command_runs(user_id,request_key,command,status,stage,checkpoint,result)
 values(o,gen_random_uuid(),'Synthetic check-in probe','succeeded','done','{}'::jsonb,'{}'::jsonb) returning id into v_run;
 action:=jsonb_build_object('title','Sessions probe task','start',v_start,'end',v_start+interval '60 minutes','timezone','UTC');
 later:=jsonb_build_object('title','Later','start',now()+interval '2 hours','end',now()+interval '3 hours','timezone','UTC');
 insert into public.approval_requests(user_id,run_id,block_index,task_id,connection_id,event_id,payload,payload_hash,status)
 values(o,v_run,0,v_task,v_connection,'fsessionsprobe0',action,encode(sha256(convert_to(action::text,'UTF8')),'hex'),'succeeded') returning id into v_past;
 insert into public.approval_requests(user_id,run_id,block_index,task_id,connection_id,event_id,payload,payload_hash,status)
 values(o,v_run,1,v_task,v_connection,'fsessionsprobe1',later,encode(sha256(convert_to(later::text,'UTF8')),'hex'),'succeeded')
 returning id into v_future;
 perform set_config('focusos.sessions.owner',o::text,true);
 perform set_config('focusos.sessions.past',v_past::text,true);
 perform set_config('focusos.sessions.future',v_future::text,true);
 perform set_config('focusos.sessions.project',v_project::text,true);
end $$;
alter table public.approval_requests enable trigger approval_proposal_guard;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.sessions.owner'),true);
do $$
declare past uuid:=current_setting('focusos.sessions.past')::uuid; future uuid:=current_setting('focusos.sessions.future')::uuid;
 v jsonb; v_count integer; v_row record;
begin
 v:=public.focusos_record_work_session(past,'done',90);
 if (v->>'planned_minutes')::integer<>60 or (v->>'actual_minutes')::integer<>90 then raise exception 'Wrong session: %',v; end if;
 select * into v_row from public.work_sessions where approval_id=past;
 if v_row.project_id::text<>current_setting('focusos.sessions.project') then raise exception 'Project not recorded'; end if;
 -- A second check-in corrects the first instead of adding a row.
 perform public.focusos_record_work_session(past,'partial',75);
 select count(*) into v_count from public.work_sessions where approval_id=past;
 if v_count<>1 then raise exception 'Correction duplicated the session'; end if;
 if (select outcome from public.work_sessions where approval_id=past)<>'partial' then raise exception 'Correction ignored'; end if;
 perform public.focusos_record_work_session(past,'skipped',null);
 begin
  perform public.focusos_record_work_session(future,'done',30);
  raise exception 'Check-in before the block started was accepted';
 exception when sqlstate '22023' then null; end;
 begin
  perform public.focusos_record_work_session(past,'skipped',20);
  raise exception 'Skipped check-in with minutes was accepted';
 exception when sqlstate '22023' then null; end;
 begin
  perform public.focusos_record_work_session(past,'done',0);
  raise exception 'Zero minutes accepted';
 exception when sqlstate '22023' then null; end;
 begin
  insert into public.work_sessions(user_id,approval_id,planned_minutes,actual_minutes,outcome)
  values(auth.uid(),past,60,60,'done');
  raise exception 'Direct insert allowed';
 exception when insufficient_privilege then null; end;
end $$;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000002',true);
do $$
begin
 if exists(select 1 from public.work_sessions where approval_id=current_setting('focusos.sessions.past')::uuid) then
   raise exception 'Another user can read sessions'; end if;
 begin
  perform public.focusos_record_work_session(current_setting('focusos.sessions.past')::uuid,'done',30);
  raise exception 'Another user checked in';
 exception when sqlstate 'P0002' then null; end;
end $$;
rollback;
