from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from ..stores import ragstore, webstore
from .. import config
from ..tools.models import ToolProgress
from .retrieval import KiwixRetrievalProvider
from .web_ingest import WebIngestQueue
from .web_search import web_search_with_fallback, SearchError

logger = logging.getLogger(__name__)

def _tool_engine() -> str:
    """Runtime-checkable tool engine selection."""
    return os.getenv("TOOL_ENGINE", "legacy")


def _runtime_signature(http, ingest_queue, embed_model, kiwix_url) -> str:
    """Create a unique signature for runtime configuration."""
    # Use object identity for http client to detect stale connections
    http_id = id(http) if http else "none"
    ingest_id = id(ingest_queue) if ingest_queue else "none"
    return f"http:{http_id}|ingest:{ingest_id}|embed:{embed_model}|kiwix:{kiwix_url}"


def _get_or_create_runtime(http, ingest_queue, embed_model, kiwix_url):
    """Get or create runtime with proper dependency injection."""
    signature = _runtime_signature(http, ingest_queue, embed_model, kiwix_url)
    
    if signature not in _runtime_cache:
        from ..tools.phase0_registry import build_phase0_registry
        from ..tools.runtime import ToolRuntime
        
        registry = build_phase0_registry(
            http=http,
            ingest_queue=ingest_queue,
            embed_model=embed_model,
            kiwix_url=kiwix_url
        )
        runtime = ToolRuntime(registry)
        _runtime_cache[signature] = runtime
    
    return _runtime_cache[signature]

# Runtime cache keyed by configuration signature to avoid stale dependencies
_runtime_cache: dict[str, Any] = {}


DEFAULT_MAX_TOOL_ROUNDS = 3
MAX_WEB_PAGES = 12


def _ollama_chat_timeout() -> float | None:
    """Return timeout seconds for Ollama /api/chat calls.

    Model loads can take minutes; default to no timeout unless explicitly set.
    """
    raw = os.getenv("OLLAMA_CHAT_TIMEOUT_SEC", "0").strip()
    try:
        sec = float(raw)
    except ValueError:
        sec = 0.0
    return None if sec <= 0 else sec


class ToolDocSearchReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str
    top_k: int = 6
    doc_ids: list[int] | None = None
    embed_model: str | None = None
    use_mmr: bool | None = None
    mmr_lambda: float = 0.75


class ToolWebSearchReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str
    top_k: int = 6
    pages: int = 5
    domain_whitelist: list[str] | None = None
    embed_model: str | None = None
    force: bool = False


class ToolKiwixSearchReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str
    top_k: int = 6


@dataclass
class ToolLoopResult:
    content: str
    messages: list[dict[str, Any]]
    used_tools: bool


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "doc_search",
                "description": "Search uploaded documents for relevant passages.",
                "parameters": ToolDocSearchReq.model_json_schema(),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web and return relevant passages.",
                "parameters": ToolWebSearchReq.model_json_schema(),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "kiwix_search",
                "description": "Search offline Kiwix content if configured.",
                "parameters": ToolKiwixSearchReq.model_json_schema(),
            },
        },
    ]


def _clamp_int(val: int, low: int, high: int) -> int:
    return max(low, min(high, int(val)))


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


async def tool_doc_search(req: ToolDocSearchReq) -> dict[str, Any]:
    query = (req.query or "").strip()
    if not query:
        raise ValueError("query required")
    hits = await ragstore.retrieve(
        query,
        top_k=req.top_k,
        doc_ids=req.doc_ids,
        embed_model=req.embed_model,
        use_mmr=req.use_mmr,
        mmr_lambda=req.mmr_lambda,
    )
    return {"query": query, "results": hits}


async def tool_web_search(
    req: ToolWebSearchReq,
    *,
    http: httpx.AsyncClient,
    ingest_queue: WebIngestQueue | None,
    embed_model: str,
    kiwix_url: str | None,
) -> dict[str, Any]:
    query = (req.query or "").strip()
    if not query:
        raise ValueError("query required")
    pages = _clamp_int(req.pages, 1, MAX_WEB_PAGES)
    errors: list[dict[str, Any]] = []
    kiwix_results: list[dict[str, Any]] = []
    if kiwix_url:
        try:
            kiwix_provider = KiwixRetrievalProvider(kiwix_url)
            kiwix_results = [
                r.__dict__
                for r in await kiwix_provider.retrieve(query, top_k=req.top_k, embed_model=req.embed_model)
            ]
        except Exception as exc:
            errors.append({"stage": "kiwix", "error": str(exc)})

    try:
        urls, provider_info = await web_search_with_fallback(http, query, n=pages)
        # Log which provider succeeded
        if provider_info.endswith("_success"):
            provider_name = provider_info.replace("_success", "")
            logger.info(f"Search succeeded with provider: {provider_name}")
    except SearchError as exc:
        urls = []
        errors.append({"stage": "search", "error": str(exc)})
    except Exception as exc:
        urls = []
        errors.append({"stage": "search", "error": str(exc)})

    fetched = []
    queued: list[str] = []
    if urls:
        sync_cap = len(urls) if req.force else 2
        sync_targets = urls[:sync_cap]
        queued = urls[sync_cap:]
        tasks = [webstore.upsert_page_from_url(u, force=bool(req.force)) for u in sync_targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for url, result in zip(sync_targets, results):
            if isinstance(result, BaseException):
                errors.append({"url": url, "error": str(result)})
                continue
            if not isinstance(result, dict):
                errors.append({"url": url, "error": "unexpected response"})
                continue
            fetched.append(
                {
                    "url": result.get("url") or url,
                    "title": result.get("title"),
                    "domain": result.get("domain"),
                    "page_id": result.get("id"),
                }
            )
        if ingest_queue is not None:
            for url in queued:
                await ingest_queue.enqueue(url)

    hits = await webstore.retrieve(
        query,
        top_k=req.top_k,
        domain_whitelist=req.domain_whitelist,
        embed_model=req.embed_model or embed_model,
    )
    combined = kiwix_results + hits
    
    # Add provider error info if search failed
    provider_error = None
    if not urls and errors:
        for error in errors:
            if error.get("stage") == "search":
                provider_error = error.get("error", "Unknown search error")
                break
    
    return {
        "query": query,
        "urls": urls,
        "fetched": fetched,
        "queued": queued,
        "errors": errors,
        "kiwix_results": kiwix_results,
        "results": combined,
        "provider_error": provider_error,
    }


async def tool_kiwix_search(
    req: ToolKiwixSearchReq,
    *,
    kiwix_url: str | None,
    embed_model: str,
) -> dict[str, Any]:
    if not kiwix_url:
        return {"results": [], "error": "KIWIX_URL not set"}
    query = (req.query or "").strip()
    if not query:
        raise ValueError("query required")
    provider = KiwixRetrievalProvider(kiwix_url)
    results = await provider.retrieve(query, top_k=req.top_k, embed_model=embed_model)
    return {"results": [r.__dict__ for r in results]}


async def _execute_tool_call(
    name: str,
    args: dict[str, Any],
    *,
    http: httpx.AsyncClient,
    ingest_queue: WebIngestQueue | None,
    embed_model: str,
    kiwix_url: str | None,
) -> dict[str, Any]:
    if name == "doc_search":
        doc_req = ToolDocSearchReq.model_validate(args)
        return await tool_doc_search(doc_req)
    elif name == "web_search":
        web_req = ToolWebSearchReq.model_validate(args)
        return await tool_web_search(
            web_req,
            http=http,
            ingest_queue=ingest_queue,
            embed_model=embed_model,
            kiwix_url=kiwix_url,
        )
    elif name == "kiwix_search":
        kiwix_req = ToolKiwixSearchReq.model_validate(args)
        return await tool_kiwix_search(kiwix_req, kiwix_url=kiwix_url, embed_model=embed_model)
    raise ValueError(f"Unknown tool: {name}")


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    if isinstance(message, dict):
        tool_calls = message.get("tool_calls")
    else:
        tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return []
    if isinstance(tool_calls, list):
        return tool_calls
    return []


def _parse_tool_call(call: dict[str, Any], index: int) -> tuple[str, dict[str, Any], str]:
    call_id = call.get("id") or call.get("tool_call_id") or f"tool_call_{index}"
    function = call.get("function") or {}
    name = function.get("name") or call.get("name") or ""
    raw_args = function.get("arguments") if function else call.get("arguments")
    args = _parse_tool_args(raw_args)
    return name, args, call_id


async def run_tool_calling_loop(
    *,
    http: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    messages: list[dict[str, Any]],
    options: dict[str, Any] | None,
    keep_alive: str | None,
    embed_model: str,
    ingest_queue: WebIngestQueue | None,
    kiwix_url: str | None,
    max_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    emit: Any = None,
) -> ToolLoopResult:
    tools = tool_definitions()
    working = list(messages)
    used_tools = False

    timeout = _ollama_chat_timeout()

    for round_idx in range(max_rounds):
        payload: dict[str, Any] = {
            "model": model,
            "messages": working,
            "stream": False,
            "tools": tools,
        }
        if options is not None:
            payload["options"] = options
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        if emit:
            if round_idx == 0:
                await emit({"type": "status", "stage": "pulling_from_disk"})
            else:
                await emit({"type": "status", "stage": "constructing_response"})

        resp = await http.post(f"{ollama_url}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        message = (resp.json().get("message") or {})
        content = (message.get("content") or "").strip()
        tool_calls = _extract_tool_calls(message)
        if not tool_calls:
            if emit:
                await emit({"type": "status", "stage": "constructing_response"})
            return ToolLoopResult(content=content, messages=working, used_tools=used_tools)

        used_tools = True

        if emit:
            await emit({"type": "status", "stage": "calling_tools"})
        assistant_msg = {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
        }
        working.append(assistant_msg)

        for idx, call in enumerate(tool_calls, start=1):
            if not isinstance(call, dict):
                continue
            name, args, call_id = _parse_tool_call(call, idx)
            execution_meta = None  # Initialize at scope level for audit logging
            try:
                if emit and name:
                    await emit({"type": "tool", "name": name})
                
                # Use registry engine if enabled
                if _tool_engine() == "registry":
                    # Get or create runtime with proper dependency injection
                    runtime = _get_or_create_runtime(http, ingest_queue, embed_model, kiwix_url)
                    
                    # Track execution metadata
                    start_time = time.time()
                    chunk_count = 0
                    total_bytes = 0
                    
                    # Execute with streaming runtime
                    final_result = None
                    execution_mode = "registry"
                    
                    async for chunk in runtime.call_async(name, args):
                        chunk_count += 1
                        
                        # Calculate result size for non-progress chunks
                        if chunk.ok and chunk.result is not None and not isinstance(chunk.result, ToolProgress):
                            try:
                                total_bytes += len(str(chunk.result).encode('utf-8'))
                            except Exception:
                                pass
                        
                        if chunk.ok and chunk.result is not None and isinstance(chunk.result, ToolProgress):
                            if emit:
                                await emit({
                                    "type": "tool_progress",
                                    "tool": name,
                                    "tool_call_id": call_id,
                                    **chunk.result.model_dump()
                                })
                        elif not chunk.ok:
                            raise RuntimeError(chunk.error or "Tool failed")
                        elif chunk.result is not None and not isinstance(chunk.result, ToolProgress):
                            final_result = chunk.result
                    
                    # Calculate execution metadata
                    duration_ms = int((time.time() - start_time) * 1000)
                    result = final_result
                    
                    execution_meta = {
                        "duration_ms": duration_ms,
                        "result_bytes": total_bytes,
                        "execution_mode": execution_mode,
                        "chunk_count": chunk_count,
                        "engine": "registry"
                    }
                else:
                    # Legacy execution path
                    start_time = time.time()
                    result = await _execute_tool_call(
                        name,
                        args,
                        http=http,
                        ingest_queue=ingest_queue,
                        embed_model=embed_model,
                        kiwix_url=kiwix_url,
                    )
                    duration_ms = int((time.time() - start_time) * 1000)
                    
                    try:
                        total_bytes = len(str(result).encode('utf-8'))
                    except Exception:
                        total_bytes = 0
                    
                    execution_meta = {
                        "duration_ms": duration_ms,
                        "result_bytes": total_bytes,
                        "execution_mode": "legacy",
                        "chunk_count": 1,
                        "engine": "legacy"
                    }
                
                # Create success payload with metadata
                payload = {"ok": True, "tool": name, "result": result}
                if execution_meta:
                    payload["meta"] = execution_meta
                
                # Audit log tool execution (success)
                logger.info(
                    "Tool execution succeeded",
                    extra={
                        "tool": name,
                        "ok": True,
                        "execution_meta": execution_meta,
                    }
                )
            except Exception as exc:
                # Import typed exceptions
                from ..tools.exceptions import ToolError
                
                # Handle typed exceptions separately
                if isinstance(exc, ToolError):
                    payload = {"ok": False, "tool": name, "error": str(exc), "code": exc.code}
                    if exc.details:
                        payload["details"] = exc.details
                else:
                    payload = {"ok": False, "tool": name, "error": str(exc), "code": "exception"}
                
                # Add metadata if available
                if execution_meta:
                    payload["meta"] = execution_meta
                
                # Audit log tool execution (errors)
                error_code = exc.code if isinstance(exc, ToolError) else "exception"
                logger.info(
                    "Tool execution failed",
                    extra={
                        "tool": name,
                        "ok": False,
                        "error_code": error_code,
                    }
                )
            working.append(
                {
                    "role": "tool",
                    "content": json.dumps(payload, ensure_ascii=False),
                    "tool_call_id": call_id,
                    "name": name,
                }
            )

    fallback_payload: dict[str, Any] = {"model": model, "messages": working, "stream": False}
    if options is not None:
        fallback_payload["options"] = options
    if keep_alive is not None:
        fallback_payload["keep_alive"] = keep_alive

    if emit:
        await emit({"type": "status", "stage": "constructing_response"})
    resp = await http.post(f"{ollama_url}/api/chat", json=fallback_payload, timeout=timeout)
    resp.raise_for_status()
    message = (resp.json().get("message") or {})
    content = (message.get("content") or "").strip()
    return ToolLoopResult(content=content, messages=working, used_tools=used_tools)


async def chat_with_tools(
    *,
    http: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    messages: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
    keep_alive: str | None = None,
    embed_model: str | None = None,
    ingest_queue: WebIngestQueue | None = None,
    kiwix_url: str | None = None,
    emit: Any = None,
) -> str:
    embed = embed_model or config.config.default_embed_model
    result = await run_tool_calling_loop(
        http=http,
        ollama_url=ollama_url,
        model=model,
        messages=messages,
        options=options,
        keep_alive=keep_alive,
        embed_model=embed,
        ingest_queue=ingest_queue,
        kiwix_url=kiwix_url,
        emit=emit,
    )
    return result.content
