from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
    def __init__(
        self,
        db_path: str | Path,
        llm: LLM,
        *,
        min_confidence: float = 0.55,
        fallback_search: Callable[[str], list[tuple[str, str]]] | None = None,
    ):
        self.db_path, self.llm, self.min_confidence = str(db_path), llm, min_confidence
        self.fallback_search = fallback_search
        with self._db() as db:
            db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(source UNINDEXED, text)"
            )

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def ingest(
        self,
        source: str,
        text: str,
        *,
        chunk_chars: int = 1000,
        overlap_chars: int = 100,
    ) -> int:
        if not source or chunk_chars < 100 or not 0 <= overlap_chars < chunk_chars:
            raise ValueError(
                "source required, chunk_chars >= 100, and overlap_chars < chunk_chars"
            )
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_chars, len(text))
            if text[start:end].strip():
                chunks.append(text[start:end])
            if end == len(text):
                break
            start = end - overlap_chars
        with self._db() as db:
            db.execute("DELETE FROM passages WHERE source=?", (source,))
            db.executemany(
                "INSERT INTO passages(source,text) VALUES (?,?)",
                [(source, chunk) for chunk in chunks],
            )
        return len(chunks)

    def ingest_file(self, path: str | Path, *, max_bytes: int = 5_000_000) -> int:
        path = Path(path)
        if path.stat().st_size > max_bytes:
            raise ValueError("file exceeds configured size limit")
        return self.ingest(str(path.resolve()), path.read_text(encoding="utf-8"))

    def sources(self) -> list[tuple[str, int]]:
        with self._db() as db:
            return db.execute(
                "SELECT source,count(*) FROM passages GROUP BY source ORDER BY source"
            ).fetchall()

    def delete_source(self, source: str) -> int:
        with self._db() as db:
            count = db.execute(
                "SELECT count(*) FROM passages WHERE source=?", (source,)
            ).fetchone()[0]
            db.execute("DELETE FROM passages WHERE source=?", (source,))
        return count

    def retrieve(self, query: str, limit: int = 5) -> list[Passage]:
        tokens = [t for t in query.split() if any(c.isalnum() for c in t)]
        expression = " OR ".join(
            '"' + "".join(c for c in token if c.isalnum()) + '"'
            for token in tokens[:12]
        )
        if not expression:
            return []
        with self._db() as db:
            rows = db.execute(
                "SELECT rowid, source, text, bm25(passages) FROM passages WHERE passages MATCH ? ORDER BY bm25(passages) LIMIT ?",
                (expression, limit),
            ).fetchall()
        return [Passage(*row) for row in rows]

    def ask(
        self, query: str, *, limit: int = 5, _fallback_used: bool = False
    ) -> Answer:
        passages = self.retrieve(query, limit)
        if not passages:
            if self.fallback_search and not _fallback_used:
                for source, text in self.fallback_search(query):
                    self.ingest(source, text)
                return self.ask(query, limit=limit, _fallback_used=True)
            return Answer("I could not find relevant source material.", (), 0.0, False)
        context = "\n".join(
            f"[{p.id}] Source: {p.source}\nText: {p.text}\nEnd text." for p in passages
        )
        from .grounding import validated_answer

        messages = [
            {
                "role": "system",
                "content": "Answer only from supplied passages. Return only a JSON object with keys answer, evidence (array of {id: integer, quote: exact supporting substring of that passage's Text field}), confidence (0 to 1). Do not include Source labels, passage IDs, or Text labels in quotes. If unsupported, say so and use no evidence.",
            },
            {"role": "user", "content": f"Question: {query}\nPassages:\n{context}"},
        ]
        for attempt in range(2):
            raw = self.llm.complete(messages)
            answer = validated_answer(raw, passages, self.min_confidence)
            if answer:
                return answer
            if attempt == 0:
                messages.extend(
                    [
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": "The answer failed citation validation. Retry with JSON only. Each evidence quote must be copied character-for-character from the cited passage's Text field, without Source or Text labels. If no passage supports the answer, use an empty evidence array.",
                        },
                    ]
                )
        if self.fallback_search and not _fallback_used:
            for source, text in self.fallback_search(query):
                self.ingest(source, text)
            return self.ask(query, limit=limit, _fallback_used=True)
        return Answer(
            "The available sources do not support a confident answer.", (), 0.0, False
        )
