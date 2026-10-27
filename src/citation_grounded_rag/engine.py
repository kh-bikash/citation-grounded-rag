from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .llm import LLM


@dataclass(frozen=True)
class Passage:
    id: int
    source: str
    text: str
    score: float


@dataclass(frozen=True)
class Answer:
    text: str
    citations: tuple[Passage, ...]
    confidence: float
    grounded: bool


class CitationRAG:
    def __init__(self, db_path: str | Path, llm: LLM, *, min_confidence: float = 0.55,
                 fallback_search: Callable[[str], list[tuple[str, str]]] | None = None):
        self.db_path, self.llm, self.min_confidence = str(db_path), llm, min_confidence
        self.fallback_search = fallback_search
        with self._db() as db:
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(source UNINDEXED, text)")

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def ingest(self, source: str, text: str, *, chunk_chars: int = 1000) -> int:
        if not source or chunk_chars < 100:
            raise ValueError("source required and chunk_chars must be >= 100")
        chunks = [text[i:i + chunk_chars] for i in range(0, len(text), chunk_chars) if text[i:i + chunk_chars].strip()]
        with self._db() as db:
            db.execute("DELETE FROM passages WHERE source=?", (source,))
            db.executemany("INSERT INTO passages(source,text) VALUES (?,?)", [(source, chunk) for chunk in chunks])
        return len(chunks)

    def retrieve(self, query: str, limit: int = 5) -> list[Passage]:
        tokens = [t for t in query.split() if any(c.isalnum() for c in t)]
        expression = " OR ".join('"' + ''.join(c for c in token if c.isalnum()) + '"' for token in tokens[:12])
        if not expression:
            return []
        with self._db() as db:
            rows = db.execute("SELECT rowid, source, text, bm25(passages) FROM passages WHERE passages MATCH ? ORDER BY bm25(passages) LIMIT ?", (expression, limit)).fetchall()
        return [Passage(*row) for row in rows]

    def ask(self, query: str, *, limit: int = 5, _fallback_used: bool = False) -> Answer:
        passages = self.retrieve(query, limit)
        if not passages:
            if self.fallback_search and not _fallback_used:
                for source, text in self.fallback_search(query):
                    self.ingest(source, text)
                return self.ask(query, limit=limit, _fallback_used=True)
            return Answer("I could not find relevant source material.", (), 0.0, False)
        context = "\n".join(f"[{p.id}] {p.source}: {p.text}" for p in passages)
        raw = self.llm.complete([
            {"role": "system", "content": "Answer only from supplied passages. Return JSON with keys answer, evidence (array of {id: integer, quote: exact supporting substring}), confidence (0 to 1). If unsupported, say so and use no evidence."},
            {"role": "user", "content": f"Question: {query}\nPassages:\n{context}"},
        ])
        try:
            data = json.loads(raw)
            evidence = data["evidence"]
            confidence = float(data["confidence"])
            by_id = {p.id: p for p in passages}
            ids = [item["id"] for item in evidence]
            selected = tuple(by_id[i] for i in ids)
            grounded = bool(selected) and len(selected) == len(set(ids)) and all(item["quote"].strip() and item["quote"] in by_id[item["id"]].text for item in evidence) and self.min_confidence <= confidence <= 1
            if grounded:
                return Answer(str(data["answer"]), selected, confidence, True)
        except (ValueError, TypeError, KeyError):
            pass
        if self.fallback_search and not _fallback_used:
            for source, text in self.fallback_search(query):
                self.ingest(source, text)
            return self.ask(query, limit=limit, _fallback_used=True)
        return Answer("The available sources do not support a confident answer.", (), 0.0, False)
