-- Projects keep Word and Markdown/text briefs as well as PDFs and photos.
update storage.buckets set allowed_mime_types=array['application/pdf','image/png','image/jpeg','image/webp','application/vnd.openxmlformats-officedocument.wordprocessingml.document','text/markdown','text/plain'] where id='project-files';
alter table public.project_files drop constraint project_files_mime_type_check,
 add constraint project_files_mime_type_check check(mime_type in ('application/pdf','image/png','image/jpeg','image/webp','application/vnd.openxmlformats-officedocument.wordprocessingml.document','text/markdown','text/plain'));
