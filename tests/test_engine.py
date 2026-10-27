from citation_grounded_rag.engine import CitationRAG


class Stub:
    def __init__(self, answer):
        self.answer = answer

    def complete(self, messages, *, model=None):
        return self.answer


def test_grounded_answer(tmp_path):
    rag = CitationRAG(tmp_path / "rag.db", Stub(""))
    rag.ingest("handbook", "The support hours are 9 to 5 on weekdays.")
    passage = rag.retrieve("support hours")[0]
    rag.llm = Stub(
        '{"answer":"9 to 5 on weekdays","evidence":[{"id":'
        + str(passage.id)
        + ',"quote":"9 to 5 on weekdays"}],"confidence":0.9}'
    )
    answer = rag.ask("What are the support hours?")
    assert answer.grounded and answer.citations[0].source == "handbook"


def test_rejects_fabricated_citation(tmp_path):
    rag = CitationRAG(
        tmp_path / "rag.db",
        Stub(
            '{"answer":"Always open","evidence":[{"id":999,"quote":"always"}],"confidence":1}'
        ),
    )
    rag.ingest("handbook", "Support hours are 9 to 5.")
    assert not rag.ask("support hours").grounded


def test_fallback_search_populates_index(tmp_path):
    queries = []

    def fallback(query):
        queries.append(query)
        return [("search-result", "The policy allows refunds within 30 days.")]

    rag = CitationRAG(tmp_path / "rag.db", Stub("{}"), fallback_search=fallback)
    rag.ask("refunds policy")
    assert queries == ["refunds policy"]
    assert rag.retrieve("refunds")[0].source == "search-result"


def test_overlapping_ingestion_and_source_replacement(tmp_path):
    rag = CitationRAG(tmp_path / "rag.db", Stub("{}"))
    count = rag.ingest(
        "manual", "a" * 150 + " refund " + "b" * 150, chunk_chars=120, overlap_chars=30
    )
    assert count > 2 and rag.sources() == [("manual", count)]
    rag.ingest("manual", "Replacement policy text.")
    assert rag.sources() == [("manual", 1)]
    assert rag.delete_source("manual") == 1 and rag.sources() == []
