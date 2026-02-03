from __future__ import annotations

import json
from typing import Any

import httpx

from .. import config


def _json_obj_from_text(text: str, *, max_size: int) -> Any:
    s = (text or "")
    if not s or len(s) > max_size:
        return None

    for i, ch in enumerate(s):
        if ch != "{":
            continue
        depth = 0
        in_string = False
        escape_next = False
        for j in range(i, min(len(s), i + max_size)):
            c = s[j]
            if escape_next:
                escape_next = False
                continue
            if c == "\\":
                escape_next = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    snippet = s[i : j + 1]
                    try:
                        return json.loads(snippet)
                    except json.JSONDecodeError:
                        return None
        return None
    return None


async def route_rag(
    *,
    http: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    query: str,
    defaults: dict[str, Any],
    timeout: float = 12.0,
) -> dict[str, Any]:
    """Best-effort router for choosing sources + rewriting queries.

    Returns a dict containing:
    - use_docs/use_web/use_kiwix
    - doc_group/doc_source
    - doc_query/web_query/kiwix_query
    """
    q = (query or "").strip()
    if not q:
        return dict(defaults)

    prompt = (
        "Return ONLY JSON.\n"
        "Schema:\n"
        "{\n"
        '  "use_docs": true|false,\n'
        '  "use_web": true|false,\n'
        '  "use_kiwix": true|false,\n'
        '  "doc_group": string|null,\n'
        '  "doc_source": string|null,\n'
        '  "doc_query": string|null,\n'
        '  "web_query": string|null,\n'
        '  "kiwix_query": string|null\n'
        "}\n\n"
        "Guidance:\n"
        "- Use docs for user-uploaded files / epubs.\n"
        "- Use kiwix for offline encyclopedia-style lookups.\n"
        "- Use web only if the answer likely needs current info.\n"
        "- doc_group can be 'epub' when the question is about books; otherwise null.\n"
        "- If you rewrite queries, keep them short and keyword-focused.\n\n"
        f"User question:\n{q}\n"
    )

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    try:
        r = await http.post(f"{ollama_url}/api/chat", json=payload, timeout=timeout)
        r.raise_for_status()
        content = ((r.json().get("message") or {}).get("content") or "").strip()
    except Exception:
        return dict(defaults)

    obj = _json_obj_from_text(content, max_size=int(config.config.max_json_parse_size))
    if not isinstance(obj, dict):
        return dict(defaults)

    out = dict(defaults)

    for key in ("use_docs", "use_web", "use_kiwix"):
        if isinstance(obj.get(key), bool):
            out[key] = bool(obj.get(key))

    for key in ("doc_group", "doc_source", "doc_query", "web_query", "kiwix_query"):
        val = obj.get(key)
        if isinstance(val, str):
            v = val.strip()
            out[key] = v if v else None
        elif val is None:
            out[key] = None

    return out
