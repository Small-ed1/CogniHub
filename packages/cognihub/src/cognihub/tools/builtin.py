from __future__ import annotations

import asyncio
import os
import httpx
import subprocess
import shlex
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from .registry import ToolRegistry, ToolSpec
from ..services.tooling import ToolDocSearchReq, ToolWebSearchReq, tool_doc_search, tool_web_search


class WebSearchArgs(BaseModel):
    q: str = Field(min_length=1, max_length=256)


class DocSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=256)
    top_k: int = Field(default=5, ge=1, le=20)


class ShellExecArgs(BaseModel):
    command: str = Field(min_length=1, max_length=512)
    cwd: Optional[str] = Field(default=None, max_length=256)
    timeout: int = Field(default=30, ge=1, le=300)


class KiwixListZimsArgs(BaseModel):
    zim_dir: Optional[str] = Field(default=None, max_length=512)


class EpubListArgs(BaseModel):
    q: Optional[str] = Field(default=None, max_length=256)
    limit: int = Field(default=25, ge=1, le=200)


class EpubIngestArgs(BaseModel):
    path: Optional[str] = Field(default=None, max_length=1024)
    q: Optional[str] = Field(default=None, max_length=256)
    limit: int = Field(default=1, ge=1, le=20)


def register_builtin_tools(
    registry: ToolRegistry,
    *,
    http: httpx.AsyncClient,
    ingest_queue,
    embed_model: str,
    kiwix_url: Optional[str] = None,
) -> None:

    async def web_search_handler(args: WebSearchArgs) -> Dict[str, Any]:
        try:
            req = ToolWebSearchReq(query=args.q)
            result = await tool_web_search(
                req,
                http=http,
                ingest_queue=ingest_queue,
                embed_model=embed_model,
                kiwix_url=kiwix_url,
            )

            items = []
            # tool_web_search returns results in "results" key, not "pages"
            for p in result.get("results", []):
                items.append({
                    "title": p.get("title", ""),
                    "url": p.get("url", ""),
                    "snippet": p.get("snippet", ""),
                })
            
            # Check for empty results and treat as error if provider indicates blocking
            if not items:
                # Check if we have provider info indicating failure
                if hasattr(result, 'get') and result.get('provider_error'):
                    return {
                        "items": [],
                        "error": f"web_search failed: {result['provider_error']}"
                    }
                else:
                    return {
                        "items": [], 
                        "error": "web_search returned no results (provider may be blocked)"
                    }
            
            return {"items": items}
            
        except Exception as e:
            # Convert any exception to structured error response
            return {
                "items": [],
                "error": f"web_search failed: {str(e)}"
            }

    async def doc_search_handler(args: DocSearchArgs) -> Dict[str, Any]:
        req = ToolDocSearchReq(query=args.query, top_k=args.top_k)
        result = await tool_doc_search(req)

        chunks = []
        for hit in result.get("results", []):
            chunks.append({
                "text": hit.get("text", ""),
                "score": hit.get("score", 0.0),
                "source": hit.get("title", ""),
                "url": hit.get("url"),
            })
        return {"chunks": chunks}

    async def shell_exec_handler(args: ShellExecArgs) -> Dict[str, Any]:
        """Execute shell command with strict safety controls."""
        try:
            # Parse command safely
            cmd_parts = shlex.split(args.command)
            if not cmd_parts:
                return {"error": "empty command"}

            # Basic allowlist - filesystem and safe commands only (no network)
            allowed_commands = {
                'ls', 'pwd', 'echo', 'cat', 'head', 'tail', 'grep', 'wc', 'sort',
                'df', 'du', 'free', 'ps', 'uptime', 'date', 'whoami', 'id',
                'python3', 'python', 'git'
            }

            if cmd_parts[0] not in allowed_commands:
                return {"error": f"command '{cmd_parts[0]}' not in allowlist"}

            # Execute with timeout and output capture
            result = subprocess.run(
                cmd_parts,
                cwd=args.cwd,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                shell=False  # Never use shell=True
            )

            return {
                "returncode": result.returncode,
                "stdout": result.stdout[:4096] if result.stdout else "",  # Cap output
                "stderr": result.stderr[:4096] if result.stderr else "",
            }

        except subprocess.TimeoutExpired:
            return {"error": "command timed out"}
        except Exception as e:
            return {"error": f"execution failed: {str(e)}"}

    async def kiwix_list_zims_handler(args: KiwixListZimsArgs) -> Dict[str, Any]:
        from ..services import kiwix
        from .. import config

        zim_dir = args.zim_dir or config.config.kiwix_zim_dir
        zims = await kiwix.list_zims(zim_dir)
        return {"zims": zims, "zim_dir": zim_dir}

    async def epub_list_handler(args: EpubListArgs) -> Dict[str, Any]:
        from .. import config
        from ..ingest import epub as epub_ingest

        library_dir = config.config.ebooks_dir
        items = await asyncio.to_thread(
            epub_ingest.list_epubs,
            query=args.q,
            limit=args.limit,
            library_dir=library_dir,
        )
        return {"library_dir": library_dir, "items": items}

    async def epub_ingest_handler(args: EpubIngestArgs) -> Dict[str, Any]:
        from .. import config
        from ..ingest import epub as epub_ingest

        library_dir = config.config.ebooks_dir
        if args.path:
            return await epub_ingest.ingest_epub(
                path=args.path,
                embed_model=embed_model,
                library_dir=library_dir,
            )
        if args.q:
            return await epub_ingest.ingest_epubs_by_query(
                query=args.q,
                limit=args.limit,
                embed_model=embed_model,
                library_dir=library_dir,
            )
        return {"ok": False, "error": "Provide either path or q"}

    registry.register(
        ToolSpec(
            name="web_search",
            description="Search the web. Args: {q}. Returns: {items:[{title,url,snippet}]}",
            args_model=WebSearchArgs,
            handler=web_search_handler,
            side_effect="network",
        )
    )

    registry.register(
        ToolSpec(
            name="kiwix_list_zims",
            description="List local Kiwix ZIM files. Args: {zim_dir?}. Returns: {zims:[...], zim_dir}",
            args_model=KiwixListZimsArgs,
            handler=kiwix_list_zims_handler,
            side_effect="read_only",
        )
    )

    registry.register(
        ToolSpec(
            name="epub_list",
            description="List EPUBs from the Calibre library. Args: {q?, limit?}. Returns: {items:[{path}], library_dir}",
            args_model=EpubListArgs,
            handler=epub_list_handler,
            side_effect="read_only",
        )
    )

    registry.register(
        ToolSpec(
            name="epub_ingest",
            description="Ingest EPUB(s) into RAG. Args: {path?} or {q?, limit?}. Returns: {ok, doc_id?} or {results:[...]}",
            args_model=EpubIngestArgs,
            handler=epub_ingest_handler,
            side_effect="writes",
        )
    )

    registry.register(
        ToolSpec(
            name="doc_search",
            description="Search docs (RAG). Args: {query, top_k}. Returns: {chunks:[...]}",
            args_model=DocSearchArgs,
            handler=doc_search_handler,
            side_effect="read_only",
        )
    )

    # Shell exec - only register if explicitly enabled
    if os.getenv("ALLOW_SHELL_EXEC", "").lower() in ("1", "true", "yes"):
        registry.register(
            ToolSpec(
                name="shell_exec",
                description="Execute safe shell commands (allowlisted only). Args: {command, cwd?, timeout}. Returns: {returncode, stdout, stderr}",
                args_model=ShellExecArgs,
                handler=shell_exec_handler,
                side_effect="dangerous",
                requires_confirmation=True,
            )
        )
