-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid(); x uuid:=gen_random_uuid();
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@files-test.invalid'),
                                                (x,'authenticated','authenticated',x::text||'@files-test.invalid');
 perform set_config('focusos.files.owner',o::text,true);
 perform set_config('focusos.files.other',x::text,true);
end $$;

-- The bucket exists, is private and takes only the four document types.
do $$
begin
 if not exists(select 1 from storage.buckets where id='project-files' and public=false and file_size_limit=3000000
   and allowed_mime_types @> array['application/pdf','image/png','image/jpeg','image/webp'])
 then raise exception 'Bucket missing or public'; end if;
end $$;

set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.files.owner'),true);
do $$
declare o text:=current_setting('focusos.files.owner'); f uuid:=gen_random_uuid(); p uuid; v jsonb; again jsonb;
begin
 select (project->>'id')::uuid into p from public.focusos_create_project('Statistika');
 v:=public.focusos_add_project_file(f,p,null,' brief.pdf ','application/pdf',1200,o||'/'||f||'/brief.pdf');
 if v->>'name'<>'brief.pdf' or v ? 'user_id' then raise exception 'Add failed: %',v; end if;
 -- A retry with the same id returns the same row.
 again:=public.focusos_add_project_file(f,p,null,'brief.pdf','application/pdf',1200,o||'/'||f||'/brief.pdf');
 if again->>'id'<>v->>'id' or (select count(*) from public.project_files)<>1 then raise exception 'Retry duplicated'; end if;
 -- A path outside the owner's folder is refused.
 begin
  perform public.focusos_add_project_file(gen_random_uuid(),p,null,'x.pdf','application/pdf',10,current_setting('focusos.files.other')||'/x/x.pdf');
  raise exception 'Foreign path accepted';
 exception when check_violation then null; end;
 -- An unknown project is refused.
 begin
  perform public.focusos_add_project_file(gen_random_uuid(),gen_random_uuid(),null,'x.pdf','application/pdf',10,o||'/y/x.pdf');
  raise exception 'Unknown project accepted';
 exception when sqlstate 'P0002' then null; end;
 -- A file that is not one of the four types is refused.
 begin
  perform public.focusos_add_project_file(gen_random_uuid(),p,null,'x.exe','application/x-msdownload',10,o||'/z/x.exe');
  raise exception 'Executable accepted';
 exception when check_violation then null; end;
 perform set_config('focusos.files.file',f::text,true);
end $$;

-- Another user sees nothing and cannot delete it.
select set_config('request.jwt.claim.sub',current_setting('focusos.files.other'),true);
do $$
begin
 if (select count(*) from public.project_files)<>0 then raise exception 'Files visible to another user'; end if;
 if public.focusos_delete_project_file(current_setting('focusos.files.file')::uuid) is not null then raise exception 'Foreign delete succeeded'; end if;
end $$;

-- The owner deletes it and gets the storage path back once.
select set_config('request.jwt.claim.sub',current_setting('focusos.files.owner'),true);
do $$
declare path text;
begin
 path:=public.focusos_delete_project_file(current_setting('focusos.files.file')::uuid);
 if path is null or path not like current_setting('focusos.files.owner')||'/%' then raise exception 'Delete failed: %',path; end if;
 if public.focusos_delete_project_file(current_setting('focusos.files.file')::uuid) is not null then raise exception 'Deleted twice'; end if;
end $$;

-- Anonymous callers cannot add files.
reset role;
set local role anon;
do $$
begin
 perform public.focusos_add_project_file(gen_random_uuid(),null,null,'x.pdf','application/pdf',10,'a/b/c.pdf');
 raise exception 'Anonymous add allowed';
exception when insufficient_privilege then null; end $$;
rollback;
