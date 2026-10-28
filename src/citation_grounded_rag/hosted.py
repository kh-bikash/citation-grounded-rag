"""Supabase-backed document actions for the hosted RAG application."""

from __future__ import annotations

import json
import os

import httpx

from .engine import Answer, Passage
from .llm import OpenAICompatibleLLM


class HostedDataError(RuntimeError):
    """A database request failed without exposing internal SQL details."""


def _rpc(name: str, values: dict, access_token: str):
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get(
        "SUPABASE_ANON_KEY", ""
    )
    if not url.startswith("https://") or not key:
        raise HostedDataError("Document storage is unavailable")
    try:
        with httpx.Client(timeout=12.0) as client:
            response = client.post(
                f"{url}/rest/v1/rpc/{name}",
                headers={"apikey": key, "Authorization": f"Bearer {access_token}"},
                json=values,
            )
    except httpx.RequestError as exc:
        raise HostedDataError("Document storage is unavailable") from exc
    if response.status_code == 401:
        raise HostedDataError("Session expired; sign in again")
    if response.status_code == 403:
        raise HostedDataError("Document access denied")
    if response.status_code >= 400:
        try:
            message = response.json().get("message", "")
        except (ValueError, TypeError):
            message = ""
        if "quota exceeded" in message:
            raise ValueError("Your document quota has been reached")
        raise HostedDataError("Document operation failed")
    return response.json()


def _chunks(
    text: str, *, chunk_chars: int = 1000, overlap_chars: int = 100
) -> list[str]:
    if not text.strip() or len(text) > 80_000:
        raise ValueError("Document must contain 1 to 80,000 characters")
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        if text[start:end].strip():
            chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap_chars
    return chunks


def _passages(query: str, access_token: str) -> list[Passage]:
    if not query.strip() or len(query) > 300:
        raise ValueError("Query must contain 1 to 300 characters")
    rows = _rpc("rag_search", {"p_query": query, "p_limit": 5}, access_token)
    return [
        Passage(int(row["id"]), row["source"], row["content"], float(row["score"]))
        for row in rows
    ]


def _answer(query: str, passages: list[Passage]) -> Answer:
    if not passages:
        return Answer("I could not find relevant source material.", (), 0.0, False)
    context = "\n".join(f"[{p.id}] {p.source}: {p.text}" for p in passages)
    raw = OpenAICompatibleLLM.from_env().complete(
        [
            {
                "role": "system",
                "content": "Answer only from supplied passages. Return JSON with keys answer, evidence (array of {id: integer, quote: exact supporting substring}), confidence (0 to 1). If unsupported, say so and use no evidence.",
            },
            {"role": "user", "content": f"Question: {query}\nPassages:\n{context}"},
        ]
    )
    try:
        data = json.loads(raw)
        evidence = data["evidence"]
        confidence = float(data["confidence"])
        by_id = {p.id: p for p in passages}
        ids = [item["id"] for item in evidence]
        selected = tuple(by_id[i] for i in ids)
        grounded = (
            bool(selected)
            and len(selected) == len(set(ids))
            and all(
                item["quote"].strip() and item["quote"] in by_id[item["id"]].text
                for item in evidence
            )
            and 0.55 <= confidence <= 1
        )
        if grounded:
            return Answer(str(data["answer"]), selected, confidence, True)
    except (ValueError, TypeError, KeyError):
        pass
    return Answer(
        "The available sources do not support a confident answer.", (), 0.0, False
    )


def run_action(action: str, values: dict[str, str], access_token: str) -> object:
    """Execute an authenticated action using the caller's Supabase JWT for RLS."""
    if action == "ingest-text":
        source = values["source"].strip()
        if not 1 <= len(source) <= 200:
            raise ValueError("Source name must contain 1 to 200 characters")
        count = _rpc(
            "rag_replace_source",
            {"p_source": source, "p_chunks": _chunks(values["text"])},
            access_token,
        )
        return {"chunks": count}
    if action == "search":
        return [
            passage.__dict__ for passage in _passages(values["query"], access_token)
        ]
    if action == "ask":
        answer = _answer(values["query"], _passages(values["query"], access_token))
        return {
            "answer": answer.text,
            "grounded": answer.grounded,
            "confidence": answer.confidence,
            "citations": [passage.__dict__ for passage in answer.citations],
        }
    if action == "sources":
        return _rpc("rag_sources", {}, access_token)
    if action == "delete":
        return {
            "deleted_chunks": _rpc(
                "rag_delete_source", {"p_source": values["source"]}, access_token
            )
        }
    raise ValueError("Unknown action")
