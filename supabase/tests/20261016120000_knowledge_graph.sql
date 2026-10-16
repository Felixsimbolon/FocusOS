-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid(); s uuid;
 body text:=E'Kode nama proyek demo FocusOS adalah Nusa.\nAudiens demo Nusa adalah backend engineers.\nGym costs 350 ribu.';
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@graph-test.invalid');
 insert into public.source_items(user_id,kind,title,normalized_body,body_hash,request_id,request_hash,received_at)
 values(o,'manual','Graph fixture',body,encode(sha256(convert_to(body,'UTF8')),'hex'),gen_random_uuid(),repeat('9',64),now())
 returning id into s;
 perform set_config('focusos.graph.owner',o::text,true);
 perform set_config('focusos.graph.source',s::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.graph.owner'),true);
do $$
declare s uuid:=current_setting('focusos.graph.source')::uuid; m_code uuid; m_aud uuid; m_gym uuid; v jsonb;
begin
 perform public.focusos_confirm_memory(gen_random_uuid(),s,null,'Kode nama proyek demo FocusOS adalah Nusa.','Kode nama proyek demo FocusOS adalah Nusa.');
 perform public.focusos_confirm_memory(gen_random_uuid(),s,null,'Audiens demo Nusa adalah backend engineers.','Audiens demo Nusa adalah backend engineers.');
 perform public.focusos_confirm_memory(gen_random_uuid(),s,null,'Gym costs 350 ribu.','Gym costs 350 ribu.');
 select id into m_code from public.memories where text like 'Kode nama%';
 select id into m_aud from public.memories where text like 'Audiens%';
 select id into m_gym from public.memories where text like 'Gym%';
 perform public.focusos_save_memory_graph(m_code,
   '[{"key":"f","kind":"project","name":"FocusOS"},{"key":"n","kind":"project","name":"Nusa"}]',
   '[{"subject":"f","predicate":"code_name","object":"n"}]');
 perform public.focusos_save_memory_graph(m_aud,'[{"key":"n","kind":"project","name":"Nusa"}]',
   '[{"subject":"n","predicate":"audience","object_text":"backend engineers"}]');
 -- Entities merge by normalized name across memories.
 if (select count(*) from public.entities where normalized='nusa')<>1 then raise exception 'Nusa was duplicated'; end if;
 -- Asking about FocusOS reaches the audience memory through Nusa (one hop).
 v:=public.focusos_graph_memories(array['focusos'],2,10);
 if not exists(select 1 from jsonb_array_elements(v) r where r->>'text' like 'Audiens%' and (r->>'hop')::int=1
               and r->>'path' like 'FocusOS%Nusa%') then raise exception 'Multi-hop memory missing: %',v; end if;
 if exists(select 1 from jsonb_array_elements(v) r where r->>'text' like 'Gym%') then raise exception 'Unrelated memory returned'; end if;
 -- Zero hops: only memories that mention the named entity.
 v:=public.focusos_graph_memories(array['focusos'],0,10);
 if jsonb_array_length(v)<>1 then raise exception 'Hop limit ignored: %',v; end if;
 begin
  perform public.focusos_save_memory_graph(m_gym,'[{"key":"x","kind":"person","name":"Maria"}]','[]');
  raise exception 'Name absent from the memory was accepted';
 exception when sqlstate '22023' then null; end;
 begin
  perform public.focusos_save_memory_graph(m_gym,'[{"key":"g","kind":"thing","name":"Gym"}]',
    '[{"subject":"g","predicate":"price","object_text":"999 ribu"}]');
  raise exception 'Object text absent from the memory was accepted';
 exception when sqlstate '22023' then null; end;
 begin
  perform public.focusos_graph_memories(array['bad term'],1,5);
  raise exception 'Unsafe term accepted';
 exception when sqlstate '22023' then null; end;
 begin
  perform public.focusos_graph_memories(array['nusa'],3,5);
  raise exception 'Unbounded hops accepted';
 exception when sqlstate '22023' then null; end;
 begin
  insert into public.entities(user_id,kind,name,normalized) values(auth.uid(),'person','X','x');
  raise exception 'Direct write allowed';
 exception when insufficient_privilege then null; end;
end $$;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000003',true);
do $$
begin
 if jsonb_array_length(public.focusos_graph_memories(array['nusa'],2,10))<>0 then raise exception 'Another user reached the graph'; end if;
 if exists(select 1 from public.entities) then raise exception 'Another user can read entities'; end if;
end $$;
rollback;
