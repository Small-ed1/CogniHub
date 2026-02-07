from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ValidationError

from .contract import ToolCall
from .registry import ToolRegistry
from ..toolstore import ToolStore


class ToolExecutionError(Exception):
    pass


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        toolstore: ToolStore,
        *,
        timeout_s: float = 12.0,
        max_output_chars: int = 12_000,
        global_timeout_s: float = 60.0,  # Max time for entire batch of calls
    ) -> None:
        self.registry = registry
        self.toolstore = toolstore
        self.timeout_s = timeout_s
        self.max_output_chars = max_output_chars
        self.global_timeout_s = global_timeout_s

    async def run_calls(
        self,
        calls: List[ToolCall],
        *,
        chat_id: str,
        message_id: str,
        confirmation_token: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        import asyncio

        async def run_with_global_timeout():
            results = []
            for call in calls:
                results.append(
                    await self._run_one(
                        call,
                        chat_id=chat_id,
                        message_id=message_id,
                        confirmation_token=confirmation_token,
                    )
                )
            return results

        try:
            results = await asyncio.wait_for(run_with_global_timeout(), timeout=self.global_timeout_s)
            return {"type": "tool_result", "id": request_id or "server", "results": results, "error": None}
        except asyncio.TimeoutError:
            return {
                "type": "tool_result",
                "id": request_id or "server",
                "results": [],
                "error": {"code": "global_timeout", "message": "tool batch exceeded global timeout"},
            }

    async def _run_one(
        self,
        call: ToolCall,
        *,
        chat_id: str,
        message_id: str,
        confirmation_token: Optional[str],
    ) -> Dict[str, Any]:
        spec = self.registry.get(call.name)
        if not spec or not spec.enabled:
            return self._result(call, ok=False, data=None, error={"code": "tool_not_found", "message": "tool not found or disabled"})

        # confirmation gating
        if spec.requires_confirmation and confirmation_token != "CONFIRMED":
            return self._result(call, ok=False, data=None, error={"code": "confirmation_required", "message": "confirmation token required"})

        # validate args against tool schema
        try:
            args_obj = spec.args_model.model_validate(call.arguments)
        except ValidationError as e:
            return self._result(
                call,
                ok=False,
                data=None,
                error={"code": "invalid_arguments", "message": "arguments failed schema validation", "details": e.errors()},
            )

        start = time.perf_counter()
        ok = True
        data: Dict[str, Any] | None = None
        err: Dict[str, Any] | None = None
        meta: Dict[str, Any] = {}

        try:
            data = await asyncio.wait_for(spec.handler(args_obj), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            ok = False
            err = {"code": "timeout", "message": "tool execution timed out"}
        except Exception as ex:
            from .exceptions import ToolError

            ok = False
            if isinstance(ex, ToolError):
                err = {"code": ex.code, "message": str(ex), "details": getattr(ex, "details", {})}
            else:
                err = {"code": "tool_failed", "message": "tool execution failed", "detail": str(ex)}

        ms = int((time.perf_counter() - start) * 1000)
        meta["ms"] = ms

        # cap + hash output for logs
        raw = json.dumps({"ok": ok, "data": data, "error": err}, ensure_ascii=False)
        excerpt = raw[: self.max_output_chars]
        sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        await self.toolstore.log_tool_run(
            chat_id=chat_id,
            message_id=message_id,
            tool_name=call.name,
            args_json=json.dumps(call.arguments, ensure_ascii=False),
            ok=ok,
            duration_ms=ms,
            output_excerpt=excerpt,
            output_sha256=sha,
            meta_json=json.dumps(meta, ensure_ascii=False),
        )

        return self._result(call, ok=ok, data=data, meta=meta, error=err)

    def _result(
        self,
        call: ToolCall,
        *,
        ok: bool,
        data: Dict[str, Any] | None,
        meta: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "id": call.id,
            "name": call.name,
            "ok": ok,
            "data": data,
            "error": error,
            "meta": meta or {},
        }
