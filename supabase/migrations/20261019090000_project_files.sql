-- Project files: PDFs and photos kept with a project (assignment briefs, syllabi, handouts).
-- The bytes live in a private Storage bucket under "<owner>/<file id>/<name>"; a row here
-- says which project (or assignment) a file belongs to. Only the owner can read either.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('project-files','project-files',false,3000000,array['application/pdf','image/png','image/jpeg','image/webp'])
on conflict(id) do update set public=false,file_size_limit=excluded.file_size_limit,allowed_mime_types=excluded.allowed_mime_types;

create policy project_files_objects_read on storage.objects for select to authenticated
 using(bucket_id='project-files' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy project_files_objects_insert on storage.objects for insert to authenticated
 with check(bucket_id='project-files' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy project_files_objects_delete on storage.objects for delete to authenticated
 using(bucket_id='project-files' and (storage.foldername(name))[1]=(select auth.uid())::text);

create table public.project_files (
 id uuid primary key,
 user_id uuid not null references auth.users(id) on delete cascade,
 project_id uuid,
 assignment_id uuid,
 name text not null check(char_length(btrim(name)) between 1 and 120),
 mime_type text not null check(mime_type in ('application/pdf','image/png','image/jpeg','image/webp')),
 size_bytes integer not null check(size_bytes between 1 and 3000000),
 storage_path text not null unique,
 created_at timestamptz not null default now(),
 unique(user_id,id),
 check(storage_path like user_id::text||'/'||id::text||'/%'),
 foreign key(user_id,project_id) references public.projects(user_id,id) on delete set null (project_id),
 foreign key(user_id,assignment_id) references public.assignments(user_id,id) on delete set null (assignment_id)
);
create index project_files_owner_project on public.project_files(user_id,project_id,created_at desc);
create index project_files_owner_assignment on public.project_files(user_id,assignment_id) where assignment_id is not null;
alter table public.project_files enable row level security;
revoke all on public.project_files from public,anon,authenticated;
grant select on public.project_files to authenticated;
create policy project_files_read_owner on public.project_files for select to authenticated using(user_id=(select auth.uid()));

-- Record a file already uploaded to the owner's folder. The id is chosen by the client, so a retry returns the same row.
create function public.focusos_add_project_file(p_id uuid,p_project_id uuid,p_assignment_id uuid,p_name text,p_mime_type text,p_size integer,p_path text)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.project_files;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 select * into v_row from public.project_files where id=p_id;
 if found then
   if v_row.user_id<>v_owner then raise exception 'File not found' using errcode='P0002'; end if;
   return pg_catalog.to_jsonb(v_row) - 'user_id';
 end if;
 if p_project_id is not null and not exists(select 1 from public.projects where id=p_project_id and user_id=v_owner)
 then raise exception 'Project not found' using errcode='P0002'; end if;
 if p_assignment_id is not null and not exists(select 1 from public.assignments where id=p_assignment_id and user_id=v_owner)
 then raise exception 'Assignment not found' using errcode='P0002'; end if;
 if (select count(*) from public.project_files where user_id=v_owner)>=500
 then raise exception 'Too many files' using errcode='54000'; end if;
 insert into public.project_files(id,user_id,project_id,assignment_id,name,mime_type,size_bytes,storage_path)
 values(p_id,v_owner,p_project_id,p_assignment_id,pg_catalog.btrim(p_name),p_mime_type,p_size,p_path) returning * into v_row;
 return pg_catalog.to_jsonb(v_row) - 'user_id';
end; $$;

-- Forget a file; returns its storage path so the caller can remove the bytes, or null if there was none.
create function public.focusos_delete_project_file(p_id uuid)
returns text language plpgsql security definer set search_path=''
as $$
declare v_path text;
begin
 if (select auth.uid()) is null then raise exception 'Authentication required' using errcode='28000'; end if;
 delete from public.project_files where id=p_id and user_id=(select auth.uid()) returning storage_path into v_path;
 return v_path;
end; $$;

revoke all on function public.focusos_add_project_file(uuid,uuid,uuid,text,text,integer,text) from public,anon;
revoke all on function public.focusos_delete_project_file(uuid) from public,anon;
grant execute on function public.focusos_add_project_file(uuid,uuid,uuid,text,text,integer,text) to authenticated;
grant execute on function public.focusos_delete_project_file(uuid) to authenticated;
