"""Command line interface for an on-disk cited knowledge base."""

from __future__ import annotations

import argparse
import json

from .engine import CitationRAG
from .llm import OpenAICompatibleLLM
from .web import serve

WEB_ACTIONS = {
    "ingest-text": [
        ("source", "Source name", "text", True),
        ("text", "Document text", "textarea", True),
    ],
    "search": [("query", "Search terms", "text", True)],
    "ask": [("query", "Question", "text", True)],
    "sources": [],
    "delete": [("source", "Source name", "text", True)],
}


class _OfflineLLM:
    def complete(self, messages, *, model=None):
        raise RuntimeError("Set OPENAI_API_KEY before using the ask command")


def execute(command: str, values: dict, db_path: str) -> object:
    llm = OpenAICompatibleLLM.from_env() if command == "ask" else _OfflineLLM()
    rag = CitationRAG(db_path, llm)
    if command == "ingest":
        return {"chunks": rag.ingest_file(values["file"])}
    if command == "ingest-text":
        return {"chunks": rag.ingest(values["source"], values["text"])}
    if command == "search":
        return [
            p.__dict__
            for p in rag.retrieve(values["query"], int(values.get("limit", 5)))
        ]
    if command == "ask":
        answer = rag.ask(values["query"])
        return {
            "answer": answer.text,
            "grounded": answer.grounded,
            "confidence": answer.confidence,
            "citations": [p.__dict__ for p in answer.citations],
        }
    if command == "sources":
        return [{"source": source, "chunks": count} for source, count in rag.sources()]
    if command == "delete":
        return {"deleted_chunks": rag.delete_source(values["source"])}
    raise ValueError("unknown command")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index, search, and cite local text")
    parser.add_argument("--db", default="knowledge.sqlite3", help="SQLite index path")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Index a UTF-8 text file")
    ingest.add_argument("file")
    ingest_text = commands.add_parser("ingest-text", help="Index supplied text")
    ingest_text.add_argument("source")
    ingest_text.add_argument("text")
    search = commands.add_parser("search", help="Retrieve matching passages offline")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    ask = commands.add_parser("ask", help="Answer with verified citations using an LLM")
    ask.add_argument("query")
    commands.add_parser("sources", help="List indexed sources")
    delete = commands.add_parser("delete", help="Remove an indexed source")
    delete.add_argument("source")
    browser = commands.add_parser("serve", help="Start local browser interface")
    browser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve(
            "Citation Grounded RAG",
            WEB_ACTIONS,
            lambda action, values: execute(action, values, args.db),
            port=args.port,
        )
        return 0
    result = execute(args.command, vars(args), args.db)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
