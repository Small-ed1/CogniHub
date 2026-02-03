from __future__ import annotations

import json
from typing import Any

import httpx

from .retrieval import RetrievalResult


def _extract_json_array(text: str) -> list[Any] | None:
    s = (text or "").strip()
    if not s:
        return None
    start = s.find("[")
    end = s.rfind("]")
    if start < 0 or end < 0 or end <= start:
        return None
    snippet = s[start : end + 1]
    try:
        val = json.loads(snippet)
    except Exception:
        return None
    return val if isinstance(val, list) else None


async def rerank_results(
    *,
    http: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    query: str,
    results: list[RetrievalResult],
    keep_n: int,
    timeout: float = 20.0,
) -> list[RetrievalResult]:
    """LLM rerank for better precision.

    Best-effort; falls back to original order on any failure.
    """
    if not results:
        return []
    keep_n = max(1, min(int(keep_n), len(results)))

    candidates = results[:keep_n]
    items: list[dict[str, Any]] = []
    for idx, r in enumerate(candidates, start=1):
        items.append(
            {
                "id": idx,
                "source_type": r.source_type,
                "title": r.title,
                "url": r.url,
                "domain": r.domain,
                "score": float(r.score),
                "text": (r.text or "")[:1200],
            }
        )

    prompt = (
        "You are reranking retrieval candidates for a RAG assistant.\n"
        "Return ONLY JSON: a list of integer ids in best-to-worst order.\n"
        "Rules:\n"
        "- Prefer items that directly answer the user question.\n"
        "- Prefer specific, factual passages.\n"
        "- Deprioritize generic boilerplate or unrelated text.\n\n"
        f"User question:\n{(query or '').strip()}\n\n"
        "Candidates JSON:\n"
        + json.dumps(items, ensure_ascii=False)
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a careful ranking engine."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }

    try:
        resp = await http.post(f"{ollama_url}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        content = ((resp.json().get("message") or {}).get("content") or "").strip()
    except Exception:
        return results

    order = _extract_json_array(content)
    if not order:
        return results

    picked: list[RetrievalResult] = []
    seen: set[int] = set()
    by_id = {i: r for i, r in enumerate(candidates, start=1)}
    for x in order:
        try:
            i = int(x)
        except Exception:
            continue
        if i in seen:
            continue
        r = by_id.get(i)
        if r is None:
            continue
        picked.append(r)
        seen.add(i)

    if not picked:
        return results

    for i, r in enumerate(candidates, start=1):
        if i not in seen:
            picked.append(r)

    return picked + results[keep_n:]
