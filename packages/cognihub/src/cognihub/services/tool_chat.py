import json
from typing import Any, Dict, List, Optional

import httpx

from ..tools.contract import ToolCall
from ..tools.executor import ToolExecutor


def cap_tool_content(s: str, limit: int = 4000) -> str:
    return s if len(s) <= limit else s[:limit] + "…(truncated)"


async def _call_llm(
    *,
    http: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    options: Optional[Dict[str, Any]] = None,
    keep_alive: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    if options:
        payload["options"] = options
    if keep_alive:
        payload["keep_alive"] = keep_alive

    timeout = httpx.Timeout(60.0)
    resp = await http.post(f"{ollama_url}/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json().get("message", {}) or {}


async def chat_with_tool_contract(
    *,
    http: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    executor: ToolExecutor,
    tools_for_prompt: List[Dict[str, str]],  # kept for compatibility, unused
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    user_text: str,
    messages: Optional[List[Dict[str, Any]]] = None,  # ✅ preserve full context
    options: Optional[Dict[str, Any]] = None,
    keep_alive: Optional[str] = None,
    max_loops: int = 3,
) -> str:
    # build native ollama tools
    registry = executor.registry
    ollama_tools = registry.build_ollama_tools()

    # ✅ keep prior context if provided
    convo: List[Dict[str, Any]] = list(messages) if messages else [{"role": "user", "content": user_text}]

    for cycle in range(max_loops):
        msg = await _call_llm(
            http=http,
            ollama_url=ollama_url,
            model=model,
            messages=convo,
            tools=ollama_tools,
            options=options,
            keep_alive=keep_alive,
        )

        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": msg.get("content", "") or ""}
        if msg.get("tool_calls"):
            assistant_msg["tool_calls"] = msg["tool_calls"]
        convo.append(assistant_msg)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return assistant_msg["content"]

        # ✅ parse tool calls robustly (id/index/arguments string-or-object)
        calls: List[ToolCall] = []
        for tc in tool_calls:
            func = tc.get("function", {}) or {}
            name = func.get("name")

            args = func.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            call_id = tc.get("id") or f"{cycle}_{func.get('index', 0)}_{name}"
            calls.append(ToolCall(id=str(call_id), name=str(name), arguments=args))

        # ✅ batch execute
        envelope = await executor.run_calls(
            calls,
            chat_id=chat_id or "",
            message_id=message_id or "",
            confirmation_token=None,
            request_id=f"req_{cycle}",
        )

        results = envelope.get("results") or []
        by_id = {r.get("id"): r for r in results if isinstance(r, dict)}

        # ✅ send CLEAN tool output back to model (with truncation)
        for i, call in enumerate(calls):
            r = by_id.get(call.id, {})
            if not r and i < len(results):
                # fallback to order if id matching fails
                r = results[i] if isinstance(results[i], dict) else {}
            
            ok = r.get("ok", True)

            data = r.get("data")
            if ok is False:
                data = {"error": r.get("error") or "tool_failed", "data": data}

            content = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
            content = cap_tool_content(content, 4000)  # ✅ truncation added back
            convo.append({"role": "tool", "tool_name": call.name, "content": content})

    return "I hit the tool loop limit. Try asking with fewer steps."