-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid(); other uuid:=gen_random_uuid(); s uuid;
 body text:=E'Buat halaman web, deadline 18 Oktober 2026.\nAudiens demo Nusa adalah backend engineers.';
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@hybrid-test.invalid'),
   (other,'authenticated','authenticated',other::text||'@hybrid-test.invalid');
 insert into public.source_items(user_id,kind,title,normalized_body,body_hash,request_id,request_hash,received_at)
 values(o,'manual','Hybrid search fixture',body,encode(sha256(convert_to(body,'UTF8')),'hex'),gen_random_uuid(),repeat('d',64),now())
 returning id into s;
 perform set_config('focusos.hybrid.owner',o::text,true);
 perform set_config('focusos.hybrid.other',other::text,true);
 perform set_config('focusos.hybrid.source',s::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.hybrid.owner'),true);
do $$
declare s uuid:=current_setting('focusos.hybrid.source')::uuid; response jsonb;
begin
 perform public.focusos_confirm_memory(gen_random_uuid(),s,null,
  'Task: Buat halaman web. Deadline 18 Oktober 2026.','Buat halaman web, deadline 18 Oktober 2026.');
 perform public.focusos_confirm_memory(gen_random_uuid(),s,null,
  'Audiens demo Nusa adalah backend engineers.','Audiens demo Nusa adalah backend engineers.');
 -- ts_rank gives an unrelated memory 1e-20, so the old "> 0" filter returned every memory.
 response:=public.focusos_search_memories('Kapan deadline halaman web?',null,null,5);
 if jsonb_array_length(response)<>2 then raise exception 'Fixture no longer reproduces the unrelated-row noise'; end if;
 response:=public.focusos_search_memories_hybrid('Kapan deadline halaman web?',array['deadline','halaman','web'],null,8);
 if jsonb_array_length(response)<>1 or response->0->>'text' not like 'Task: Buat halaman web%' then
   raise exception 'Hybrid search must return only the task memory: %',response; end if;
 if response->0->>'match_kind'<>'lexical' then raise exception 'Unexpected match kind'; end if;
 -- Prefix terms match inflected words; unrelated memories are not returned.
 response:=public.focusos_search_memories_hybrid('siapa audiens',array['audien'],null,8);
 if jsonb_array_length(response)<>1 or response->0->>'text' not like 'Audiens%' then raise exception 'Prefix term missed'; end if;
 response:=public.focusos_search_memories_hybrid('apa?','{}',null,8);
 if jsonb_array_length(response)<>0 then raise exception 'Empty terms without a vector must return nothing'; end if;
 begin
  perform public.focusos_search_memories_hybrid('x',array['bad term'],null,8);
  raise exception 'Unsafe term accepted';
 exception when sqlstate '22023' then null; end;
 begin
  perform public.focusos_search_memories_hybrid('x',array['web'],null,11);
  raise exception 'Unbounded limit accepted';
 exception when sqlstate '22023' then null; end;
end $$;
select set_config('request.jwt.claim.sub',current_setting('focusos.hybrid.other'),true);
do $$
begin
 if jsonb_array_length(public.focusos_search_memories_hybrid('halaman web',array['halaman','web'],null,8))<>0 then
   raise exception 'Another user can read memories'; end if;
end $$;
rollback;
