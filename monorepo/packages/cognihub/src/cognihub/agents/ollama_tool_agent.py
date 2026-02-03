#!/usr/bin/env python3
"""
ollama_tool_agent.py

A robust tool-calling agent loop for Ollama:
- tool filtering (select relevant tools per request)
- schema validation + repair loop
- dedupe + caching
- loop guard + optional supervisor escalation
- safe-ish terminal tool

Requires:
  pip install requests
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from ollama_cli.client import OllamaClient as _OllamaClient

API_BASE = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")

# ----------------------------
# Types
# ----------------------------

Json = Dict[str, Any]
ToolFn = Callable[..., Any]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Json  # JSON Schema-ish
    keywords: List[str] = field(default_factory=list)

    def ollama_schema(self) -> Json:
        # Ollama expects OpenAI-style function schema inside tools[]
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class AgentConfig:
    ollama_host: str = "http://localhost:11434"
    main_model: str = "qwen3"
    supervisor_model: Optional[str] = None  # e.g. "qwen3:32b"
    stream: bool = False

    max_steps: int = 10
    max_tool_calls_per_step: int = 8
    max_total_tool_calls: int = 30

    # how many invalid tool attempts before escalation
    max_invalid_calls_before_escalate: int = 3

    # tool filtering
    max_tools_exposed: int = 8

    # output safety
    max_tool_output_chars: int = 8000

    # terminal tool safety
    terminal_timeout_s: int = 8


# ----------------------------
# Ollama client
# ----------------------------

class OllamaClient:
    def __init__(self, host: str):
        self.host = host.rstrip("/")
        self._client = _OllamaClient(self.host, timeout=60)

    def chat(self, model: str, messages: List[Json], tools: Optional[List[Json]] = None,
             stream: bool = False, options: Optional[Json] = None, think: bool = False) -> Json:
        # NOTE: ollama-cli client returns an iterator; keep the local API returning
        # a single JSON dict for compatibility.
        if think:
            options = dict(options or {})
            options["think"] = True

        it = self._client.chat(messages=messages, model=model, tools=tools, stream=stream, options=options)
        return next(it)


# ----------------------------
# Tool registry + validation
# ----------------------------

class ToolRegistry:
    def __init__(self):
        self._specs: Dict[str, ToolSpec] = {}
        self._fns: Dict[str, ToolFn] = {}

    def register(self, spec: ToolSpec, fn: ToolFn) -> None:
        self._specs[spec.name] = spec
        self._fns[spec.name] = fn

    def get_spec(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    def get_fn(self, name: str) -> Optional[ToolFn]:
        return self._fns.get(name)

    def all_specs(self) -> List[ToolSpec]:
        return list(self._specs.values())


def _type_ok(schema_type: str, value: Any) -> bool:
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    return True  # unknown types: don't hard-fail


def validate_args(schema: Json, args: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Minimal validation for JSON Schema-like tool parameters.
    """
    if not isinstance(args, dict):
        return False, "arguments must be an object"

    required = schema.get("required", [])
    props = schema.get("properties", {})
    additional_ok = schema.get("additionalProperties", True)

    for k in required:
        if k not in args:
            return False, f"missing required argument '{k}'"

    if additional_ok is False:
        extras = set(args.keys()) - set(props.keys())
        if extras:
            return False, f"unexpected arguments: {sorted(extras)}"

    # basic type checks + numeric bounds
    for k, v in args.items():
        prop = props.get(k)
        if not prop:
            continue
        t = prop.get("type")
        if t and not _type_ok(t, v):
            return False, f"argument '{k}' must be type {t}"
        if isinstance(v, (int, float)):
            if "minimum" in prop and v < prop["minimum"]:
                return False, f"argument '{k}' below minimum {prop['minimum']}"
            if "maximum" in prop and v > prop["maximum"]:
                return False, f"argument '{k}' above maximum {prop['maximum']}"

    return True, ""


# ----------------------------
# Tool selection (filtering)
# ----------------------------

class ToolSelector:
    """
    Cheap + effective tool filtering.
    Replace this with embeddings if you want later.
    """
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def select(self, user_text: str, max_tools: int, debug: bool = False) -> List[ToolSpec]:
        text = user_text.lower()

        scored: List[Tuple[int, ToolSpec]] = []
        for spec in self.registry.all_specs():
            score = 0
            # name/desc match
            if spec.name.lower() in text:
                score += 8
            for kw in spec.keywords:
                if kw.lower() in text:
                    score += 3
            # tiny boost if description matches
            for token in spec.description.lower().split():
                if token in text:
                    score += 1
            scored.append((score, spec))

        scored.sort(key=lambda x: x[0], reverse=True)
        picked = [s for (sc, s) in scored if sc > 0][:max_tools]

        if debug:
            print(f"DEBUG selector: scored {[(sc, s.name) for sc, s in scored]} picked {[s.name for s in picked]}")

        # if nothing matched, still expose a couple "general" tools if they exist
        if not picked:
            for fallback in ("doc_search", "web_search"):
                sp = self.registry.get_spec(fallback)
                if sp:
                    picked.append(sp)

        if debug:
            print(f"DEBUG fallback: picked {[s.name for s in picked]}")

        # final cap
        return picked[:max_tools]


# ----------------------------
# Tool-call parsing + fallbacks
# ----------------------------

TOOL_JSON_RE = re.compile(r'^\s*\{\s*"name"\s*:\s*".+?"\s*,\s*"arguments"\s*:', re.DOTALL)

def looks_like_tool_json(content: str) -> bool:
    return bool(TOOL_JSON_RE.match(content or ""))

def parse_tool_json(content: str) -> List[Json]:
    """
    Fallback: model prints JSON instead of returning tool_calls.
    Expected: {"name":"web_search","arguments":{"query":"..."}} OR list of those.
    """
    obj = json.loads(content)
    calls = []
    if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
        calls.append({
            "type": "function",
            "function": {"name": obj["name"], "arguments": obj["arguments"]},
        })
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and "name" in item and "arguments" in item:
                calls.append({
                    "type": "function",
                    "function": {"name": item["name"], "arguments": item["arguments"]},
                })
    return calls


def normalize_tool_calls(tool_calls: Any) -> List[Json]:
    """
    Ollama returns tool calls as JSON. Keep it tolerant.
    """
    if not tool_calls:
        return []
    if isinstance(tool_calls, list):
        out = []
        for tc in tool_calls:
            if isinstance(tc, dict) and "function" in tc:
                out.append(tc)
        return out
    return []


# ----------------------------
# Safe-ish tools
# ----------------------------

def truncate(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n...[TRUNCATED]..."


def _api_post(path: str, payload: Json, timeout_s: int = 30) -> Json:
    url = f"{API_BASE}{path}"
    r = requests.post(url, json=payload, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def tool_web_search(
    query: str,
    top_k: int = 5,
    pages: int = 5,
    domain_whitelist: Optional[List[str]] = None,
    embed_model: Optional[str] = None,
    force: bool = False,
) -> Json:
    payload = {
        "query": query,
        "top_k": top_k,
        "pages": pages,
        "domain_whitelist": domain_whitelist,
        "embed_model": embed_model,
        "force": force,
    }
    try:
        return _api_post("/api/tools/web_search", payload, timeout_s=60)
    except Exception as e:
        return {"error": f"api error: {e}", "query": query, "api_base": API_BASE}


def tool_doc_search(
    query: str,
    top_k: int = 5,
    doc_ids: Optional[List[int]] = None,
    embed_model: Optional[str] = None,
    use_mmr: Optional[bool] = None,
    mmr_lambda: float = 0.75,
) -> Json:
    payload = {
        "query": query,
        "top_k": top_k,
        "doc_ids": doc_ids,
        "embed_model": embed_model,
        "use_mmr": use_mmr,
        "mmr_lambda": mmr_lambda,
    }
    try:
        return _api_post("/api/tools/doc_search", payload, timeout_s=60)
    except Exception as e:
        return {"error": f"api error: {e}", "query": query, "api_base": API_BASE}


# Terminal safety
ALLOWED_CMDS = {
    "ls", "cat", "head", "tail", "grep", "rg", "find", "pwd", "whoami", "uname",
    "df", "du", "free", "ps", "top", "htop", "ip", "ss", "ping", "curl", "wget",
    "python", "python3", "node", "npm", "pnpm", "bun", "git", "jq",
}
DENY_PATTERNS = [
    r"\brm\b", r"\bmkfs\b", r"\bdd\b", r"\bshutdown\b", r"\breboot\b", r"\bpoweroff\b",
    r":\(\)\s*\{",  # fork bomb
    r">\s*/dev/sd", r"\bchmod\s+777\b",
]

def tool_terminal_exec(cmd: str, timeout_s: int = 8) -> Json:
    """
    Safer terminal execution:
    - no shell=True
    - allowlist first command
    - denylist pattern scan
    """
    for pat in DENY_PATTERNS:
        if re.search(pat, cmd):
            return {"error": f"blocked by deny rule: {pat}", "cmd": cmd}

    parts = shlex.split(cmd)
    if not parts:
        return {"error": "empty command", "cmd": cmd}

    exe = Path(parts[0]).name
    if exe not in ALLOWED_CMDS:
        return {"error": f"command not allowed: {exe}", "cmd": cmd, "allowed": sorted(ALLOWED_CMDS)}

    try:
        proc = subprocess.run(
            parts,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-6000:],
            "stderr": proc.stderr[-6000:],
        }
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "error": "timeout", "timeout_s": timeout_s}
    except Exception as e:
        return {"cmd": cmd, "error": f"{type(e).__name__}: {e}"}


# ----------------------------
# Agent
# ----------------------------

DEFAULT_SYSTEM = """You are a tool-using agent in a loop.

Rules:
- Only call tools when they help answer the user's question or complete the task.
- Use ONLY the provided tools. Never invent tool names.
- You may call multiple tools in one step.
- If a tool returns an ERROR, correct the tool call arguments and try again.
- Do not repeat identical tool calls unless you need updated data.
- When you have enough info, reply normally without tool calls.
"""


class ToolCallingAgent:
    def __init__(self, config: AgentConfig, registry: ToolRegistry):
        self.cfg = config
        self.client = OllamaClient(config.ollama_host)
        self.registry = registry
        self.selector = ToolSelector(registry)

        # cache tool results by (name, args_json)
        self.cache: Dict[Tuple[str, str], Json] = {}

    def _tool_schemas_for(self, specs: List[ToolSpec]) -> List[Json]:
        return [s.ollama_schema() for s in specs]

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> Json:
        key = (name, json.dumps(args, sort_keys=True))
        if key in self.cache:
            return {"cached": True, "result": self.cache[key]}

        out: Json

        spec = self.registry.get_spec(name)
        fn = self.registry.get_fn(name)
        if not spec or not fn:
            out = {"error": f"tool not available: {name}"}
            self.cache[key] = out
            return out

        ok, err = validate_args(spec.parameters, args)
        if not ok:
            out = {"error": f"invalid arguments: {err}", "expected_schema": spec.parameters}
            self.cache[key] = out
            return out

        # execute
        try:
            res = fn(**args)
            if isinstance(res, str):
                out = {"result": res}
            else:
                out = res if isinstance(res, dict) else {"result": res}
        except Exception as e:
            out = {"error": f"tool crashed: {type(e).__name__}: {e}"}

        self.cache[key] = out
        return out

    def run(self, user_text: str) -> str:
        debug = os.getenv("DEBUG_AGENT") == "1"
        if debug:
            print(f"DEBUG: user_text: {user_text}")
        # Filter tools for THIS query
        selected_specs = self.selector.select(user_text, self.cfg.max_tools_exposed)
        if debug:
            print(f"DEBUG: selected tools: {[s.name for s in selected_specs]}")
        tools_payload = self._tool_schemas_for(selected_specs)
        allowed_tool_names = {s.name for s in selected_specs}

        messages: List[Json] = [
            {"role": "system", "content": DEFAULT_SYSTEM},
            {"role": "user", "content": user_text},
        ]

        invalid_calls = 0
        total_tool_calls = 0
        seen_call_sigs: set[Tuple[str, str]] = set()

        model = self.cfg.main_model

        for step in range(self.cfg.max_steps):
            resp = self.client.chat(
                model=model,
                messages=messages,
                tools=tools_payload,
                stream=self.cfg.stream,
                think=True,
            )

            msg = resp.get("message", {})
            messages.append(msg)

            tool_calls = normalize_tool_calls(msg.get("tool_calls"))

            # fallback: model printed JSON tool call in content
            if not tool_calls and looks_like_tool_json(msg.get("content", "") or ""):
                try:
                    tool_calls = parse_tool_json(msg["content"])
                except Exception:
                    tool_calls = []

            if debug:
                print(f"DEBUG: step {step}: tool_calls: {len(tool_calls)}")
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    print(f"DEBUG: tool call: {fn.get('name')} args: {fn.get('arguments')}")

            # If no tool calls -> final answer
            if not tool_calls:
                return msg.get("content", "") or ""

            # cap tool calls
            tool_calls = tool_calls[: self.cfg.max_tool_calls_per_step]

            for tc in tool_calls:
                if total_tool_calls >= self.cfg.max_total_tool_calls:
                    messages.append({
                        "role": "tool",
                        "tool_name": "system",
                        "content": "ERROR: tool budget exceeded. Provide best-effort answer with current info.",
                    })
                    break

                fn = (tc or {}).get("function") or {}
                name = fn.get("name")
                args = fn.get("arguments") or {}

                if not isinstance(name, str):
                    invalid_calls += 1
                    messages.append({
                        "role": "tool",
                        "tool_name": "system",
                        "content": "ERROR: malformed tool call (missing function.name). Return a corrected tool call.",
                    })
                    continue

                # if model asked for a tool we didn't expose
                if name not in allowed_tool_names:
                    invalid_calls += 1
                    messages.append({
                        "role": "tool",
                        "tool_name": name,
                        "content": f"ERROR: tool '{name}' not available in this context. Use one of: {sorted(allowed_tool_names)}",
                    })
                    continue

                if not isinstance(args, dict):
                    invalid_calls += 1
                    messages.append({
                        "role": "tool",
                        "tool_name": name,
                        "content": "ERROR: arguments must be an object. Return corrected tool call.",
                    })
                    continue

                call_sig = (name, json.dumps(args, sort_keys=True))
                if call_sig in seen_call_sigs:
                    messages.append({
                        "role": "tool",
                        "tool_name": name,
                        "content": "ERROR: duplicate tool call suppressed. Use prior results or vary the query.",
                    })
                    continue
                seen_call_sigs.add(call_sig)

                total_tool_calls += 1

                # Execute tool (with caching + validation)
                out = self._execute_tool(name, args)

                tool_text = truncate(json.dumps(out, ensure_ascii=False), self.cfg.max_tool_output_chars)
                messages.append({
                    "role": "tool",
                    "tool_name": name,
                    "content": tool_text,
                })

            # Escalate if things are going sideways
            if (
                self.cfg.supervisor_model
                and invalid_calls >= self.cfg.max_invalid_calls_before_escalate
                and model != self.cfg.supervisor_model
            ):
                messages.append({
                    "role": "system",
                    "content": "Supervisor mode: fix tool usage. Stop inventing tools/args. Use available tools correctly.",
                })
                model = self.cfg.supervisor_model

        return "Stopped: step limit reached (agent loop)."


# ----------------------------
# Build registry + run demo
# ----------------------------

def build_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(
        ToolSpec(
            name="web_search",
            description="Search the web and retrieve relevant cached chunks via the API.",
            parameters={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Number of results"},
                    "pages": {"type": "integer", "minimum": 1, "maximum": 12, "description": "Pages to fetch"},
                    "domain_whitelist": {"type": "array", "items": {"type": "string"}},
                    "embed_model": {"type": "string"},
                    "force": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            keywords=["web", "latest", "search", "news", "recent", "lookup"],
        ),
        tool_web_search,
    )

    reg.register(
        ToolSpec(
            name="doc_search",
            description="Search indexed documents via the API (RAG retrieval).",
            parameters={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                    "doc_ids": {"type": "array", "items": {"type": "integer"}},
                    "embed_model": {"type": "string"},
                    "use_mmr": {"type": "boolean"},
                    "mmr_lambda": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "additionalProperties": False,
            },
            keywords=["docs", "document", "notes", "search files", "project"],
        ),
        tool_doc_search,
    )

    reg.register(
        ToolSpec(
            name="terminal_exec",
            description="Run a terminal command (restricted allowlist + denylist).",
            parameters={
                "type": "object",
                "required": ["cmd"],
                "properties": {
                    "cmd": {"type": "string", "description": "Command to run"},
                    "timeout_s": {"type": "integer", "minimum": 1, "maximum": 30, "default": 8},
                },
                "additionalProperties": False,
            },
            keywords=["terminal", "shell", "command", "run", "execute", "linux", "arch"],
        ),
        tool_terminal_exec,
    )

    return reg


if __name__ == "__main__":
    cfg = AgentConfig(
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        main_model=os.getenv("OLLAMA_MODEL", "qwen3"),
        supervisor_model=os.getenv("OLLAMA_SUPERVISOR", "") or None,
    )
    agent = ToolCallingAgent(cfg, build_registry())

    print("Ollama Tool Agent ready. Type a prompt and hit enter.\nCtrl+C to exit.\n")
    try:
        while True:
            user = input("> ").strip()
            if not user:
                continue
            out = agent.run(user)
            print("\n" + out + "\n")
    except KeyboardInterrupt:
        print("\nbye")
