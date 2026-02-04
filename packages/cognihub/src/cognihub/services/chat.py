from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncGenerator

import httpx

from .context import build_context, rag_system_prompt
from .models import ModelRegistry
from .retrieval import DocRetrievalProvider, KiwixRetrievalProvider, WebRetrievalProvider, RetrievalResult
from .rag_routing import route_rag
from .rerank import rerank_results
from .tooling import chat_with_tools
from .web_ingest import WebIngestQueue
from .hybrid_router import smart_chat, get_router


def _validate_messages(msgs: list[dict]) -> list[dict]:
    clean = []
    for m in msgs or []:
        role = (m.get("role") or "").strip()
        content = m.get("content")
        if role not in ("system", "user", "assistant"):
            continue
        if content is None:
            content = ""
        clean.append({"role": role, "content": str(content)})
    if not clean:
        raise ValueError("No valid messages")
    return clean


def _allowed_citations(sources_meta: list[dict]) -> set[str]:
    out: set[str] = set()
    for s in sources_meta or []:
        if not isinstance(s, dict):
            continue
        tag = s.get("citation")
        if isinstance(tag, str) and tag:
            out.add(tag)
    return out


def _has_any_citation(text: str, allowed: set[str]) -> bool:
    if not text or not allowed:
        return False
    for tag in allowed:
        if f"[{tag}]" in text:
            return True
    return False


async def _ollama_chat_once(
    *,
    http: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    messages: list[dict],
    options: dict | None,
    keep_alive: str | None,
    timeout: float,
) -> str:
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if options is not None:
        payload["options"] = options
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    r = await http.post(f"{ollama_url}/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    return ((r.json().get("message") or {}).get("content") or "").strip()


async def stream_chat(
    *,
    http: httpx.AsyncClient,
    model_registry: ModelRegistry,
    ollama_url: str,
    model: str,
    messages: list[dict],
    options: dict | None,
    keep_alive: str | None,
    rag: dict | None,
    embed_model: str,
    web_ingest: WebIngestQueue | None,
    kiwix_url: str | None,
    request=None,  # FastAPI request object for tool access
    chat_id: str | None = None,
    message_id: str | None = None,
) -> AsyncGenerator[str, None]:
    if not messages or not model:
        raise ValueError("Messages and model are required")

    await model_registry.validate_model(http, model)

    if len(messages) > 100:
        raise ValueError("Too many messages")

    total_chars = sum(len(m.get("content", "")) for m in messages)
    if total_chars > 100000:
        raise ValueError("Messages too long")

    clean_messages = _validate_messages(messages)
    rag = rag or {"enabled": False}

    sources_meta: list[dict] = []

    if rag.get("enabled"):
        yield json.dumps({"type": "status", "stage": "calling_tools"}) + "\n"
        last_user = next((m for m in reversed(clean_messages) if m["role"] == "user"), None)
        query = (last_user or {}).get("content", "")
        rag_embed_model = rag.get("embed_model") or embed_model

        # Backwards-compatible defaults: docs on, web/kiwix off.
        use_docs = bool(rag.get("use_docs", True))
        use_web = bool(rag.get("use_web", False))
        use_kiwix = bool(rag.get("use_kiwix", False))

        doc_group = rag.get("doc_group")
        doc_source = rag.get("doc_source")

        doc_query = query
        web_query = query
        kiwix_query = query

        if bool(rag.get("auto_route")):
            router_model = (
                rag.get("router_model")
                or os.getenv("RAG_ROUTER_MODEL")
                or os.getenv("DECIDER_MODEL")
                or model
            )
            router_timeout = float(rag.get("router_timeout_sec") or 12.0)
            routed = await route_rag(
                http=http,
                ollama_url=ollama_url,
                model=str(router_model),
                query=query,
                defaults={
                    "use_docs": use_docs,
                    "use_web": use_web,
                    "use_kiwix": use_kiwix,
                    "doc_group": doc_group,
                    "doc_source": doc_source,
                    "doc_query": None,
                    "web_query": None,
                    "kiwix_query": None,
                },
                timeout=router_timeout,
            )
            use_docs = bool(routed.get("use_docs"))
            use_web = bool(routed.get("use_web"))
            use_kiwix = bool(routed.get("use_kiwix"))
            doc_group = routed.get("doc_group") or doc_group
            doc_source = routed.get("doc_source") or doc_source
            doc_query = routed.get("doc_query") or query
            web_query = routed.get("web_query") or query
            kiwix_query = routed.get("kiwix_query") or query

        if use_kiwix and not kiwix_url:
            use_kiwix = False

        top_k_default = int(rag.get("top_k") or 12)
        doc_top_k = int(rag.get("doc_top_k") or top_k_default)
        web_top_k = int(rag.get("web_top_k") or top_k_default)
        kiwix_top_k = int(rag.get("kiwix_top_k") or top_k_default)

        doc_ids = rag.get("doc_ids")
        domain_whitelist = rag.get("domain_whitelist")

        # ranking knobs (doc retrieval only for now)
        use_mmr = rag.get("use_mmr")
        mmr_lambda = rag.get("mmr_lambda", 0.75)

        results: list[RetrievalResult] = []
        if use_docs:
            doc_provider = DocRetrievalProvider()
            results.extend(
                await doc_provider.retrieve(
                    doc_query,
                    top_k=doc_top_k,
                    doc_ids=doc_ids,
                    group_name=doc_group,
                    source=doc_source,
                    embed_model=rag_embed_model,
                    use_mmr=use_mmr,
                    mmr_lambda=mmr_lambda,
                )
            )

        if use_web:
            web_provider = WebRetrievalProvider()
            results.extend(
                await web_provider.retrieve(
                    web_query,
                    top_k=web_top_k,
                    embed_model=rag_embed_model,
                    domain_whitelist=domain_whitelist,
                )
            )

        if use_kiwix and kiwix_url:
            kiwix_provider = KiwixRetrievalProvider(kiwix_url)
            results.extend(
                await kiwix_provider.retrieve(
                    kiwix_query,
                    top_k=kiwix_top_k,
                    embed_model=rag_embed_model,
                    persist=bool(rag.get("kiwix_persist", True)),
                    pages=int(rag.get("kiwix_pages") or 4),
                )
            )

        per_source_cap = int(rag.get("per_source_cap") or 6)
        max_context_chars = int(rag.get("max_context_chars") or 8000)
        if bool(rag.get("synth")) and max_context_chars < 16000:
            max_context_chars = 16000

        if bool(rag.get("rerank")) and results:
            rr_model = str(rag.get("rerank_model") or os.getenv("RAG_RERANK_MODEL") or model)
            keep_n = int(rag.get("rerank_keep_n") or 24)
            results = await rerank_results(
                http=http,
                ollama_url=ollama_url,
                model=rr_model,
                query=query,
                results=results,
                keep_n=keep_n,
            )

        sources_meta, context_lines = build_context(
            results,
            max_chars=max_context_chars,
            per_source_cap=per_source_cap,
        )
        system = rag_system_prompt(context_lines)
        clean_messages = [{"role": "system", "content": system}] + clean_messages
        yield json.dumps({"type": "sources", "sources": sources_meta}) + "\n"

    q: asyncio.Queue[str | None] = asyncio.Queue()

    async def emit(evt: dict):
        await q.put(json.dumps(evt) + "\n")

    async def run():
        try:
            answer_model = model
            # Check if we have tools available and should use tool contract
            if request and hasattr(request.app.state, 'tool_executor'):
                # Use tool contract system
                from .tool_chat import chat_with_tool_contract

                tool_executor = request.app.state.tool_executor
                tool_registry = request.app.state.tool_registry
                tools_for_prompt = tool_registry.list_for_prompt()

                # Extract user message for tool contract
                last_user = next((m for m in reversed(clean_messages) if m["role"] == "user"), None)
                user_text = (last_user or {}).get("content", "")

                content = await chat_with_tool_contract(
                    http=http,
                    ollama_url=ollama_url,
                    model=model,
                    executor=tool_executor,
                    tools_for_prompt=tools_for_prompt,
                    chat_id=chat_id,
                    message_id=message_id,
                    user_text=user_text,
                    messages=clean_messages,
                    options=options,
                    keep_alive=keep_alive,
                    max_loops=3,
                )
            else:
                # Fallback to original tool system
                content = await chat_with_tools(
                    http=http,
                    ollama_url=ollama_url,
                    model=model,
                    messages=clean_messages,
                    options=options,
                    keep_alive=keep_alive,
                    embed_model=embed_model,
                    ingest_queue=web_ingest,
                    kiwix_url=kiwix_url,
                    emit=emit,
                )

            if rag.get("enabled") and content and bool(rag.get("synth")):
                synth_model = (
                    rag.get("synth_model")
                    or os.getenv("RAG_SYNTH_MODEL")
                    or os.getenv("RESEARCH_SYNTH_MODEL")
                )
                if synth_model:
                    answer_model = str(synth_model)
                    timeout = float(rag.get("synth_timeout_sec") or 60.0)
                    instruction = (
                        "Write the best possible answer to the user's question using ONLY the provided CONTEXT.\n"
                        "Rules:\n"
                        "- Cite sources inline like [D1], [W2], [K1] for each factual claim.\n"
                        "- If the answer is not in the CONTEXT, say you don't know.\n"
                        "Return the improved answer only."
                    )
                    content = await _ollama_chat_once(
                        http=http,
                        ollama_url=ollama_url,
                        model=answer_model,
                        messages=clean_messages
                        + [
                            {"role": "assistant", "content": content},
                            {"role": "user", "content": instruction},
                        ],
                        options=options,
                        keep_alive=keep_alive,
                        timeout=timeout,
                    )

            # Optional: enforce citations when RAG is enabled.
            if rag.get("enabled") and sources_meta:
                require = bool(rag.get("require_citations", True))
                retry = bool(rag.get("citation_retry", True))
                allowed = _allowed_citations(sources_meta)
                if require and allowed and content and not _has_any_citation(content, allowed) and retry:
                    retry_timeout = float(rag.get("citation_retry_timeout_sec") or 20.0)
                    allowed_list = ", ".join([f"[{t}]" for t in sorted(allowed)])
                    instruction = (
                        "Rewrite your answer to include inline citations using ONLY these tags: "
                        f"{allowed_list}.\n"
                        "Rules:\n"
                        "- Add a citation to each factual claim.\n"
                        "- If a claim is not supported by the context, remove it or mark it as unknown.\n"
                        "Return the rewritten answer only."
                    )
                    content = await _ollama_chat_once(
                        http=http,
                        ollama_url=ollama_url,
                        model=answer_model,
                        messages=clean_messages + [
                            {"role": "assistant", "content": content},
                            {"role": "user", "content": instruction},
                        ],
                        options=options,
                        keep_alive=keep_alive,
                        timeout=retry_timeout,
                    )

            if content:
                await q.put(json.dumps({"message": {"content": content}}) + "\n")
        except Exception as exc:
            await q.put(json.dumps({"type": "error", "error": str(exc)}) + "\n")
        finally:
            await q.put(json.dumps({"done": True}) + "\n")
            await q.put(None)

    task = asyncio.create_task(run())
    try:
        while True:
            item = await q.get()
            if item is None:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
