-- Synthetic rows only. All fixture and function changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid(); c uuid; s uuid; raw uuid; r uuid;
 body text:=E'Synthetic source\nTolong siapkan checklist demo FocusOS selama 30 menit.\n\tKode demo FocusOS ini adalah Nusa.\nSynthetic end.';
 task_quote text:='Tolong siapkan checklist demo FocusOS selama 30 menit.';
 fact text:='Kode demo FocusOS ini adalah Nusa.';
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@capture-test.invalid');
 insert into public.connections(user_id,provider,provider_subject,granted_scopes,status)
 values(o,'google','capture-test',array['https://www.googleapis.com/auth/gmail.readonly'],'connected') returning id into c;
 insert into public.source_items(user_id,kind,title,normalized_body,body_hash,request_id,request_hash,received_at,
   connection_id,provider_message_id,thread_id,selected_label_id,created_at)
 values(o,'gmail','Old unparsed',body,repeat('a',64),gen_random_uuid(),repeat('a',64),now(),c,'old','old','FocusOS',now()-interval '1 hour') returning id into raw;
 insert into public.source_items(user_id,kind,title,normalized_body,body_hash,request_id,request_hash,received_at,
   connection_id,provider_message_id,thread_id,selected_label_id)
 values(o,'gmail','Parsed Nusa',body,repeat('b',64),gen_random_uuid(),repeat('b',64),now(),c,'nusa','nusa','FocusOS') returning id into s;
 insert into public.extraction_results(user_id,source_id,content_hash,schema_version,prompt_version,model_version,status,validated_payload)
 values(o,s,repeat('b',64),'1','2','synthetic-model','ready',jsonb_build_object(
   'tasks',jsonb_build_array(jsonb_build_object('local_ref','checklist','title','Siapkan checklist demo FocusOS','description',E'\n',
      'evidence',jsonb_build_array(jsonb_build_object('quote',E'\n'||task_quote||E'\n')))),
   'facts',jsonb_build_array(jsonb_build_object('kind','fact','text',E'\t'||fact||E'\n','evidence',jsonb_build_array(jsonb_build_object('quote',E'\t'||fact||E'\n'))))
 )) returning id into r;
 perform set_config('focusos.capture.owner',o::text,true);
 perform set_config('focusos.capture.source',s::text,true);
 perform set_config('focusos.capture.raw',raw::text,true);
 perform set_config('focusos.capture.result',r::text,true);
 perform set_config('focusos.capture.task_memory_key',gen_random_uuid()::text,true);
 perform set_config('focusos.capture.fact_memory_key',gen_random_uuid()::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.capture.owner'),true);
do $$
declare s uuid:=current_setting('focusos.capture.source')::uuid; raw uuid:=current_setting('focusos.capture.raw')::uuid;
 r uuid:=current_setting('focusos.capture.result')::uuid; response jsonb; replay jsonb;
begin
 if public.focusos_next_gmail_capture('1','2','synthetic-model','{}') is distinct from s then raise exception 'Parsed recovery did not take priority'; end if;
 if public.focusos_next_gmail_capture('1','2','synthetic-model',array[s]) is distinct from raw then raise exception 'Excluded source blocks next email'; end if;
 begin
  perform public.focusos_next_gmail_capture('1','2','synthetic-model',array_fill(s,array[65]));
  raise exception 'Unbounded exclusion accepted';
 exception when sqlstate '22023' then null; end;
 response:=public.focusos_confirm_extraction_task(r,'checklist',repeat('c',64),'Siapkan checklist demo FocusOS',null,'normal','none',null,null,null,30,null,'[]',0.95);
 replay:=public.focusos_confirm_extraction_task(r,'checklist',repeat('c',64),'Siapkan checklist demo FocusOS',null,'normal','none',null,null,null,30,null,'[]',0.95);
 if response->'task'->>'id' is distinct from replay->'task'->>'id' or replay->>'replayed'<>'true' then raise exception 'Task replay duplicated'; end if;
 if response->'task' ? 'review_hash' or response->'task' ? 'user_id' then raise exception 'Private task fields leaked'; end if;
 if public.focusos_next_gmail_capture('1','2','synthetic-model',array[raw]) is distinct from s then raise exception 'Task-only capture was mistaken for complete'; end if;
 response:=public.focusos_confirm_memory(current_setting('focusos.capture.task_memory_key')::uuid,s,null,
  'Task: Siapkan checklist demo FocusOS.','Tolong siapkan checklist demo FocusOS selama 30 menit.');
 if public.focusos_next_gmail_capture('1','2','synthetic-model',array[raw]) is distinct from s then raise exception 'Missing fact was skipped'; end if;
 response:=public.focusos_confirm_memory(current_setting('focusos.capture.fact_memory_key')::uuid,s,null,
  'Kode demo FocusOS ini adalah Nusa.','Kode demo FocusOS ini adalah Nusa.');
 replay:=public.focusos_confirm_memory(current_setting('focusos.capture.fact_memory_key')::uuid,s,null,
  'Kode demo FocusOS ini adalah Nusa.','Kode demo FocusOS ini adalah Nusa.');
 if response->>'id' is distinct from replay->>'id' then raise exception 'Memory replay duplicated'; end if;
 if public.focusos_next_gmail_capture('1','2','synthetic-model',array[raw]) is distinct from s then raise exception 'Pending indexing was skipped'; end if;
 response:=public.focusos_search_memories('Nusa',null,null,5);
 if jsonb_array_length(response)<>1 or response->0->>'text'<>'Kode demo FocusOS ini adalah Nusa.' then raise exception 'Unindexed Nusa fact not available by keyword'; end if;
 if (select count(*) from public.tasks where extraction_result_id=r)<>1 or (select count(*) from public.memories where source_id=s)<>2 then raise exception 'Replay row count wrong'; end if;
end $$;
reset role;
do $$
declare s uuid:=current_setting('focusos.capture.source')::uuid; vec text;
begin
 vec:='['||'1,'||array_to_string(array_fill(0,array[255]),',')||']';
 update public.memories set embedding_status='ready',embedding=vec::extensions.vector(256),
   embedding_model='gemini-embedding-2',embedding_dim=256,embedding_hash=repeat('d',64) where source_id=s;
 if has_function_privilege('anon','public.focusos_next_gmail_capture(text,text,text,uuid[])','EXECUTE') then raise exception 'Anonymous capture access'; end if;
end $$;
set local role authenticated;
do $$
declare s uuid:=current_setting('focusos.capture.source')::uuid; raw uuid:=current_setting('focusos.capture.raw')::uuid;
 matches jsonb; vec text;
begin
 if public.focusos_next_gmail_capture('1','2','synthetic-model',array[raw]) is not null then raise exception 'Complete source reselected'; end if;
 vec:='['||'1,'||array_to_string(array_fill(0,array[255]),',')||']';
 matches:=public.focusos_search_memories('Apa kode demo FocusOS ini?',vec,null,5);
 if not exists(select 1 from jsonb_array_elements(matches) m where m->>'text'='Kode demo FocusOS ini adalah Nusa.') then raise exception 'Indexed Nusa fact missing from semantic retrieval'; end if;
 perform public.focusos_supersede_memory((select id from public.memories where source_id=s and text='Kode demo FocusOS ini adalah Nusa.'));
 if public.focusos_next_gmail_capture('1','2','synthetic-model',array[raw]) is not null then raise exception 'Superseded fact would be restored'; end if;
 perform set_config('request.jwt.claim.sub',gen_random_uuid()::text,true);
 if public.focusos_next_gmail_capture('1','2','synthetic-model','{}') is not null then raise exception 'Foreign owner source leak'; end if;
 if public.focusos_search_memories('Nusa',vec,null,5)<>'[]'::jsonb then raise exception 'Foreign owner memory leak'; end if;
 perform set_config('request.jwt.claim.sub',current_setting('focusos.capture.owner'),true);
end $$;
reset role;
-- Ignored task and superseded fact remain intentionally absent from active data.
delete from public.tasks where extraction_result_id=current_setting('focusos.capture.result')::uuid;
update public.extraction_results set ignored_item_keys=array['checklist'] where id=current_setting('focusos.capture.result')::uuid;
set local role authenticated;
do $$
begin
 if public.focusos_next_gmail_capture('1','2','synthetic-model',array[current_setting('focusos.capture.raw')::uuid]) is not null then raise exception 'Ignored task would be recreated'; end if;
end $$;
reset role;
update public.extraction_results set status='processing',lease_expires_at=now()+interval '1 minute' where id=current_setting('focusos.capture.result')::uuid;
set local role authenticated;
do $$
begin
 if public.focusos_next_gmail_capture('1','2','synthetic-model',array[current_setting('focusos.capture.raw')::uuid]) is not null then raise exception 'Live extraction lease ignored'; end if;
end $$;
reset role;
update public.extraction_results set status='failed',lease_expires_at=null where id=current_setting('focusos.capture.result')::uuid;
update public.source_items set body_expires_at=now()-interval '1 second' where id=current_setting('focusos.capture.source')::uuid;
set local role authenticated;
do $$
begin
 if public.focusos_next_gmail_capture('1','2','synthetic-model',array[current_setting('focusos.capture.raw')::uuid]) is not null then raise exception 'Expired source selected'; end if;
end $$;
reset role;
rollback;
select 'Gmail capture recovery, replay, indexing/search, ownership and intentional removals passed; fixtures rolled back' as result;
