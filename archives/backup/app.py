from __future__ import annotations
import os, json, re, time, asyncio, logging, sqlite3
from typing import Any, Optional
from contextlib import asynccontextmanager, contextmanager
from urllib.parse import urlparse, parse_qs, unquote
import uuid, httpx
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
import config, ragstore, chatstore, webstore, researchstore
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
OLLAMA_URL = config.config.ollama_url.rstrip("/")
DEFAULT_EMBED_MODEL = config.config.default_embed_model
DEFAULT_CHAT_MODEL = config.config.default_chat_model
MAX_UPLOAD_BYTES = config.config.max_upload_bytes
_http_client: httpx.AsyncClient | None = None
_CACHE_MAX = int(os.getenv("CACHE_MAX", "256"))
_cache: "dict[str, tuple[Any, float]]" = {}
_cache_lock = asyncio.Lock()
SLASH_COMMANDS = [
    {"cmd": "/help", "args": "", "desc": "Show all commands"},
    {"cmd": "/find", "args": "<query>", "desc": "Search within current chat"},
    {"cmd": "/search", "args": "<query>", "desc": "Search across all chats"},
    {"cmd": "/pin", "args": "", "desc": "Toggle pin for current chat"},
    {"cmd": "/archive", "args": "", "desc": "Toggle archive for current chat"},
    {"cmd": "/summary", "args": "", "desc": "Generate/update chat summary"},
    {"cmd": "/jump", "args": "<msg_id>", "desc": "Jump to a message id"},
    {"cmd": "/clear", "args": "", "desc": "Clear current chat"},
    {"cmd": "/status", "args": "", "desc": "Show system status"},
    {"cmd": "/research","args": "<question>", "desc": "Start research task"},
    {"cmd": "/set", "args": "<key> <value>","desc": "Change settings"},
    {"cmd": "/tags", "args": "", "desc": "Show/manage chat tags"},
    {"cmd": "/tag", "args": "<tag>", "desc": "Add/remove tag from chat"},
    {"cmd": "/trace", "args": "<run_id>", "desc": "Show research trace"},
    {"cmd": "/sources", "args": "<run_id>", "desc": "Show research sources"},
    {"cmd": "/claims", "args": "<run_id>", "desc": "Show research claims"},
    {"cmd": "/autosummary", "args": "", "desc": "Toggle auto-summary"},
]
def _now() -> int:
    """Return current time as integer seconds."""
    return int(time.time())
async def _cached_get(key: str, ttl: int, fetcher) -> Any:
    """Simple async cache with TTL (in seconds)."""
    async with _cache_lock:
        entry = _cache.get(key)
        if entry:
            data, timestamp = entry
            if time.time() - timestamp < ttl:
                return data
        data = await fetcher()
        _cache[key] = (data, time.time())
        # Evict oldest if over limit
        if len(_cache) > _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        return data
def _sanitize_filename(filename: Optional[str]) -> str:
    """Sanitize and normalize uploaded filenames for safe storage."""
    if not filename:
        return "upload.txt"
    name = os.path.basename(filename).strip()
    name = re.sub(r"[^\w\-_.]", "_", name)
    name = name.lstrip(".")[:200] or "upload.txt"
    if not name.lower().endswith((".txt", ".md", ".py", ".js", ".html", ".csv", ".json")):
        name += ".txt"
    return name
def _ddg_unwrap(href: str) -> str | None:
    """Convert DuckDuckGo redirect links to actual target URL."""
    if not href:
        return None
    url = href.strip()
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/"):
        url = "https://duckduckgo.com" + url
    u = urlparse(url)
    if u.netloc.endswith("duckduckgo.com") and u.path.startswith("/l/"):
        qs = parse_qs(u.query)
        uddg = qs.get("uddg", [None])[0]
        if uddg:
            real = unquote(uddg)
            if real.startswith("http"):
                return real
        return None
    return url if url.startswith("http") else None
async def _retry(coro_factory, tries: int = 3, base_delay: float = 0.4):
    """Retry an async operation with exponential backoff."""
    last_exc = None
    for i in range(tries):
        try:
            return await coro_factory()
        except Exception as e:
            last_exc = e
            await asyncio.sleep(base_delay * (2 ** i))
    raise last_exc
def _merge_existing_source_flags(run_id: Optional[str], sources_meta: list[dict]) -> list[dict]:
    """
    Retain user-set flags (e.g., pinned/excluded) when updating research sources.
    """
    if not run_id:
        return sources_meta
    try:
        existing = researchstore.get_sources(run_id) or []
    except Exception:
        existing = []
    by_ref = {str(s.get("ref_id")): s for s in existing if s.get("ref_id")}
    for s in sources_meta:
        ref = str(s.get("ref_id"))
        old = by_ref.get(ref)
        if not old:
            continue
        for flag in ("pinned", "excluded"):
            if flag in old:
                s[flag] = old.get(flag)
    return sources_meta
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan: initialize DBs and HTTP client before startup, and cleanup after shutdown.
    """
    global _http_client
    ragstore.init_db()
    chatstore.init_db()
    webstore.init_db()
    researchstore.init_db()
    _http_client = httpx.AsyncClient(timeout=None)
    try:
        yield
    finally:
        if _http_client:
            await _http_client.aclose()
        _http_client = None
API_KEY = os.getenv("API_KEY")  # If unset, no API key required
app = FastAPI(
    title="CogniHub",
    description="Local-first chat + RAG assistant",
    version="1.0.0",
    lifespan=lifespan
)
@app.middleware("http")
async def auth_and_logging(request: Request, call_next):
    """Middleware: assign request ID, enforce API key, and log requests."""
    req_id = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
    request.state.request_id = req_id
    # API key check for /api and /health routes
    if API_KEY and (request.url.path.startswith("/api/") or request.url.path == "/health"):
        got = request.headers.get("x-api-key") or request.query_params.get("api_key")
        if got != API_KEY:
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    start = time.time()
    try:
        response = await call_next(request)
    finally:
        duration = (time.time() - start) * 1000
        logger.info(f"[{req_id}] {request.method} {request.url.path} {duration:.1f}ms")
    response.headers["x-request-id"] = req_id
    return response
# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/")
async def root():
    """Serve a simple homepage or redirect."""
    return FileResponse("static/showcase.html")
@app.get("/dashboard")
async def dashboard():
    """Serve the main web UI."""
    return FileResponse("static/index.html")
@app.get("/health")
async def health():
    """
    Health check: returns system info and Ollama status. """
    import platform, psutil
    sysinfo: dict[str, Any] = {"platform": platform.system()}
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        sysinfo.update({
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / 2**30, 2),
            "memory_total_gb": round(mem.total / 2**30, 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / 2**30, 2),
        })
    except Exception as e:
        sysinfo["metrics_error"] = str(e)
    return {
        "ok": True,
        "timestamp": _now(),
        "system": sysinfo,
        "services": {"ollama": await api_status()},
    }
@app.get("/api/slash_commands")
async def api_slash_commands():
    """List available slash commands."""
    return {"commands": SLASH_COMMANDS}
@app.get("/api/status")
async def api_status():
    """Get Ollama API status with caching."""
    if not _http_client:
        return {"ok": False, "error": "client not initialized"}
    async def fetch():
        try:
            res = await _http_client.get(f"{OLLAMA_URL}/api/version", timeout=2.5)
            data = res.json()
            return {"ok": True, "version": data.get("version")}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return await _cached_get("status", 60, fetch)
@app.get("/api/models")
async def api_models():
    """List available Ollama models (filtered)."""
    if not _http_client:
        return {"models": [], "error": "client not initialized"}
    async def fetch():
        try:
            res = await _http_client.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
            res.raise_for_status()
            data = res.json()
            models = [m["name"] for m in data.get("models", []) if m.get("name")]
            return {"models": models}
        except Exception as e:
            return {"models": [], "error": str(e)}
    return await _cached_get("models", 30, fetch)
# ---- RAG Documents Endpoints ----
@app.get("/api/docs")
async def docs_list():
    """List uploaded RAG documents."""
    return {"docs": ragstore.list_documents()}
@app.delete("/api/docs/{doc_id}")
async def docs_delete(doc_id: int):
    """Delete a document by ID."""
    ragstore.delete_document(doc_id)
    return {"ok": True}
class DocPatchReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    weight: Optional[float] = None
    group_name: Optional[str] = None
    filename: Optional[str] = None
@app.patch("/api/docs/{doc_id}")
async def docs_patch(doc_id: int, req: DocPatchReq):
    """Update document metadata (weight, group, filename)."""
    ragstore.update_document(
        doc_id,
        weight=req.weight,
        group_name=req.group_name,
        filename=req.filename
    )
    return {"ok": True}
@app.post("/api/docs/upload")
async def docs_upload(file: UploadFile = File(...)):
    """Handle document file uploads."""
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    size = len(raw)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_BYTES} bytes)")
    try:
        text = raw.decode("utf-8")
    except Exception:
        text = raw.decode("utf-8", errors="ignore")
    if not text.strip():
        raise HTTPException(status_code=400, detail="No readable text")
    filename = _sanitize_filename(file.filename)
    doc_id = await ragstore.add_document(filename, text)
    return {"ok": True, "doc_id": doc_id}
@app.get("/api/chunks/{chunk_id}")
async def get_chunk(chunk_id: int):
    """Get a specific text chunk by ID."""
    try:
        return ragstore.get_chunk(chunk_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="chunk not found")
@app.get("/api/chunks/{chunk_id}/neighbors")
async def get_neighbors(chunk_id: int, span: int = 1):
    """Get neighboring chunks for a given chunk ID."""
    try:
        return ragstore.get_neighbors(chunk_id, span=span)
    except KeyError:
        raise HTTPException(status_code=404, detail="chunk not found")
# ---- Chat Management Endpoints ----
class ChatCreateReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = "New Chat"
class ChatPatchReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = None
    archived: Optional[bool] = None
    pinned: Optional[bool] = None
class ChatAppendReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    messages: list[dict]
class EditReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    msg_id: int
    new_content: str
@app.get("/api/chats")
async def api_list_chats(archived: int = 0, q: str | None = None, tag: str | None = None):
    """
    List chats, optionally filtering by archived status, text query, or tag.
    """
    return {"chats": chatstore.list_chats(
        include_archived=bool(archived), query=q, tag=tag
    )}
@app.post("/api/chats")
async def api_create_chat(req: ChatCreateReq):
    """Create a new chat with an optional title."""
    return {"chat": chatstore.create_chat(req.title or "New Chat")}
@app.get("/api/chats/{chat_id}")
async def api_get_chat(chat_id: str, limit: int = 2000, offset: int = 0):
    """
    Retrieve a chat and its messages.
    """
    try:
        limit = max(1, min(limit, 5000))
        offset = max(0, offset)
        return chatstore.get_chat(chat_id, limit=limit, offset=offset)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.patch("/api/chats/{chat_id}")
async def api_patch_chat(chat_id: str, req: ChatPatchReq):
    """Update chat metadata: rename, archive, or pin."""
    try:
        if req.title is not None:
            chatstore.rename_chat(chat_id, req.title)
        if req.archived is not None:
            chatstore.set_archived(chat_id, req.archived)
        if req.pinned is not None:
            chatstore.set_pinned(chat_id, req.pinned)
        return {"ok": True}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.post("/api/chats/{chat_id}/append")
async def api_append(chat_id: str, req: ChatAppendReq):
    """Append messages to a chat."""
    chatstore.append_messages(chat_id, req.messages)
    return {"ok": True}
@app.post("/api/chats/{chat_id}/clear")
async def api_clear_chat(chat_id: str):
    """Clear all messages from a chat."""
    chatstore.clear_chat(chat_id)
    return {"ok": True}
@app.delete("/api/chats/{chat_id}")
async def api_delete_chat(chat_id: str):
    """Delete an entire chat."""
    chatstore.delete_chat(chat_id)
    return {"ok": True}
@app.post("/api/chats/{chat_id}/edit_last")
async def api_edit_last(chat_id: str, req: EditReq):
    """
    Edit a user's message by ID and remove subsequent messages.
    """
    try:
        data = chatstore.get_chat(chat_id, limit=5000, offset=0)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
    msg = next((m for m in data["messages"] if m["id"] == req.msg_id), None)
    if not msg or msg.get("role") != "user":
        raise HTTPException(status_code=400, detail="Invalid message ID for editing")
    await chatstore.trim_after_async(chat_id, req.msg_id)
    await chatstore.update_message_content_async(chat_id, req.msg_id, req.new_content)
    return {"ok": True}
@app.get("/api/export/chat/{chat_id}")
async def export_chat(chat_id: str):
    """Export an entire chat to Markdown format."""
    try:
        markdown = chatstore.export_chat_markdown(chat_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
    return PlainTextResponse(markdown, media_type="text/markdown")
class PrefsReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rag_enabled: Optional[bool] = None
    doc_ids: Any = "__nochange__"
class TagReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tag: str
class SettingsReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: Optional[str] = None
    temperature: Optional[float] = None
    num_ctx: Optional[int] = None
    top_k: Optional[int] = None
    use_mmr: Optional[bool] = None
    mmr_lambda: Optional[float] = None
    autosummary_enabled: Optional[bool] = None
    autosummary_every: Optional[int] = None
@app.get("/api/chats/{chat_id}/prefs")
async def api_get_prefs(chat_id: str):
    """Get RAG preferences for a chat."""
    try:
        return {"prefs": chatstore.get_prefs(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.post("/api/chats/{chat_id}/prefs")
async def api_set_prefs(chat_id: str, req: PrefsReq):
    """Set RAG preferences (enabled, document IDs) for a chat."""
    try:
        chatstore.set_prefs(chat_id, rag_enabled=req.rag_enabled, doc_ids=req.doc_ids)
        return {"ok": True}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.post("/api/chats/{chat_id}/fork")
async def api_fork(chat_id: str, msg_id: int = Query(..., ge=1)):
    """Fork a chat at a given message ID into a new chat."""
    try:
        new_chat = chatstore.fork_chat(chat_id, msg_id)
        return {"chat": new_chat}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1), limit: int = 25, offset: int = 0):
    """Search messages across all chats."""
    hits = chatstore.search_messages(q, chat_id=None, limit=limit, offset=offset)
    return {"hits": hits}
@app.get("/api/chats/{chat_id}/search")
async def api_search_in_chat(chat_id: str, q: str = Query(..., min_length=1), limit: int = 25, offset: int = 0):
    """Search messages within a specific chat."""
    try:
        chatstore.get_chat(chat_id, limit=1, offset=0)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
    hits = chatstore.search_messages(q, chat_id=chat_id, limit=limit, offset=offset)
    return {"hits": hits}
@app.get("/api/chats/{chat_id}/tags")
async def api_get_tags(chat_id: str):
    """List tags for a chat."""
    try:
        chatstore.get_chat(chat_id, limit=1, offset=0)
        return {"tags": chatstore.list_tags(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.post("/api/chats/{chat_id}/tags/add")
async def api_add_tag(chat_id: str, req: TagReq):
    """Add a tag to a chat."""
    try:
        chatstore.get_chat(chat_id, limit=1, offset=0)
        chatstore.add_tag(chat_id, req.tag)
        return {"ok": True, "tags": chatstore.list_tags(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.post("/api/chats/{chat_id}/tags/remove")
async def api_remove_tag(chat_id: str, req: TagReq):
    """Remove a tag from a chat."""
    try:
        chatstore.get_chat(chat_id, limit=1, offset=0)
        chatstore.remove_tag(chat_id, req.tag)
        return {"ok": True, "tags": chatstore.list_tags(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.get("/api/chats/{chat_id}/settings")
async def api_get_settings(chat_id: str):
    """Get chat-specific settings (model, temperature, etc.)."""
    try:
        chatstore.get_chat(chat_id, limit=1, offset=0)
        return {"settings": chatstore.get_settings(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.post("/api/chats/{chat_id}/settings")
async def api_set_settings(chat_id: str, req: SettingsReq):
    """Set chat-specific settings."""
    try:
        chatstore.get_chat(chat_id, limit=1, offset=0)
        chatstore.set_settings(
            chat_id,
            model=req.model,
            temperature=req.temperature,
            num_ctx=req.num_ctx,
            top_k=req.top_k,
            use_mmr=req.use_mmr,
            mmr_lambda=req.mmr_lambda,
            autosummary_enabled=req.autosummary_enabled,
            autosummary_every=req.autosummary_every
        )
        return {"ok": True, "settings": chatstore.get_settings(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.get("/api/chats/{chat_id}/jump")
async def api_jump(chat_id: str, msg_id: int = Query(..., ge=1), span: int = 20):
    """Get context around a message ID in a chat."""
    try:
        return chatstore.get_message_context(chat_id, msg_id, span=span)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
@app.post("/api/chats/{chat_id}/summary")
async def api_summary(chat_id: str):
    """
    Generate/update summary of the chat via Ollama and append it as a message.
    """
    try:
        data = chatstore.get_chat(chat_id, limit=config.config.max_summary_messages, offset=0)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
    msgs = data["messages"][-config.config.max_summary_messages:]
    text_body = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)
    settings = chatstore.get_settings(chat_id)
    model = settings.get("model") or DEFAULT_CHAT_MODEL
    temp = settings.get("temperature")
    num_ctx = settings.get("num_ctx")
    prompt = (
        "Summarize this chat in 8-12 bullet points, then list 5 actionable next steps.\n\n"
        + text_body
    )
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    opts: dict[str, Any] = {}
    if temp is not None:
        opts["temperature"] = temp
    if num_ctx is not None:
        opts["num_ctx"] = int(num_ctx)
    if opts:
        payload["options"] = opts
    try:
        if not _http_client:
            raise HTTPException(status_code=503, detail="client not initialized")
        res = await _http_client.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=60.0)
        res.raise_for_status()
        content = (res.json().get("message") or {}).get("content", "").strip()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"summary failed: {e}")
    chatstore.append_messages(chat_id, [{
        "role": "assistant",
        "content": content,
        "model": model,
        "meta_json": {"summary": True}
    }])
    return {"ok": True, "summary": content}
@app.post("/api/chats/{chat_id}/autosummary")
async def api_autosummary(chat_id: str, force: int = 0):
    """
    Perform or skip auto-summary of recent messages if enabled.
    """
    try:
        data = chatstore.get_chat(chat_id, limit=5000, offset=0)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
    settings = chatstore.get_settings(chat_id)
    enabled = bool(settings.get("autosummary_enabled") or 0)
    every = int(settings.get("autosummary_every") or config.config.default_autosummary_every)
    last_done = settings.get("autosummary_last_msg_id")
    if not force and not enabled:
        return {"ok": True, "skipped": True, "reason": "disabled"}
    msgs = data["messages"]
    if len([m for m in msgs if m["role"] in ("user", "assistant")]) < config.config.min_autosummary_messages:
        return {"ok": True, "skipped": True, "reason": "too short"}
    latest_id = int(msgs[-1]["id"])
    if not force and last_done is not None:
        # Determine how many new messages since last summary
        idx = next((i for i, m in enumerate(msgs) if int(m["id"]) == int(last_done)), None)
        if idx is not None:
            new_count = len(msgs) - (idx + 1)
            if new_count < every:
                return {"ok": True, "skipped": True, "reason": f"need {every - new_count} more msgs"}
    # Build prompt using last up to 80 messages
    relevant = msgs[-min(80, len(msgs)):]
    body = "\n".join(f"{m['role']}: {m['content']}" for m in relevant)
    model = settings.get("model") or DEFAULT_CHAT_MODEL
    temp = settings.get("temperature")
    num_ctx = settings.get("num_ctx")
    prompt = (
        "Make a running summary of the conversation so far.\n"
        "Output:\n"
        "1) 8-12 bullet points of key facts/decisions\n"
        "2) Open questions (if any)\n"
        "3) Next actions (3-6)\n\n"
        "Chat window:\n" + body
    )
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    opts: dict[str, Any] = {}
    if temp is not None:
        opts["temperature"] = float(temp)
    if num_ctx is not None:
        opts["num_ctx"] = int(num_ctx)
    if opts:
        payload["options"] = opts
    try:
        if not _http_client:
            raise HTTPException(status_code=503, detail="client not initialized")
        res = await _http_client.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90.0)
        res.raise_for_status()
        content = (res.json().get("message") or {}).get("content", "").strip()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"autosummary failed: {e}")
    chatstore.append_messages(chat_id, [{
        "role": "assistant",
        "content": content,
        "model": model,
        "meta_json": {"autosummary": True}
    }])
    chatstore.set_settings(chat_id, autosummary_last_msg_id=latest_id)
    return {"ok": True, "summary": content, "latest_id": latest_id}
@app.post("/api/chats/{chat_id}/toggle_pin")
async def api_toggle_pin(chat_id: str):
    """Toggle the pinned status of a chat."""
    try:
        return {"ok": True, **chatstore.toggle_pinned(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
@app.post("/api/chats/{chat_id}/toggle_archive")
async def api_toggle_archive(chat_id: str):
    """Toggle the archived status of a chat."""
    try:
        return {"ok": True, **chatstore.toggle_archived(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")