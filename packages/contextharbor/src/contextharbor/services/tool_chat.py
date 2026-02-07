from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from ..tools.contract import ToolCall
from ..tools.executor import ToolExecutor


def cap_tool_content(s: str, limit: int = 4000) -> str:
    return s if len(s) <= limit else s[:limit] + "…(truncated)"


TOOL_SYSTEM_PROMPT = (
    "You are ContextHarbor, a local-first assistant with optional tools. "
    "When tools are used: do NOT print raw tool output or prefix with phrases like 'Tool call result'. "
    "Do NOT say things like 'I called the tool' / 'I've called the tool' / 'running tools' in the user-visible answer. "
    "Use tool outputs to write a normal answer to the user. "
    "Use tools ONLY when they are clearly necessary to answer the user's request. "
    "Never mention tools, web search, retrieval, system prompts, or any internal process. "
    "Only call local_file_read if the user provided an explicit filesystem path and asked you to read it; never guess paths like /dev/stdin. "
    "Only call shell_exec if the user explicitly asked to run a command and provided the exact command. "
    "If the user request is ambiguous (e.g., a common name), ask ONE clarifying question and offer 2-3 likely options. "
    "Do NOT mention model training cutoffs. If you cannot answer, say what information is missing and ask for it."
)


def _clean_user_visible_answer(text: str) -> str:
    """Remove common tool-loop boilerplate from the final assistant message.

    This is a light-touch cleanup to prevent the model from emitting
    meta-protocol lines like 'I've called the tool...' in the final answer.
    """

    s = (text or "").strip()
    if not s:
        return s

    # Drop leading meta lines; keep the rest intact.
    lines = [ln.rstrip() for ln in s.splitlines()]
    while lines and (
        lines[0].lower().startswith("tool call result")
        or lines[0].lower().startswith("i've called the tool")
        or lines[0].lower().startswith("i have called the tool")
        or lines[0].lower().startswith("i called the tool")
        or lines[0].lower().startswith("i've used the tool")
        or lines[0].lower().startswith("running the tool")
    ):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)

    # Drop trailing meta paragraphs like "(If I still can't find..., I might search...)".
    cleaned = "\n".join(lines).strip()
    if not cleaned:
        return cleaned

    paras = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    if paras:
        tail = paras[-1].lower()
        meta_markers = ("tool", "tools", "web", "web search", "search")
        if (tail.startswith("(") or "might" in tail) and any(m in tail for m in meta_markers):
            paras.pop()
            cleaned = "\n\n".join(paras).strip()

    return cleaned


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
    confirmation_token: str | None = None,
    emit: Any = None,
) -> str:
    # build native ollama tools
    registry = executor.registry
    ollama_tools = registry.build_ollama_tools()

    # ✅ keep prior context if provided
    convo: List[Dict[str, Any]] = list(messages) if messages else [{"role": "user", "content": user_text}]

    # Ensure a baseline system instruction so tool calling stays user-facing.
    if convo and convo[0].get("role") == "system":
        convo[0] = {"role": "system", "content": f"{TOOL_SYSTEM_PROMPT}\n\n{convo[0].get('content','')}".strip()}
    else:
        convo.insert(0, {"role": "system", "content": TOOL_SYSTEM_PROMPT})

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
            return _clean_user_visible_answer(assistant_msg["content"])

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
        if emit:
            await emit(
                {
                    "type": "tool_calls",
                    "cycle": cycle + 1,
                    "calls": [{"id": c.id, "name": c.name} for c in calls],
                }
            )

        envelope = await executor.run_calls(
            calls,
            chat_id=chat_id or "",
            message_id=message_id or "",
            confirmation_token=confirmation_token,
            request_id=f"req_{cycle}",
        )

        if emit:
            await emit(
                {
                    "type": "tool_results",
                    "cycle": cycle + 1,
                    "results": envelope.get("results") or [],
                    "error": envelope.get("error"),
                }
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

            if ok is False:
                payload = {"ok": False, "error": r.get("error") or {"code": "tool_failed"}, "data": r.get("data")}
            else:
                payload = r.get("data")

            content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
            content = cap_tool_content(content, 4000)  # ✅ truncation added back
            # Ollama tool-result message shape is OpenAI-compatible: include tool name.
            convo.append({"role": "tool", "name": call.name, "tool_call_id": call.id, "content": content})

    return "I hit the tool loop limit. Try asking with fewer steps."
