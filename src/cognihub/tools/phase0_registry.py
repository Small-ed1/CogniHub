"""Phase 0 tool registry with dependency-bound legacy tools.

This module creates a ToolRegistry with wrappers for the existing
tool functions, preserving their behavior while enabling streaming support.
"""

from .runtime import ToolRegistry, ToolSpec
from ..services.tooling import (
    ToolWebSearchReq, 
    ToolDocSearchReq, 
    ToolKiwixSearchReq,
    tool_web_search,
    tool_doc_search,
    tool_kiwix_search
)


def build_phase0_registry(*, http, ingest_queue, embed_model, kiwix_url) -> ToolRegistry:
    """Build a registry with the three core tools using dependency injection."""
    registry = ToolRegistry()
    
    # web_search - dependency binding via closure
    registry.register(ToolSpec(
        name="web_search",
        description="Search the web for information using various search engines",
        args_schema=ToolWebSearchReq,
        handler=lambda args: tool_web_search(
            args, 
            http=http, 
            ingest_queue=ingest_queue, 
            embed_model=embed_model, 
            kiwix_url=kiwix_url
        )
    ))
    
    # doc_search - dependency binding via closure (no extra deps)
    registry.register(ToolSpec(
        name="doc_search",
        description="Search uploaded documents and knowledge base",
        args_schema=ToolDocSearchReq,
        handler=lambda args: tool_doc_search(args)
    ))
    
    # kiwix_search - dependency binding via closure
    registry.register(ToolSpec(
        name="kiwix_search",
        description="Search offline content via Kiwix Wikipedia dumps",
        args_schema=ToolKiwixSearchReq,
        handler=lambda args: tool_kiwix_search(args, kiwix_url=kiwix_url, embed_model=embed_model)
    ))
    
    return registry