import json
from typing import Any, Dict, List, Optional, Tuple, cast

import pytest

from ollama_cli.client import OllamaClient
from ollama_cli import research_pipeline


def test_normalize_query_strips_trailing_punctuation() -> None:
    assert research_pipeline.normalize_query("Example Query.  ") == "Example Query"
    assert research_pipeline.normalize_query("  Example Query?!") == "Example Query"


class _FakeWebTools:
    def __init__(self, searxng_url: str):
        self.searxng_url = searxng_url

    def search(self, *args: Any, **kwargs: Any) -> List[Any]:
        raise AssertionError("web search should not be called when offline results fill the budget")

    def open_url(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise AssertionError("web open should not be called in this test")


class _FakeKiwixTools:
    def __init__(self, kiwix_url: str):
        self.kiwix_url = kiwix_url.rstrip("/")

    def ping(self) -> bool:
        return True

    def catalog_search_books(self, query: str, count: int = 10) -> List[Dict[str, Any]]:
        return []

    def search_rss(self, query: str, zim: Optional[str], count: int = 8, start: int = 0) -> List[Dict[str, Any]]:
        # Provide enough library-wide results to fill the standard preset.
        out: List[Dict[str, Any]] = []
        for i in range(20):
            out.append(
                {
                    "title": f"Example topic {i}",
                    "zim": "wikipedia_en_all_nopic_2025-12",
                    "path": f"Example_topic_{i}",
                    "snippet": "Example topic overview and details",
                }
            )
        return out

    def open_raw(self, zim: str, path: str, max_chars: int = 12000) -> Dict[str, Any]:
        # Return content longer than the retry max so we can assert truncation.
        content = ("x" * 4000)
        url = f"{self.kiwix_url}/content/{zim}/{path}"
        return {
            "zim": zim,
            "path": path,
            "url": url,
            "content_type": "text/html",
            "content": content,
            "size": len(content),
            "truncated": False,
        }


def test_synthesis_retry_reduces_packet(monkeypatch: Any) -> None:
    monkeypatch.setattr(research_pipeline, "WebTools", _FakeWebTools)
    monkeypatch.setattr(research_pipeline, "KiwixTools", _FakeKiwixTools)

    # Skip real planning.
    def fake_plan_queries(*args: Any, **kwargs: Any) -> Tuple[List[str], List[str]]:
        return (["Example Topic."], [])

    monkeypatch.setattr(research_pipeline, "plan_queries", fake_plan_queries)

    packets: List[Dict[str, Any]] = []

    def fake_chat_once(client: Any, model: str, messages: List[Dict[str, Any]], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pkt = json.loads(messages[1]["content"])
        packets.append(pkt)
        if len(packets) == 1:
            raise RuntimeError("context too large")
        return {"message": {"content": "ok"}}

    monkeypatch.setattr(research_pipeline, "_chat_once", fake_chat_once)

    dummy_client = cast(OllamaClient, object())
    out = research_pipeline.run_deep_research(
        client=dummy_client,
        model="fake",
        query="Example Topic.",
        preset_name="standard",
        searxng_url="http://localhost:8080/search",
        kiwix_url="http://127.0.0.1:8081",
    )
    assert out == "ok"
    assert len(packets) == 2

    first = packets[0]
    second = packets[1]

    assert first["query"] == "Example Topic"
    assert second["query"] == "Example Topic"

    assert len(first["opened"]) == 10
    assert len(second["opened"]) <= 4
    assert len(second["sources"]) == len(second["opened"])

    for d in second["opened"]:
        assert len(d["content"]) <= 3000


def test_synthesis_failure_returns_digest_with_errors(monkeypatch: Any) -> None:
    monkeypatch.setattr(research_pipeline, "WebTools", _FakeWebTools)
    monkeypatch.setattr(research_pipeline, "KiwixTools", _FakeKiwixTools)

    monkeypatch.setattr(research_pipeline, "plan_queries", lambda *a, **k: (["Example topic"], []))

    def always_fail(client: Any, model: str, messages: List[Dict[str, Any]], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise TimeoutError("boom")

    monkeypatch.setattr(research_pipeline, "_chat_once", always_fail)

    dummy_client = cast(OllamaClient, object())
    out = research_pipeline.run_deep_research(
        client=dummy_client,
        model="fake",
        query="Example Topic.",
        preset_name="standard",
        searxng_url="http://localhost:8080/search",
        kiwix_url="http://127.0.0.1:8081",
    )

    assert "Synthesis failed" in out
    assert "Primary error" in out
    assert "Retry error" in out
    assert "TimeoutError" in out
