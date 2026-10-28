# Deployment

## Hosted web application

`app.py` exports FastAPI for Vercel at <https://citation-grounded-rag.vercel.app/>. The Vercel project `citation-grounded-rag` is connected to the shared `agent-suite-supabase` resource and uses the `fastapi` framework preset. The hosted interface uses Supabase Auth email/password sessions in Secure, HttpOnly cookies. Every action verifies the user's token, then calls Supabase RPC with that same token. Postgres RLS limits passage access by `auth.uid()`; the SQL migration also revokes Supabase's broad default grants.

The shared [agent-suite-platform](https://github.com/kh-bikash/agent-suite-platform) repository owns all Supabase migrations. Apply them from there before deploying a database-dependent app. Store the database URL outside Git and avoid printing it. Run `scripts/check_supabase.py` with `DATABASE_URL` set to verify RLS and grants. `scripts/smoke_hosted.py` can verify two-user isolation using temporary accounts; it requires `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and `SUPABASE_SERVICE_ROLE_KEY`, and deletes its accounts afterward. The service role key is only for this operator check, never for the web app.

The web app needs `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` (or `SUPABASE_ANON_KEY`), which the Vercel integration supplies. Add `OPENAI_API_KEY`, plus optional `OPENAI_MODEL` and `OPENAI_BASE_URL`, for grounded answer generation. Search, ingestion, listing, and deletion work without a model key. Configure Supabase email delivery and confirmation redirects before inviting users at scale.

The hosted product permits 80,000 characters per ingest request, up to 100 chunks per source, and 2,000 passages per user. Source replacement is atomic. Postgres full-text search ranks results. Exact source quotes and retrieved IDs are checked before an answer is marked grounded; the answer's overall factual entailment is not formally proven.

Release checks: `uv lock --check`, `ruff check app.py src tests scripts`, `ruff format --check app.py src tests scripts`, `pytest -q`, schema access check, two-user smoke test, and public HTTP checks of `/`, `/healthz`, and unauthenticated 401 from `/api/session`.

## Local product

Install with `python -m pip install -e .`, then run the command shown in README. The browser binds to `127.0.0.1:8080` by default. `GET /healthz` is a lightweight health endpoint.

## Container

Copy `.env.example` to `.env`, replace every example secret, and keep that file outside Git. Build and run from this repository:

```bash
docker build -t citation-grounded-rag .
docker run --rm -p 127.0.0.1:8080:8080 --env-file .env -v citation_rag_data:/data citation-grounded-rag --db /data/knowledge.sqlite3 serve --port 8080
```

The image runs as a non-root user. It binds inside the container to `0.0.0.0`; the example publishes only to host loopback. A non-loopback bind requires `AGENT_WEB_TOKEN` of at least 16 characters. The browser asks for that token and sends it to the action endpoint. Put TLS and an authenticated reverse proxy in front of any public deployment.

Back up the citation_rag_data volume. Set OPENAI_API_KEY to enable answers; indexing and retrieval work without it.

## Release checks

Run `ruff check src tests`, `ruff format --check src tests`, and `pytest -q`. Test the browser action path and `/healthz` after deployment. Keep secrets in the deployment platform, monitor failed actions and model/provider errors, and set backups for any mounted data volume.
