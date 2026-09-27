-- PostgreSQL ARE bounds do not accept {5,1024}; use explicit length plus alphabet.
alter table public.approval_requests drop constraint approval_requests_event_id_check;
alter table public.approval_requests add constraint approval_event_id_format
 check(char_length(event_id) between 5 and 1024 and event_id ~ '^[a-v0-9]+$');
