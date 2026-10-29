import json
import re

from citation_grounded_rag.__main__ import main


def test_cli_indexes_searches_and_deletes(tmp_path, capsys):
    document = tmp_path / "policy.txt"
    document.write_text("Refunds are available within thirty days.", encoding="utf-8")
    db = tmp_path / "knowledge.sqlite3"
    assert main(["--db", str(db), "ingest", str(document)]) == 0
    assert json.loads(capsys.readouterr().out)["chunks"] == 1
    assert main(["--db", str(db), "search", "Refunds"]) == 0
    matches = json.loads(capsys.readouterr().out)
    assert matches[0]["source"] == str(document.resolve())
    assert main(["--db", str(db), "delete", str(document.resolve())]) == 0
    assert json.loads(capsys.readouterr().out)["deleted_chunks"] == 1


def test_cli_asks_with_verified_source_quote(tmp_path, capsys, monkeypatch):
    class FakeLLM:
        def complete(self, messages, *, model=None):
            passage_id = int(re.search(r"\[(\d+)\]", messages[1]["content"]).group(1))
            return json.dumps(
                {
                    "answer": "Within 30 days.",
                    "evidence": [{"id": passage_id, "quote": "Refunds within 30 days"}],
                    "confidence": 0.9,
                }
            )

    monkeypatch.setattr(
        "citation_grounded_rag.__main__.OpenAICompatibleLLM.from_env",
        lambda: FakeLLM(),
    )
    db = tmp_path / "knowledge.sqlite3"
    main(["--db", str(db), "ingest-text", "policy", "Refunds within 30 days"])
    capsys.readouterr()
    assert main(["--db", str(db), "ask", "Refunds"]) == 0
    assert json.loads(capsys.readouterr().out)["grounded"] is True
