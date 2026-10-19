-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid();
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@note-project-test.invalid');
 insert into public.projects(user_id,name) values(o,'Skripsi');
 perform set_config('focusos.note.owner',o::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.note.owner'),true);
do $$
declare project uuid:=(select id from public.projects limit 1); saved jsonb;
begin
 begin
  perform public.focusos_save_note(gen_random_uuid(),null,'Catatan umum','isi',0);
  raise exception 'A note without a project was saved';
 exception when not_null_violation then null;
 end;
 saved:=public.focusos_save_note(gen_random_uuid(),project,'Catatan bab 1','isi',0);
 if saved->>'project_id'<>project::text then raise exception 'Note lost its project'; end if;
end $$;
rollback;
