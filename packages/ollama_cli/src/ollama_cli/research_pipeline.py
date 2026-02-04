"""Deep research pipeline.

This module provides a small, self-contained research flow that:
- plans a handful of search queries
- gathers sources via SearxNG (web_search)
- opens and extracts text from top sources
- synthesizes a cited report with an Ollama model

It is designed to be used from both the interactive shell and a CLI subcommand.
"""

import json
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

from .client import OllamaClient
from .config import DEFAULT_SEARXNG_URL
from .tools.kiwix_tools import KiwixTools
from .tools.web_tools import WebTools


_CODE_BLOCK = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def normalize_query(q: str) -> str:
    q = (q or "").strip()
    q = re.sub(r"\s+", " ", q)
    q = q.rstrip(".!?;:,")
    return q


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _query_tokens(q: str) -> List[str]:
    tokens: List[str] = []
    seen = set()
    for t in re.findall(r"[A-Za-z0-9]+", (q or "").lower()):
        if len(t) < 3:
            continue
        if t in seen:
            continue
        seen.add(t)
        tokens.append(t)
    return tokens


def _keyword_overlap_score(tokens: List[str], title: str, snippet: str) -> int:
    if not tokens:
        return 0
    hay = f"{title} {snippet}".lower()
    score = 0
    for t in tokens:
        if t in hay:
            score += 1
    # Weight title matches a bit higher.
    title_l = (title or "").lower()
    for t in tokens:
        if t in title_l:
            score += 1
    return score


def _shrink_opened_doc(doc: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    out = dict(doc)
    content = out.get("content")
    if isinstance(content, str) and max_chars > 0 and len(content) > max_chars:
        out["content"] = content[:max_chars]
        out["truncated"] = True
        out["size"] = len(out["content"])
    return out


def _sources_digest(
    *,
    query: str,
    sources: List[Dict[str, Any]],
    opened: List[Dict[str, Any]],
    reason: str,
) -> str:
    lines: List[str] = []
    lines.append("Synthesis failed (timeout/context/model error). Showing retrieved sources instead.")
    lines.append(reason)
    lines.append("")
    lines.append(f"Query: {query}")
    lines.append("")

    opened_urls: set[str] = set()
    for d in opened:
        u = d.get("url")
        if isinstance(u, str) and u:
            opened_urls.add(u)

    shown = 0
    for s in sources:
        url = s.get("url", "")
        if not isinstance(url, str) or not url:
            continue
        if opened_urls and url not in opened_urls:
            continue
        title = s.get("title", "")
        if not isinstance(title, str):
            title = str(title or "")
        snippet = s.get("snippet", "")
        if not isinstance(snippet, str):
            snippet = str(snippet or "")
        shown += 1
        lines.append(f"{shown}. {title} - {url}")
        if snippet:
            lines.append(f"   {snippet[:256]}")

    if shown == 0:
        lines.append("No sources opened.")

    return "\n".join(lines)


@dataclass
class ResearchPreset:
    """Budgets and knobs for research."""

    name: str
    max_planned_queries: int
    results_per_query: int
    max_sources_open: int
    max_source_chars: int
    recency_days: int


PRESETS: Dict[str, ResearchPreset] = {
    "quick": ResearchPreset(
        name="quick",
        max_planned_queries=2,
        results_per_query=6,
        max_sources_open=5,
        max_source_chars=6000,
        recency_days=365,
    ),
    "standard": ResearchPreset(
        name="standard",
        max_planned_queries=4,
        results_per_query=10,
        max_sources_open=10,
        max_source_chars=9000,
        recency_days=365,
    ),
    "deep": ResearchPreset(
        name="deep",
        max_planned_queries=7,
        results_per_query=15,
        max_sources_open=16,
        max_source_chars=12000,
        recency_days=365,
    ),
}


def _safe_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON extraction from raw model output."""
    s = (text or "").strip()
    if not s:
        return None

    # Direct parse
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else None
    except Exception:
        pass

    # Code block parse
    for m in _CODE_BLOCK.finditer(s):
        try:
            data = json.loads(m.group(1))
            return data if isinstance(data, dict) else None
        except Exception:
            continue

    return None


def _chat_once(
    client: OllamaClient,
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run a single non-streaming chat call and return the response dict."""
    # OllamaClient.chat returns an iterator; for non-stream it yields exactly one object.
    out: Dict[str, Any] = {}
    for chunk in client.chat(messages, model, stream=False, options=options):
        out = chunk
    return out


def _content_from_chat_response(resp: Dict[str, Any]) -> str:
    msg = resp.get("message", {}) or {}
    return msg.get("content") or ""


def plan_queries(
    client: OllamaClient,
    model: str,
    query: str,
    preset: ResearchPreset,
) -> Tuple[List[str], List[str]]:
    """Ask the model for a small plan: search queries + subquestions."""
    system = (
        "You are a research planner. Output ONLY valid JSON. "
        "Return an object with keys: search_queries (array of strings), subquestions (array of strings). "
        "Keep search_queries concise and specific."
    )
    user = {
        "query": query,
        "max_search_queries": preset.max_planned_queries,
        "notes": "Prefer authoritative sources. Include at least one query targeting official docs/specs if relevant.",
    }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
    resp = _chat_once(client, model, messages, options={"temperature": 0.2})
    data = _safe_json_from_text(_content_from_chat_response(resp)) or {}

    raw_queries = data.get("search_queries", [])
    raw_subq = data.get("subquestions", [])

    queries: List[str] = []
    if isinstance(raw_queries, list):
        for q in raw_queries:
            if isinstance(q, str):
                q = q.strip()
                if q and q not in queries:
                    queries.append(q)

    subquestions: List[str] = []
    if isinstance(raw_subq, list):
        for sq in raw_subq:
            if isinstance(sq, str):
                sq = sq.strip()
                if sq and sq not in subquestions:
                    subquestions.append(sq)

    if not queries:
        queries = [query]

    return queries[: preset.max_planned_queries], subquestions[: max(0, preset.max_planned_queries * 2)]


def run_deep_research(
    *,
    client: OllamaClient,
    model: str,
    query: str,
    preset_name: str = "standard",
    seed_urls: Optional[List[str]] = None,
    searxng_url: Optional[str] = None,
    kiwix_url: Optional[str] = None,
) -> str:
    """Run a bounded deep research pass and return a cited report."""
    raw_query = query
    query = normalize_query(query)
    if not query:
        query = (raw_query or "").strip()

    preset = PRESETS.get(preset_name, PRESETS["standard"])
    web = WebTools(searxng_url=searxng_url or DEFAULT_SEARXNG_URL)

    kiwix: Optional[KiwixTools] = None
    offline_zims: List[str] = []
    if kiwix_url:
        kt = KiwixTools(kiwix_url=kiwix_url)
        if kt.ping():
            kiwix = kt

    started_at = time.time()
    planned_queries, subquestions = plan_queries(client, model, query, preset)

    q_tokens = _query_tokens(query)

    # Pick offline books (ZIM ids) to search.
    if kiwix and not seed_urls:
        # Offline budget: keep this small to avoid swamping the run.
        max_offline_zims = 2 if preset.name == "quick" else (4 if preset.name == "standard" else 6)

        # Search catalog by a few useful terms.
        terms: List[str] = []
        terms.append(query)
        terms.extend(planned_queries)
        for token in re.findall(r"[A-Za-z0-9]{4,}", query.lower()):
            if token not in terms:
                terms.append(token)
        # Always attempt to include Wikipedia when present.
        terms.insert(0, "wikipedia")

        scores: Dict[str, int] = {}
        for t in terms[:8]:
            try:
                books = kiwix.catalog_search_books(t, count=12)
            except Exception:
                continue
            for b in books:
                zim_id = str(b.get("zim_id") or "").strip()
                if not zim_id:
                    continue
                title = str(b.get("title") or "").lower()
                inc = 1
                if "wikipedia" in zim_id.lower() or "wikipedia" in title:
                    inc += 3
                if t.lower() in title:
                    inc += 2
                scores[zim_id] = scores.get(zim_id, 0) + inc

        offline_zims = [z for z, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))][:max_offline_zims]

    # Gather candidate URLs
    urls: List[str] = []
    sources: List[Dict[str, Any]] = []

    # Gather offline sources first when Kiwix is available.
    if kiwix and not seed_urls:
        # Prefer a library-wide search first so we can use all available docs.
        for q in planned_queries:
            try:
                rows = kiwix.search_rss(q, zim=None, count=preset.results_per_query, start=0)
            except Exception:
                rows = []

            for row in rows:
                zim = str(row.get("zim") or "").strip()
                path = str(row.get("path") or "").strip()
                title = str(row.get("title") or "").strip()
                snippet = str(row.get("snippet") or "").strip()
                if not zim or not path or not title:
                    continue

                safe_path = quote(path.lstrip("/"), safe="/-._~")
                u = f"{kiwix.kiwix_url}/content/{zim}/{safe_path}"
                if u not in urls:
                    urls.append(u)
                    sources.append(
                        {
                            "title": title,
                            "url": u,
                            "snippet": snippet,
                            "backend": "kiwix",
                            "zim": zim,
                            "path": path,
                        }
                    )
                if len(urls) >= preset.max_sources_open:
                    break
            if len(urls) >= preset.max_sources_open:
                break

        # Fallback: search a short list of relevant ZIMs from the catalog.
        if not urls and offline_zims:
            per_zim = max(2, min(6, preset.results_per_query // max(1, len(offline_zims))))
            for q in planned_queries:
                for zim in offline_zims:
                    try:
                        offline = kiwix.search_xml(q, zim, count=per_zim, start=0)
                    except Exception:
                        offline = []
                    for r in offline:
                        if not r.url:
                            continue
                        safe_path = quote(r.url.lstrip("/"), safe="/-._~")
                        u = f"{kiwix.kiwix_url}/content/{zim}/{safe_path}"
                        if u not in urls:
                            urls.append(u)
                            sources.append(
                                {
                                    "title": r.title,
                                    "url": u,
                                    "snippet": r.snippet,
                                    "backend": "kiwix",
                                    "zim": zim,
                                    "path": r.url,
                                }
                            )
                    if len(urls) >= preset.max_sources_open:
                        break
                if len(urls) >= preset.max_sources_open:
                    break

    if seed_urls:
        for u in seed_urls:
            u = (u or "").strip()
            if u and u not in urls:
                urls.append(u)
                sources.append({"title": u, "url": u, "snippet": "", "backend": "seed"})
    else:
        if len(urls) < preset.max_sources_open:
            for q in planned_queries:
                results = web.search(q, count=preset.results_per_query, recency_days=preset.recency_days)
                for r in results:
                    if r.url and r.url not in urls:
                        urls.append(r.url)
                        sources.append({"title": r.title, "url": r.url, "snippet": r.snippet, "backend": "web"})
                if len(urls) >= preset.max_sources_open:
                    break

    # Prefer on-topic sources first (simple overlap) while preserving offline-first priority.
    if sources:
        offline_sources = [s for s in sources if s.get("backend") == "kiwix"]
        web_sources = [s for s in sources if s.get("backend") != "kiwix"]

        def _score(s: Dict[str, Any]) -> int:
            return _keyword_overlap_score(
                q_tokens,
                str(s.get("title") or ""),
                str(s.get("snippet") or ""),
            )

        offline_sources.sort(key=lambda s: (-_score(s), str(s.get("title") or "")))
        web_sources.sort(key=lambda s: (-_score(s), str(s.get("title") or "")))
        sources = offline_sources + web_sources
        urls = [str(s.get("url") or "") for s in sources if s.get("url")]

    # Open sources
    opened: List[Dict[str, Any]] = []
    for u in urls[: preset.max_sources_open]:
        # Prefer offline open when the URL is a kiwix content URL.
        if kiwix and u.startswith(f"{kiwix.kiwix_url}/content/"):
            try:
                rest = u.split(f"{kiwix.kiwix_url}/content/", 1)[1]
                parts = rest.split("/", 1)
                if len(parts) == 2:
                    zim = parts[0]
                    path = unquote(parts[1])
                    raw = kiwix.open_raw(zim, path, max_chars=preset.max_source_chars)
                    opened.append(raw)
                    continue
            except Exception:
                # Fall back to web open if possible
                pass

        try:
            opened_doc = web.open_url(u, mode="auto", max_chars=preset.max_source_chars)
        except Exception:
            continue
        opened.append(opened_doc)

    if not opened:
        raise RuntimeError(
            "No sources could be fetched/opened. "
            "If using web search, verify your SearxNG instance and SEARXNG_URL. "
            "Alternatively, provide seed URLs."
        )

    # Align sources to opened docs for synthesis and citations.
    source_by_url: Dict[str, Dict[str, Any]] = {}
    for s in sources:
        src_url = s.get("url")
        if isinstance(src_url, str) and src_url and src_url not in source_by_url:
            source_by_url[src_url] = s

    opened_sources: List[Dict[str, Any]] = []
    opened_ordered: List[Dict[str, Any]] = []
    for d in opened:
        opened_url = d.get("url")
        if not isinstance(opened_url, str) or not opened_url:
            continue
        opened_ordered.append(d)
        opened_sources.append(
            source_by_url.get(opened_url, {"title": opened_url, "url": opened_url, "snippet": ""})
        )
    opened = opened_ordered

    offline_opened = sum(1 for s in opened_sources if s.get("backend") == "kiwix")
    web_opened = sum(1 for s in opened_sources if s.get("backend") != "kiwix")
    if offline_opened and not web_opened:
        _progress(f"Found {offline_opened} offline sources (Kiwix). Synthesizing...")
    elif offline_opened:
        _progress(f"Found {offline_opened} offline sources (Kiwix) and {web_opened} web sources. Synthesizing...")
    else:
        _progress(f"Found {len(opened_sources)} sources. Synthesizing...")

    # Build report prompt
    packet = {
        "query": query,
        "subquestions": subquestions,
        "planned_queries": planned_queries,
        "sources": opened_sources,
        "opened": opened,
        "elapsed_s": round(time.time() - started_at, 2),
        "instructions": {
            "citation_style": "Use inline bracket citations like [1], [2] referencing the numbered Sources list you include at the end.",
            "be_explicit_about_uncertainty": True,
            "prefer_primary_sources": True,
        },
    }

    system = (
        "You are a deep research assistant. Write a concise, high-signal report with citations. "
        "Use only the provided sources. If evidence is weak or conflicting, say so. "
        "End with a 'Sources' section listing numbered sources with title and URL."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
    ]
    def _synthesize(pkt: Dict[str, Any], temperature: float) -> str:
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(pkt, ensure_ascii=False)},
        ]
        resp = _chat_once(client, model, msgs, options={"temperature": temperature})
        text = _content_from_chat_response(resp).strip()
        if not text:
            raise RuntimeError("empty model response")
        return text

    try:
        return _synthesize(packet, temperature=0.3)
    except Exception as e1:
        _progress(f"Synthesis failed: {type(e1).__name__}: {e1}. Retrying with smaller context...")

        retry_max_sources_open = min(4, max(2, len(opened_sources) // 2))
        retry_max_source_chars = min(3000, preset.max_source_chars)

        ranked: List[Tuple[int, int, Dict[str, Any], Dict[str, Any]]] = []
        for i, (s, d) in enumerate(zip(opened_sources, opened)):
            score = _keyword_overlap_score(q_tokens, str(s.get("title") or ""), str(s.get("snippet") or ""))
            ranked.append((score, -i, s, d))
        ranked.sort(key=lambda t: (-t[0], -t[1]))

        small_sources: List[Dict[str, Any]] = []
        small_opened: List[Dict[str, Any]] = []
        for _, _, s, d in ranked[:retry_max_sources_open]:
            small_sources.append(s)
            small_opened.append(_shrink_opened_doc(d, max_chars=retry_max_source_chars))

        packet_small = dict(packet)
        packet_small["opened"] = small_opened
        packet_small["sources"] = small_sources
        q_obj = packet_small.get("query")
        q_str = q_obj if isinstance(q_obj, str) else ""
        packet_small["query"] = normalize_query(q_str)

        try:
            return _synthesize(packet_small, temperature=0.2)
        except Exception as e2:
            _progress(f"Synthesis failed again: {type(e2).__name__}: {e2}. Showing sources list.")
            reason = (
                f"Primary error: {type(e1).__name__}: {e1} | "
                f"Retry error: {type(e2).__name__}: {e2}"
            )
            return _sources_digest(query=query, sources=opened_sources, opened=opened, reason=reason)
