begin;
do $$
declare v_owner uuid; v_task uuid; v_connection uuid; v_run uuid; v_start timestamptz:=date_trunc('minute',now()+interval '2 hours'); v_end timestamptz; v_s text; v_e text;
begin
 v_owner:=gen_random_uuid();
 insert into auth.users(id,aud,role,email) values(v_owner,'authenticated','authenticated','focusos-calendar-probe@example.test');
 v_end:=v_start+interval '1 hour'; v_s:=to_char(v_start at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS"+00:00"'); v_e:=to_char(v_end at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS"+00:00"');
 insert into public.profiles(id,timezone,working_hours) values(v_owner,'UTC','{"days":[1,2,3,4,5,6,7],"start_minute":0,"end_minute":1440}'::jsonb)
 on conflict(id) do update set timezone=excluded.timezone,working_hours=excluded.working_hours;
 insert into public.connections(user_id,provider,provider_subject,granted_scopes,status)
 values(v_owner,'google','phase8-rollback-probe',array['https://www.googleapis.com/auth/calendar.events.owned','https://www.googleapis.com/auth/calendar.events.owned.readonly'],'connected')
 on conflict(user_id,provider) do update set granted_scopes=excluded.granted_scopes,status='connected'
 returning id into v_connection;
 insert into public.tasks(user_id,title) values(v_owner,'Phase 8 rollback focus block') returning id into v_task;
 insert into public.command_runs(user_id,request_key,command,status,stage,checkpoint,result)
 values(v_owner,gen_random_uuid(),'Plan a synthetic focus block','succeeded','done',
 jsonb_build_object('free_time',jsonb_build_object('slots',jsonb_build_array(jsonb_build_object('start',v_s,'end',v_e)))),
 jsonb_build_object('status','proposed','actionable',false,'blocks',jsonb_build_array(jsonb_build_object('task_id',v_task,'title','Phase 8 rollback focus block','start',v_s,'end',v_e,'slot_ref','slot-1')))) returning id into v_run;
 perform set_config('focusos.test.owner_id',v_owner::text,true);
 perform set_config('focusos.test.run_id',v_run::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.test.owner_id'),true);
do $$
declare v_row jsonb; v_count integer;
begin
 v_row:=public.focusos_propose_calendar_action(current_setting('focusos.test.run_id')::uuid,0);
 if v_row->>'status'<>'pending' or v_row->>'event_id' !~ '^[a-f0-9]+$' then raise exception 'Proposal failed'; end if;
 if (public.focusos_propose_calendar_action(current_setting('focusos.test.run_id')::uuid,0)->>'id')<>v_row->>'id' then raise exception 'Replay created a second approval'; end if;
 select count(*) into v_count from public.approval_requests where run_id=current_setting('focusos.test.run_id')::uuid;
 if v_count<>1 then raise exception 'Owner cannot read approval'; end if;
 perform set_config('focusos.test.approval_id',v_row->>'id',true);
 v_row:=public.focusos_decide_approval((v_row->>'id')::uuid,'approve');
 if v_row->>'status'<>'approved' then raise exception 'Approve failed'; end if;
 if (public.focusos_decide_approval((v_row->>'id')::uuid,'approve')->>'id')<>v_row->>'id' then raise exception 'Decision replay changed row'; end if;
 begin
  perform public.focusos_decide_approval((v_row->>'id')::uuid,'reject');
  raise exception 'Opposite decision was accepted';
 exception when sqlstate '22023' then null; end;
end $$;
reset role;
set local role service_role;
select set_config('request.jwt.claim.role','service_role',true);
do $$
declare v_claim jsonb; v_second jsonb; v_id text;
begin
 v_claim:=public.focusos_claim_approval_execution(current_setting('focusos.test.owner_id')::uuid,current_setting('focusos.test.approval_id')::uuid);
 if v_claim->>'claimed'<>'true' or v_claim->'approval'->>'status'<>'executing' then raise exception 'Claim failed'; end if;
 v_second:=public.focusos_claim_approval_execution(current_setting('focusos.test.owner_id')::uuid,current_setting('focusos.test.approval_id')::uuid);
 if v_second->>'claimed'<>'false' then raise exception 'Second request claimed same action'; end if;
 v_id:=v_claim->'approval'->>'event_id';
 if not public.focusos_finish_approval_execution(current_setting('focusos.test.owner_id')::uuid,current_setting('focusos.test.approval_id')::uuid,
  (v_claim->'approval'->>'status_version')::integer,'succeeded',v_id,'https://www.google.com/calendar/event?eid=test',null)
 then raise exception 'Finish failed'; end if;
 if (public.focusos_claim_approval_execution(current_setting('focusos.test.owner_id')::uuid,current_setting('focusos.test.approval_id')::uuid)->'approval'->>'status')<>'succeeded'
 then raise exception 'Succeeded action changed'; end if;
end $$;
set local role authenticated;
select set_config('request.jwt.claim.role','authenticated',true);
select set_config('request.jwt.claim.sub',current_setting('focusos.test.owner_id'),true);
do $$
declare c jsonb; id uuid:=current_setting('focusos.test.approval_id')::uuid;
begin
 c:=public.focusos_claim_calendar_cancellation(id);
 if c->>'claimed'<>'true' then raise exception 'Cancellation claim failed';end if;
 if public.focusos_claim_calendar_cancellation(id)->>'claimed'<>'false' then raise exception 'Double cancellation claim';end if;
 if public.focusos_finish_calendar_cancellation(id,gen_random_uuid(),'cancelled',null) then raise exception 'Wrong cancellation lease accepted';end if;
 if not public.focusos_finish_calendar_cancellation(id,(c->>'lease')::uuid,'cancelled',null) then raise exception 'Cancellation finish failed';end if;
 if public.focusos_claim_calendar_cancellation(id)->>'status'<>'cancelled' then raise exception 'Cancellation replay changed result';end if;
end $$;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
do $$
declare v_count integer;
begin
 select count(*) into v_count from public.approval_requests where run_id=current_setting('focusos.test.run_id')::uuid;
 if v_count<>0 then raise exception 'Foreign approval visible'; end if;
 if public.focusos_claim_calendar_cancellation(current_setting('focusos.test.approval_id')::uuid) is not null then raise exception 'Foreign cancellation allowed';end if;
end $$;
rollback;
