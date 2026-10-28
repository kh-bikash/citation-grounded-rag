-- Supabase projects may grant broad privileges on new public objects by default.
-- RLS does not cover TRUNCATE or sequence privileges, so explicitly narrow them.
revoke all on table public.rag_passages from public, anon, authenticated;
grant select, insert, delete on table public.rag_passages to authenticated;

revoke all on sequence public.rag_passages_id_seq from public, anon, authenticated;
grant usage, select on sequence public.rag_passages_id_seq to authenticated;

revoke all on function public.rag_enforce_quota() from public, anon, authenticated;
revoke all on function public.rag_replace_source(text, text[]) from public, anon, authenticated;
revoke all on function public.rag_sources() from public, anon, authenticated;
revoke all on function public.rag_delete_source(text) from public, anon, authenticated;
revoke all on function public.rag_search(text, integer) from public, anon, authenticated;
grant execute on function public.rag_replace_source(text, text[]) to authenticated;
grant execute on function public.rag_sources() to authenticated;
grant execute on function public.rag_delete_source(text) to authenticated;
grant execute on function public.rag_search(text, integer) to authenticated;
