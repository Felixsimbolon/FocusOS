-- Synthetic rows only. All fixture changes, including the disabled guard, are rolled back.
begin;
alter table public.approval_requests disable trigger approval_proposal_guard;
do $$
declare o uuid:=gen_random_uuid(); quiet uuid:=gen_random_uuid(); c uuid; run uuid; task uuid; block jsonb; soon timestamptz:=date_trunc('minute',now()+interval '12 minutes');
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@notify-test.invalid'),
   (quiet,'authenticated','authenticated',quiet::text||'@notify-test.invalid');
 insert into public.profiles(id,timezone,working_hours) values(o,'UTC','{"days":[1,2,3,4,5,6,7],"start_minute":0,"end_minute":1440}'::jsonb)
 on conflict(id) do update set timezone=excluded.timezone;
 insert into public.connections(user_id,provider,provider_subject,granted_scopes,status)
 values(o,'google','notify-rollback-probe',array['https://www.googleapis.com/auth/gmail.send'],'connected') returning id into c;
 insert into public.tasks(user_id,title,due_kind,due_date) values(o,'Notify probe due today','date',current_date) returning id into task;
 insert into public.command_runs(user_id,request_key,command,status,stage,checkpoint,result)
 values(o,gen_random_uuid(),'Notify probe','succeeded','done','{}'::jsonb,'{}'::jsonb) returning id into run;
 block:=jsonb_build_object('title','Notify probe block','start',soon,'end',soon+interval '1 hour','timezone','UTC');
 insert into public.approval_requests(user_id,run_id,block_index,task_id,connection_id,event_id,payload,payload_hash,status)
 values(o,run,0,task,c,'fnotfprobe0',block,encode(sha256(convert_to(block::text,'UTF8')),'hex'),'succeeded');
 perform set_config('focusos.notify.owner',o::text,true);
 perform set_config('focusos.notify.quiet',quiet::text,true);
end $$;
alter table public.approval_requests enable trigger approval_proposal_guard;

-- The owner chooses reminders and a brief that is due right now (local minute in UTC).
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.notify.owner'),true);
do $$
declare minute integer:=extract(hour from now() at time zone 'UTC')*60+extract(minute from now() at time zone 'UTC');
begin
 perform public.focusos_save_notification_settings(true,minute,true,10);
 begin
  perform public.focusos_plan_notifications(now());
  raise exception 'A signed-in user could run the worker planner';
 exception when insufficient_privilege then null; end;
 begin
  perform public.focusos_claim_notifications(now(),10,null);
  raise exception 'A signed-in user could claim emails';
 exception when insufficient_privilege then null; end;
end $$;

reset role;
set local role service_role;
do $$
declare added integer; again integer; items jsonb; reminder jsonb; brief jsonb; o uuid:=current_setting('focusos.notify.owner')::uuid;
begin
 added:=public.focusos_plan_notifications(now());
 if added<>2 then raise exception 'Expected a reminder and a brief, got %',added; end if;
 again:=public.focusos_plan_notifications(now());
 if again<>0 then raise exception 'Planning twice duplicated emails'; end if;
 -- The reminder is due 10 minutes before the block (about 2 minutes from now): claim as if then.
 items:=public.focusos_claim_notifications(now()+interval '3 minutes',10,null);
 select i into reminder from jsonb_array_elements(items) i where i->>'kind'='block_reminder';
 select i into brief from jsonb_array_elements(items) i where i->>'kind'='morning_brief';
 if reminder is null or reminder->'block'->>'title'<>'Notify probe block' then raise exception 'Reminder payload wrong: %',items; end if;
 if brief->'brief'->'due_today'->>0<>'Notify probe due today' or jsonb_array_length(brief->'brief'->'blocks')<1 then raise exception 'Brief payload wrong: %',brief; end if;
 if brief->'connection'->>'email' is not null and brief->'connection'->'scopes'->>0<>'https://www.googleapis.com/auth/gmail.send' then raise exception 'Connection payload wrong'; end if;
 if jsonb_array_length(public.focusos_claim_notifications(now()+interval '3 minutes',10,null))<>0 then raise exception 'Leased emails claimed twice'; end if;
 if not public.focusos_finish_notification((reminder->>'id')::uuid,'sent',null) then raise exception 'Finish failed'; end if;
 if public.focusos_finish_notification((reminder->>'id')::uuid,'sent',null) then raise exception 'Finished twice'; end if;
 if exists(select 1 from public.email_outbox where user_id=current_setting('focusos.notify.quiet')::uuid) then raise exception 'Emails planned for a user who never opted in'; end if;
end $$;
rollback;
