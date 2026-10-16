-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid(); s uuid;
 body text:=E'Audiens demo Nusa adalah backend engineers.\nGym membership costs 350 thousand rupiah.';
 near text:='['||array_to_string(array[1]||array_fill(0,array[255]),',')||']';
 far text:='['||array_to_string(array[0.5,0.8660254]||array_fill(0,array[254]),',')||']';
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@floor-test.invalid');
 insert into public.source_items(user_id,kind,title,normalized_body,body_hash,request_id,request_hash,received_at)
 values(o,'manual','Semantic floor fixture',body,encode(sha256(convert_to(body,'UTF8')),'hex'),gen_random_uuid(),repeat('e',64),now())
 returning id into s;
 perform set_config('focusos.floor.owner',o::text,true);
 perform set_config('focusos.floor.source',s::text,true);
 perform set_config('focusos.floor.near',near,true);
 perform set_config('focusos.floor.far',far,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.floor.owner'),true);
do $$
declare s uuid:=current_setting('focusos.floor.source')::uuid;
begin
 perform public.focusos_confirm_memory(gen_random_uuid(),s,null,
  'Audiens demo Nusa adalah backend engineers.','Audiens demo Nusa adalah backend engineers.');
 perform public.focusos_confirm_memory(gen_random_uuid(),s,null,
  'Gym membership costs 350 thousand rupiah.','Gym membership costs 350 thousand rupiah.');
end $$;
reset role;
-- Give the memories known vectors: cosine 1.0 and 0.5 to the query vector.
update public.memories set embedding_status='ready',embedding_model='gemini-embedding-2',embedding_dim=256,embedding_hash=repeat('a',64),
  embedding=(case when text like 'Audiens%' then current_setting('focusos.floor.near') else current_setting('focusos.floor.far') end)::extensions.vector(256)
where user_id=current_setting('focusos.floor.owner')::uuid;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.floor.owner'),true);
do $$
declare response jsonb;
begin
 -- No keyword overlap, so only the semantic floor decides what is returned.
 response:=public.focusos_search_memories_hybrid('who watches the talk',array['who','watches','talk'],current_setting('focusos.floor.near'),8);
 if jsonb_array_length(response)<>1 or response->0->>'text' not like 'Audiens%' then
   raise exception 'Semantic floor must drop the cosine-0.5 memory: %',response; end if;
 if response->0->>'match_kind'<>'semantic' then raise exception 'Unexpected match kind'; end if;
 -- A keyword match still returns a memory below the semantic floor.
 response:=public.focusos_search_memories_hybrid('gym cost',array['gym'],current_setting('focusos.floor.near'),8);
 if not exists(select 1 from jsonb_array_elements(response) r where r->>'text' like 'Gym%' and r->>'match_kind'='lexical') then
   raise exception 'Keyword match below the floor was dropped: %',response; end if;
end $$;
rollback;
