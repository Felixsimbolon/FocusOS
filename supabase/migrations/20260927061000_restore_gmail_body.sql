-- Restore the same selected body after lazy retention expiry without inventing a new content version.
create or replace function public.focusos_upsert_gmail_source(
 p_connection_id uuid,p_message_id text,p_thread_id text,p_history_id text,
 p_label_id text,p_title text,p_sender text,p_received_at timestamptz,
 p_body text,p_body_hash text,p_truncated boolean,p_has_attachments boolean
) returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.source_items;
declare v_created boolean := false; v_changed boolean := false; v_restore boolean := false;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if not exists(select 1 from public.connections where id=p_connection_id and user_id=v_owner
   and status='connected' and 'https://www.googleapis.com/auth/gmail.readonly'=any(granted_scopes)) then
   return jsonb_build_object('outcome','connection_unavailable');
 end if;
 if p_message_id !~ '^[A-Za-z0-9_-]{1,128}$'
   or p_thread_id !~ '^[A-Za-z0-9_-]{1,128}$'
   or p_label_id !~ '^[A-Za-z0-9_-]{1,128}$'
   or p_body_hash !~ '^[0-9a-f]{64}$'
   or (p_body is not null and octet_length(p_body)>20480)
   or p_received_at is null or char_length(p_title) not between 1 and 200 then
   raise exception 'Invalid Gmail source' using errcode='22023';
 end if;
 insert into public.source_items(
   user_id,kind,connection_id,provider_message_id,thread_id,gmail_history_id,
   selected_label_id,title,sender,received_at,normalized_body,body_hash,
   body_truncated,has_attachments,request_id,request_hash)
 values(v_owner,'gmail',p_connection_id,p_message_id,p_thread_id,p_history_id,
   p_label_id,p_title,p_sender,p_received_at,p_body,p_body_hash,
   p_truncated,p_has_attachments,gen_random_uuid(),p_body_hash)
 on conflict (connection_id,provider_message_id) where kind='gmail' do nothing
 returning * into v_row;
 if v_row.id is not null then
   v_created := true;
 else
   select * into v_row from public.source_items
    where connection_id=p_connection_id and provider_message_id=p_message_id and user_id=v_owner
    for update;
   if v_row.id is null then raise exception 'Gmail source unresolved'; end if;
   v_changed := v_row.body_hash<>p_body_hash or v_row.normalization_version<>'1';
   v_restore := v_row.normalized_body is null and p_body is not null;
   update public.source_items set
     title=p_title,sender=p_sender,thread_id=p_thread_id,gmail_history_id=p_history_id,
     selected_label_id=p_label_id,received_at=p_received_at,
     normalized_body=case when v_changed or v_restore then p_body else normalized_body end,
     body_hash=case when v_changed then p_body_hash else body_hash end,
     body_truncated=p_truncated,has_attachments=p_has_attachments,
     body_expires_at=case when v_changed or v_restore then now()+interval '30 days' else body_expires_at end,
     content_version=case when v_changed then content_version+1 else content_version end,
     normalization_version='1'
    where id=v_row.id returning * into v_row;
 end if;
 return jsonb_build_object('outcome','saved','source',to_jsonb(v_row),
   'created',v_created,'changed',v_changed);
end;
$$;
revoke all on function public.focusos_upsert_gmail_source(
 uuid,text,text,text,text,text,text,timestamptz,text,text,boolean,boolean)
 from public,anon;
grant execute on function public.focusos_upsert_gmail_source(
 uuid,text,text,text,text,text,text,timestamptz,text,text,boolean,boolean)
 to authenticated;
