# Architecture

## Goal

Index text in SQLite FTS5, retrieve relevant passages, require exact source quotes for every citation, and optionally use a search fallback.

## Request path

Ingest -> fixed text chunks -> SQLite FTS5 -> BM25 retrieval -> model answer with evidence quotes -> quote and source ID validation -> optional search fallback -> answer or abstention.

## Components

- `src/citation_grounded_rag/engine.py`: policy and state transitions for this project.
- `src/citation_grounded_rag/llm.py`: injected model protocol and HTTPS OpenAI-compatible adapter with timeouts and retry for transient transport failures.
- `tests/test_engine.py`: deterministic behavior and failure tests.
- `.github/workflows/ci.yml`: install and test gate.


## State and failure behavior

Exact quotes and source IDs are checked, but entailment of the full answer is not formally proved. Add domain evaluations and human review for high stakes use. Ingestion replaces passages for a source atomically.

The LLM adapter times out after 30 seconds and retries transient HTTP failures twice. Model output is untrusted input and is parsed or validated at the project boundary.

## Operations checklist

1. Set secrets through a secret manager and rotate them regularly.
2. Put the service or integrating application behind TLS and authentication.
3. Persist and back up the SQLite FTS5 index. Rebuild it from trusted source documents after corruption or schema changes.
4. Run `pytest -q` in CI before deployment.
5. Define workload specific evaluation cases, latency objectives, and rollback criteria before serving real users.

## Index and answer lifecycle

`passages` is an SQLite FTS5 virtual table. `ingest` splits text into overlapping chunks and replaces all chunks for a source within one transaction; `ingest_file` enforces a byte limit and UTF-8 encoding. `sources` and `delete_source` provide index maintenance. Search uses FTS5 BM25 ranking. A caller-provided `fallback_search` may ingest extra documents once when retrieval or grounding fails.

The model must return an answer, confidence, and evidence items with an exact quote and passage ID. The validator checks that every ID was in the retrieved set and every quote is an exact substring of its passage. If confidence falls below `min_confidence`, or evidence is malformed, the agent abstains after the optional fallback. This establishes provenance, not formal entailment; evaluate answer correctness with domain data.

| Failure | Behavior |
|---|---|
| No matching passage | One search fallback, then abstain |
| Fabricated ID or quote | Reject answer |
| Unparseable model JSON | Reject answer |
| Source update | Atomic replacement of that source's chunks |
