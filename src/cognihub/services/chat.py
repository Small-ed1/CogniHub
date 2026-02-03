from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

import httpx

from .context import build_context, rag_system_prompt
from .models import ModelRegistry
from .retrieval import DocRetrievalProvider
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

    if rag.get("enabled"):
        yield json.dumps({"type": "status", "stage": "calling_tools"}) + "\n"
        last_user = next((m for m in reversed(clean_messages) if m["role"] == "user"), None)
        query = (last_user or {}).get("content", "")
        provider = DocRetrievalProvider()
        sources = await provider.retrieve(
            query,
            top_k=int(rag.get("top_k") or 6),
            doc_ids=rag.get("doc_ids"),
            embed_model=rag.get("embed_model") or embed_model,
            use_mmr=rag.get("use_mmr"),
            mmr_lambda=rag.get("mmr_lambda", 0.75),
        )

        sources_meta, context_lines = build_context(sources)
        system = rag_system_prompt(context_lines)
        clean_messages = [{"role": "system", "content": system}] + clean_messages
        yield json.dumps({"type": "sources", "sources": sources_meta}) + "\n"

    q: asyncio.Queue[str | None] = asyncio.Queue()

    async def emit(evt: dict):
        await q.put(json.dumps(evt) + "\n")

    async def run():
        try:
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
