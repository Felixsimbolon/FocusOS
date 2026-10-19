-- Read-only checks of the bucket and the table constraint.
do $$
begin
 if not (select allowed_mime_types @> array['text/markdown','application/vnd.openxmlformats-officedocument.wordprocessingml.document']
         from storage.buckets where id='project-files')
 then raise exception 'Bucket still refuses Word or Markdown files'; end if;
 if position('text/markdown' in (select pg_get_constraintdef(oid) from pg_constraint
            where conrelid='public.project_files'::regclass and conname='project_files_mime_type_check'))=0
 then raise exception 'Project files still refuse Markdown'; end if;
end $$;
