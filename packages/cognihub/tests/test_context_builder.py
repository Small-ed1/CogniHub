from cognihub.services.context import build_context
from cognihub.services.retrieval import RetrievalResult


def test_build_context_caps_and_dedupe():
    results = [
        RetrievalResult(
            source_type="doc",
            ref_id="doc:1",
            chunk_id=1,
            title="doc-a.txt",
            url=None,
            domain=None,
            score=0.9,
            text="alpha",
            meta={"doc_id": 1, "chunk_index": 0},
        ),
        RetrievalResult(
            source_type="doc",
            ref_id="doc:2",
            chunk_id=2,
            title="doc-b.txt",
            url=None,
            domain=None,
            score=0.8,
            text="alpha",
            meta={"doc_id": 2, "chunk_index": 0},
        ),
        RetrievalResult(
            source_type="web",
            ref_id="web:9",
            chunk_id=9,
            title="Example",
            url="https://example.com",
            domain="example.com",
            score=0.7,
            text="bravo",
            meta={"page_id": 1, "chunk_index": 0},
        ),
    ]

    sources, context = build_context(results, max_chars=5000, per_source_cap=1)

    assert len(sources) == 2
    assert "[D1]" in context[0]
    assert "[W1]" in context[1]
    assert sources[0]["citation"] == "D1"
    assert sources[0]["filename"] == "doc-a.txt"
