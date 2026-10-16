-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid(); other uuid:=gen_random_uuid(); s uuid; m uuid; body text:='Please sign the contract by Friday.';
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@triage-test.invalid'),
   (other,'authenticated','authenticated',other::text||'@triage-test.invalid');
 insert into public.source_items(user_id,kind,title,normalized_body,body_hash,request_id,request_hash,received_at)
 values(o,'gmail','Contract renewal',body,encode(sha256(convert_to(body,'UTF8')),'hex'),gen_random_uuid(),repeat('f',64),now())
 returning id into s;
 insert into public.source_items(user_id,kind,title,normalized_body,body_hash,request_id,request_hash,received_at)
 values(o,'manual','A manual note',body,encode(sha256(convert_to(body,'UTF8')),'hex'),gen_random_uuid(),repeat('c',64),now())
 returning id into m;
 perform set_config('focusos.triage.owner',o::text,true);
 perform set_config('focusos.triage.other',other::text,true);
 perform set_config('focusos.triage.source',s::text,true);
 perform set_config('focusos.triage.manual',m::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.triage.owner'),true);
do $$
declare s uuid:=current_setting('focusos.triage.source')::uuid; v jsonb;
begin
 v:=public.focusos_save_triage(s,'normal','Due Friday.',false);
 if v->>'priority'<>'normal' or (v->>'corrected')::boolean then raise exception 'Proposal not saved: %',v; end if;
 v:=public.focusos_save_triage(s,'urgent',null,true);
 if v->>'priority'<>'urgent' or v->>'model_priority'<>'normal' or not (v->>'corrected')::boolean then raise exception 'Correction lost the model view: %',v; end if;
 -- A later model proposal never overwrites the user's correction.
 v:=public.focusos_save_triage(s,'fyi','Looks informational.',false);
 if v->>'priority'<>'urgent' or v->>'model_priority'<>'fyi' then raise exception 'Model overwrote a correction: %',v; end if;
 begin
  perform public.focusos_save_triage(current_setting('focusos.triage.manual')::uuid,'urgent',null,true);
  raise exception 'Non-email source accepted';
 exception when sqlstate 'P0002' then null; end;
 begin
  perform public.focusos_save_triage(s,'critical',null,true);
  raise exception 'Unknown priority accepted';
 exception when sqlstate '22023' then null; end;
 begin
  insert into public.email_triage(user_id,source_id,priority) values(auth.uid(),s,'fyi');
  raise exception 'Direct write allowed';
 exception when insufficient_privilege then null; end;
end $$;
select set_config('request.jwt.claim.sub',current_setting('focusos.triage.other'),true);
do $$
begin
 if exists(select 1 from public.email_triage) then raise exception 'Another user can read triage'; end if;
 begin
  perform public.focusos_save_triage(current_setting('focusos.triage.source')::uuid,'fyi',null,true);
  raise exception 'Another user changed triage';
 exception when sqlstate 'P0002' then null; end;
end $$;
rollback;
