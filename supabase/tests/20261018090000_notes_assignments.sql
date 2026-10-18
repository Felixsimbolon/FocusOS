-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid(); s uuid; body text:='Tugas 2: laporan regresi linear, deadline 24 Oktober.';
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@notes-test.invalid');
 insert into public.source_items(user_id,kind,title,normalized_body,body_hash,request_id,request_hash,received_at)
 values(o,'manual','Assignment: tugas2.pdf',body,encode(sha256(convert_to(body,'UTF8')),'hex'),gen_random_uuid(),repeat('e',64),now())
 returning id into s;
 perform set_config('focusos.notes.owner',o::text,true);
 perform set_config('focusos.notes.source',s::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.notes.owner'),true);
do $$
declare n uuid:=gen_random_uuid(); v jsonb; p uuid; a jsonb; key uuid:=gen_random_uuid(); vec text;
begin
 select (project->>'id')::uuid into p from public.focusos_create_project('Statistika');
 v:=public.focusos_save_note(n,p,'Kuliah 3','Regresi linear memodelkan hubungan antara dua variabel.',0);
 if (v->>'version')::int<>1 then raise exception 'Create failed: %',v; end if;
 v:=public.focusos_save_note(n,p,'Kuliah 3','Regresi linear memodelkan hubungan antara dua variabel. Uji asumsi penting.',1);
 if (v->>'version')::int<>2 then raise exception 'Update failed'; end if;
 -- Replaying the save that made version 2 is fine; an older version is a conflict.
 perform public.focusos_save_note(n,p,'Kuliah 3','Regresi linear memodelkan hubungan antara dua variabel. Uji asumsi penting.',1);
 begin
  perform public.focusos_save_note(n,p,'Kuliah 3','Edit from another window',1);
  raise exception 'Stale save accepted';
 exception when sqlstate '40001' then null; end;
 vec:='['||array_to_string(array[1]||array_fill(0,array[255]),',')||']';
 if not public.focusos_set_note_embedding(n,2,vec) then raise exception 'Embedding not stored'; end if;
 if public.focusos_set_note_embedding(n,1,vec) then raise exception 'Stale embedding stored'; end if;
 v:=public.focusos_search_notes(array['regresi'],null,3);
 if jsonb_array_length(v)<>1 or v->0->>'title'<>'Kuliah 3' then raise exception 'Keyword search failed: %',v; end if;
 v:=public.focusos_search_notes(array['zzz'],vec,3);
 if jsonb_array_length(v)<>1 then raise exception 'Vector search failed: %',v; end if;
 v:=public.focusos_search_notes(array['zzz'],null,3);
 if jsonb_array_length(v)<>0 then raise exception 'Unrelated note returned'; end if;

 a:=public.focusos_create_assignment(key,current_setting('focusos.notes.source')::uuid,'tugas2');
 if public.focusos_create_assignment(key,current_setting('focusos.notes.source')::uuid,'tugas2')->>'id'<>a->>'id' then raise exception 'Assignment duplicated'; end if;
 a:=public.focusos_update_assignment((a->>'id')::uuid,1,jsonb_build_object('status','questions','analysis',jsonb_build_object('title','Tugas 2'),'title','Tugas 2'));
 if a->>'status'<>'questions' or (a->>'version')::int<>2 then raise exception 'Assignment update failed: %',a; end if;
 a:=public.focusos_update_assignment((a->>'id')::uuid,2,jsonb_build_object('project_id',p,'status','planned'));
 begin
  perform public.focusos_update_assignment((a->>'id')::uuid,2,jsonb_build_object('status','questions'));
  raise exception 'Stale assignment update accepted';
 exception when sqlstate '40001' then null; end;
 begin
  perform public.focusos_update_assignment((a->>'id')::uuid,3,jsonb_build_object('user_id',gen_random_uuid()));
  raise exception 'Owner change accepted';
 exception when sqlstate '22023' then null; end;
 begin
  insert into public.notes(id,user_id,title) values(gen_random_uuid(),auth.uid(),'direct');
  raise exception 'Direct note write allowed';
 exception when insufficient_privilege then null; end;
 perform set_config('focusos.notes.note',n::text,true);
end $$;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000006',true);
do $$
begin
 if exists(select 1 from public.notes) or exists(select 1 from public.assignments) then raise exception 'Another user can read notes or assignments'; end if;
 begin
  perform public.focusos_save_note(current_setting('focusos.notes.note')::uuid,null,'Taken over','x',2);
  raise exception 'Another user edited the note';
 exception when sqlstate 'P0002' then null; end;
 if public.focusos_delete_note(current_setting('focusos.notes.note')::uuid) then raise exception 'Another user deleted the note'; end if;
end $$;
rollback;
