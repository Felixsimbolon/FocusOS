-- Every note belongs to a project. A note left without one (its project was deleted) keeps its text
-- and can be read, but saving it again needs a project.
create or replace function public.focusos_save_note(p_id uuid,p_project_id uuid,p_title text,p_body text,p_expected_version integer)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.notes;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_project_id is null then raise exception 'Project required' using errcode='23502'; end if;
 if not exists(select 1 from public.projects where id=p_project_id and user_id=v_owner)
 then raise exception 'Project not found' using errcode='P0002'; end if;
 if (select count(*) from public.notes where user_id=v_owner)>=2000 and p_expected_version=0
 then raise exception 'Too many notes' using errcode='54000'; end if;
 select * into v_row from public.notes where id=p_id;
 if found and v_row.user_id<>v_owner then raise exception 'Note not found' using errcode='P0002'; end if;
 if not found then
   if p_expected_version<>0 then raise exception 'Note not found' using errcode='P0002'; end if;
   insert into public.notes(id,user_id,project_id,title,body) values(p_id,v_owner,p_project_id,pg_catalog.btrim(p_title),p_body)
   returning * into v_row;
 else
   if v_row.version<>p_expected_version then
     -- Replaying the save that produced this version is fine; anything else changed elsewhere.
     if not (v_row.version=p_expected_version+1 and v_row.title=pg_catalog.btrim(p_title) and v_row.body=p_body
             and v_row.project_id is not distinct from p_project_id)
     then raise exception 'Note changed elsewhere' using errcode='40001'; end if;
   else
     update public.notes set project_id=p_project_id,title=pg_catalog.btrim(p_title),body=p_body,version=version+1,updated_at=now()
     where id=p_id returning * into v_row;
   end if;
 end if;
 return pg_catalog.jsonb_build_object('id',v_row.id,'project_id',v_row.project_id,'title',v_row.title,'body',v_row.body,
   'version',v_row.version,'updated_at',v_row.updated_at);
end; $$;
