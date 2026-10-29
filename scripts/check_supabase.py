"""Verify the hosted RAG schema and anonymous access boundaries.

Set DATABASE_URL in the shell; never commit a connection string.
"""

from __future__ import annotations

import os

import psycopg


def main() -> None:
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, connect_timeout=8) as db:
        enabled = db.execute(
            "select relrowsecurity from pg_class where oid='public.rag_passages'::regclass"
        ).fetchone()[0]
        policies = db.execute(
            "select count(*) from pg_policies where schemaname='public' and tablename='rag_passages'"
        ).fetchone()[0]
        anon_insert = db.execute(
            "select has_table_privilege('anon','public.rag_passages','INSERT')"
        ).fetchone()[0]
        anon_search = db.execute(
            "select has_function_privilege('anon','public.rag_search(text,integer)','EXECUTE')"
        ).fetchone()[0]
        authenticated_truncate = db.execute(
            "select has_table_privilege('authenticated','public.rag_passages','TRUNCATE')"
        ).fetchone()[0]
    assert enabled and policies >= 3
    assert not anon_insert, "anon can insert passages"
    assert not anon_search, "anon can call search"
    assert not authenticated_truncate, "authenticated can bypass RLS with TRUNCATE"
    print("RAG schema and anonymous access checks passed")


if __name__ == "__main__":
    main()
