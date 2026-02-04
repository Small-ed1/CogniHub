from __future__ import annotations

import os, json, re, time, asyncio, logging, uuid
from pathlib import Path
from typing import Optional, Any, cast, Dict
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict

from . import config
from .stores import ragstore
from .stores import chatstore
from .stores import researchstore
from .stores import webstore
from .services.chat import stream_chat
from .services.tool_chat import chat_with_tool_contract
from .services.intelligent_chat import should_use_intelligent_tools, stream_chat_intelligent
import asyncio

from .services.kiwix import fetch_page as kiwix_fetch_page
from .services.kiwix import list_zims as kiwix_list_zims
from .services.kiwix import search as kiwix_search
from .ingest import epub as epub_ingest
from .services.models import ModelRegistry
from .services.research import run_research
from .services.tooling import ToolDocSearchReq, ToolWebSearchReq, chat_with_tools, tool_doc_search, tool_web_search
from .services.web_ingest import WebIngestQueue
from .toolstore import ToolStore
from .tools.registry import ToolRegistry
from .tools.executor import ToolExecutor
from .tools import builtin


def ensure_db_dirs():
    """Ensure all database parent directories exist."""
    for db_path in [
        config.config.rag_db,
        config.config.chat_db,
        config.config.web_db,
        config.config.research_db,
        config.config.tool_db,
    ]:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

OLLAMA_URL = config.config.ollama_url
DEFAULT_EMBED_MODEL = config.config.default_embed_model
DEFAULT_CHAT_MODEL = config.config.default_chat_model
MAX_UPLOAD_BYTES = config.config.max_upload_bytes

_http: httpx.AsyncClient | None = None
_model_registry = ModelRegistry(config.config.ollama_url)
_web_ingest = WebIngestQueue(concurrency=3)

# Simple in-memory cache
_cache: dict[str, tuple[Any, float]] = {}
_cache_lock = asyncio.Lock()

SLASH_COMMANDS = [
    {"cmd": "/help",    "args": "",           "desc": "Show all commands"},
    {"cmd": "/find",    "args": "<query>",    "desc": "Search within current chat"},
    {"cmd": "/search",  "args": "<query>",    "desc": "Search across all chats"},
    {"cmd": "/pin",     "args": "",           "desc": "Toggle pin for current chat"},
    {"cmd": "/archive", "args": "",           "desc": "Toggle archive for current chat"},
    {"cmd": "/summary", "args": "",           "desc": "Generate/update chat summary"},
    {"cmd": "/jump",    "args": "<msg_id>",   "desc": "Jump to a message id"},
    {"cmd": "/clear",   "args": "",           "desc": "Clear current chat"},
    {"cmd": "/status",  "args": "",           "desc": "Show system status"},
    {"cmd": "/research", "args": "<question>", "desc": "Start research task"},
    {"cmd": "/set",     "args": "<key> <value>", "desc": "Change settings"},
    {"cmd": "/tags",    "args": "",           "desc": "Show/manage chat tags"},
    {"cmd": "/tag",     "args": "<tag>",      "desc": "Add/remove tag from chat"},
    {"cmd": "/trace",   "args": "<run_id>",   "desc": "Show research trace"},
    {"cmd": "/sources", "args": "<run_id>",   "desc": "Show research sources"},
    {"cmd": "/claims",  "args": "<run_id>",   "desc": "Show research claims"},
    {"cmd": "/autosummary", "args": "",       "desc": "Toggle auto-summary"},
]

def _now():
    return int(time.time())

async def _cached_get(key: str, ttl: int, fetcher):
    """Simple cache with TTL"""
    async with _cache_lock:
        if key in _cache:
            data, timestamp = _cache[key]
            if time.time() - timestamp < ttl:
                return data
        data = await fetcher()
        _cache[key] = (data, time.time())
        return data

def _sanitize_filename(filename: str | None) -> str:
    if not filename:
        return "upload.txt"
    filename = filename.strip()
    filename = os.path.basename(filename)
    filename = re.sub(r"[^\w\-_.]", "_", filename)
    filename = filename.lstrip(".")
    filename = filename[:200] or "upload.txt"
    if not any(filename.lower().endswith(ext) for ext in [".txt", ".md", ".py", ".js", ".html", ".csv", ".json"]):
        filename = filename + ".txt"
    return filename


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http

    # Ensure all DB directories exist
    ensure_db_dirs()

    ragstore.init_db()
    chatstore.init_db()
    webstore.init_db()
    researchstore.init_db()

    _http = httpx.AsyncClient(timeout=None)
    await _web_ingest.start()

    # Initialize tool system (after _http and _web_ingest are ready)
    app.state.toolstore = ToolStore()
    app.state.tool_registry = ToolRegistry()
    builtin.register_builtin_tools(
        app.state.tool_registry,
        http=_http,
        ingest_queue=_web_ingest,
        embed_model=config.config.default_embed_model,
        kiwix_url=os.getenv("KIWIX_URL"),
    )
    app.state.tool_executor = ToolExecutor(app.state.tool_registry, app.state.toolstore)

    try:
        yield
    finally:
        if _http:
            await _http.aclose()
            _http = None
        await _web_ingest.stop()

app = FastAPI(lifespan=lifespan)
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../web/static"))
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/health")
async def health():
    import psutil
    import platform

    try:
        # System metrics
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        return {
            "ok": True,
            "timestamp": _now(),
            "system": {
                "platform": platform.system(),
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_used_gb": round(memory.used / (1024**3), 2),
                "memory_total_gb": round(memory.total / (1024**3), 2),
                "disk_percent": disk.percent,
                "disk_free_gb": round(disk.free / (1024**3), 2),
            },
            "services": {
                "ollama": await api_status(),
            }
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/slash_commands")
async def api_slash_commands():
    return {"commands": SLASH_COMMANDS}

@app.get("/api/status")
async def api_status():
    if not _http:
        return {"ok": False, "error": "client not initialized"}
    http = _http

    async def fetch_status():
        try:
            v = await http.get(f"{OLLAMA_URL}/api/version", timeout=2.5)
            ver = cast(Dict, v.json()).get("version")
            return {"ok": True, "version": ver}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return await _cached_get("status", 60, fetch_status)  # Cache for 60 seconds

@app.get("/api/models")
async def api_models():
    if not _http:
        return {"models": [], "error": "client not initialized"}
    http = _http

    async def fetch_models():
        try:
            models = await _model_registry.list_models(http)
            return {"models": [m.name for m in models]}
        except Exception as e:
            return {"models": [], "error": str(e)}

    return await _cached_get("models", 30, fetch_models)  # Cache for 30 seconds

# ---------------- docs ----------------

@app.get("/api/docs")
async def docs_list():
    return {"docs": ragstore.list_documents()}

@app.delete("/api/docs/{doc_id}")
async def docs_delete(doc_id: int):
    ragstore.delete_document(doc_id)
    return {"ok": True}

class DocPatchReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    weight: Optional[float] = None
    group_name: Optional[str] = None
    filename: Optional[str] = None

@app.patch("/api/docs/{doc_id}")
async def docs_patch(doc_id: int, req: DocPatchReq):
    ragstore.update_document(doc_id, weight=req.weight, group_name=req.group_name, filename=req.filename)
    return {"ok": True}

@app.post("/api/docs/upload")
async def docs_upload(file: UploadFile = File(...)):
    total = 0
    chunk_size = 8192
    chunks = []
    
    while total < MAX_UPLOAD_BYTES:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            chunks = chunks[:-1]
            total -= len(chunk)
            logger.warning(f"File upload too large: {total} bytes (max {MAX_UPLOAD_BYTES})")
            raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_BYTES} bytes)")
    
    if total == 0:
        logger.warning("Empty file upload attempt")
        raise HTTPException(status_code=400, detail="Empty file")
    
    raw = b"".join(chunks)
    try:
        text = raw.decode("utf-8")
    except Exception:
        text = raw.decode("utf-8", errors="ignore")
    
    if not text.strip():
        logger.warning("File contains no readable text")
        raise HTTPException(status_code=400, detail="No readable text")
    
    safe_filename = _sanitize_filename(file.filename)
    logger.info(f"Uploading document: {safe_filename} ({total} bytes)")
    doc_id = await ragstore.add_document(safe_filename, text)
    return {"ok": True, "doc_id": doc_id}

@app.post("/api/tools/doc_search")
async def api_tool_doc_search(req: ToolDocSearchReq):
    try:
        return await tool_doc_search(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.post("/api/tools/web_search")
async def api_tool_web_search(req: ToolWebSearchReq):
    if not _http:
        raise HTTPException(status_code=503, detail="client not initialized")
    try:
        return await tool_web_search(
            req,
            http=_http,
            ingest_queue=_web_ingest,
            embed_model=DEFAULT_EMBED_MODEL,
            kiwix_url=config.config.kiwix_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

class KiwixSearchReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str
    top_k: int = 8

@app.post("/api/kiwix/search")
async def api_kiwix_search(req: KiwixSearchReq):
    kiwix_url = config.config.kiwix_url
    if not kiwix_url:
        return {"results": [], "error": "KIWIX_URL not set"}
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    results = await kiwix_search(kiwix_url, query, top_k=req.top_k)
    return {"results": results}

@app.get("/api/kiwix/page")
async def api_kiwix_page(path: str = Query(..., min_length=1)):
    kiwix_url = config.config.kiwix_url
    if not kiwix_url:
        return {"page": None, "error": "KIWIX_URL not set"}
    page = await kiwix_fetch_page(kiwix_url, path)
    if not page:
        raise HTTPException(status_code=404, detail="page not found")
    return {"page": page}


@app.get("/api/kiwix/zims")
async def api_kiwix_zims(zim_dir: Optional[str] = Query(default=None)):
    zims = await kiwix_list_zims(zim_dir or config.config.kiwix_zim_dir)
    return {"zim_dir": zim_dir or config.config.kiwix_zim_dir, "zims": zims}


class EpubIngestReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: Optional[str] = None
    query: Optional[str] = None
    limit: int = 1
    library_dir: Optional[str] = None


@app.get("/api/epubs")
async def api_epubs_list(
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    library_dir: Optional[str] = Query(default=None, max_length=1024),
):
    items = await asyncio.to_thread(
        epub_ingest.list_epubs,
        query=q,
        limit=limit,
        library_dir=library_dir or config.config.ebooks_dir,
    )
    return {"library_dir": library_dir or config.config.ebooks_dir, "items": items}


@app.post("/api/epubs/ingest")
async def api_epubs_ingest(req: EpubIngestReq):
    library_dir = (req.library_dir or "").strip() or config.config.ebooks_dir
    if req.path:
        return await epub_ingest.ingest_epub(
            path=req.path,
            embed_model=DEFAULT_EMBED_MODEL,
            library_dir=library_dir,
        )
    if req.query:
        return await epub_ingest.ingest_epubs_by_query(
            query=req.query,
            limit=req.limit,
            embed_model=DEFAULT_EMBED_MODEL,
            library_dir=library_dir,
        )
    raise HTTPException(status_code=400, detail="path or query required")

@app.get("/api/chunks/{chunk_id}")
async def get_chunk(chunk_id: int):
    try:
        return ragstore.get_chunk(chunk_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="chunk not found")

@app.get("/api/chunks/{chunk_id}/neighbors")
async def get_neighbors(chunk_id: int, span: int = 1):
    try:
        return ragstore.get_neighbors(chunk_id, span=span)
    except KeyError:
        raise HTTPException(status_code=404, detail="chunk not found")

# ---------------- chats ----------------

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
    return {"chats": chatstore.list_chats(include_archived=bool(archived), q=q, tag=tag)}

@app.post("/api/chats")
async def api_create_chat(req: ChatCreateReq):
    return {"chat": chatstore.create_chat(req.title or "New Chat")}

@app.get("/api/chats/{chat_id}")
async def api_get_chat(chat_id: str, limit: int = 2000, offset: int = 0):
    limit = max(1, min(limit, 5000))
    offset = max(0, offset)
    try:
        return chatstore.get_chat(chat_id, limit=limit, offset=offset)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

@app.patch("/api/chats/{chat_id}")
async def api_patch_chat(chat_id: str, req: ChatPatchReq):
    if req.title is not None:
        chatstore.rename_chat(chat_id, req.title)
    if req.archived is not None:
        chatstore.set_archived(chat_id, req.archived)
    if req.pinned is not None:
        chatstore.set_pinned(chat_id, req.pinned)
    return {"ok": True}

@app.post("/api/chats/{chat_id}/append")
async def api_append(chat_id: str, req: ChatAppendReq):
    chatstore.append_messages(chat_id, req.messages)
    return {"ok": True}

@app.post("/api/chats/{chat_id}/clear")
async def api_clear_chat(chat_id: str):
    chatstore.clear_chat(chat_id)
    return {"ok": True}

@app.delete("/api/chats/{chat_id}")
async def api_delete_chat(chat_id: str):
    chatstore.delete_chat(chat_id)
    return {"ok": True}

@app.post("/api/chats/{chat_id}/edit_last")
async def api_edit_and_trim(chat_id: str, req: EditReq):
    try:
        data = chatstore.get_chat(chat_id, limit=5000, offset=0)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

    msg = next((m for m in data["messages"] if int(m["id"]) == int(req.msg_id)), None)
    if not msg:
        raise HTTPException(status_code=404, detail="message not found")
    if msg.get("role") != "user":
        raise HTTPException(status_code=400, detail="can only edit user messages")

    await chatstore.trim_after_async(chat_id, int(req.msg_id))
    await chatstore.update_message_content_async(chat_id, int(req.msg_id), req.new_content)

    return {"ok": True}

@app.get("/api/export/chat/{chat_id}")
async def export_chat(chat_id: str):
    try:
        md = chatstore.export_chat_markdown(chat_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
    return PlainTextResponse(md, media_type="text/markdown")

class PrefsReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rag_enabled: Optional[bool] = None
    doc_ids: Any = "__nochange__"

class TagReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tag: str

class SettingsReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str | None = None
    temperature: float | None = None
    num_ctx: int | None = None
    top_k: int | None = None
    use_mmr: bool | None = None
    mmr_lambda: float | None = None
    autosummary_enabled: bool | None = None
    autosummary_every: int | None = None

@app.get("/api/chats/{chat_id}/prefs")
async def api_get_prefs(chat_id: str):
    try:
        return {"prefs": chatstore.get_prefs(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

@app.post("/api/chats/{chat_id}/prefs")
async def api_set_prefs(chat_id: str, req: PrefsReq):
    try:
        chatstore.set_prefs(chat_id, rag_enabled=req.rag_enabled, doc_ids=req.doc_ids)
        return {"ok": True}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

@app.post("/api/chats/{chat_id}/fork")
async def api_fork(chat_id: str, msg_id: int = Query(..., ge=1)):
    try:
        new_chat = chatstore.fork_chat(chat_id, msg_id)
        return {"chat": new_chat}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

# -------- search endpoints --------

@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1), limit: int = 25, offset: int = 0):
    hits = chatstore.search_messages(q, chat_id=None, limit=limit, offset=offset)
    return {"hits": hits}

@app.get("/api/chats/{chat_id}/search")
async def api_search_in_chat(chat_id: str, q: str = Query(..., min_length=1), limit: int = 25, offset: int = 0):
    try:
        _ = chatstore.get_chat(chat_id, limit=1, offset=0)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
    hits = chatstore.search_messages(q, chat_id=chat_id, limit=limit, offset=offset)
    return {"hits": hits}

# -------- tags endpoints --------

@app.get("/api/chats/{chat_id}/tags")
async def api_get_tags(chat_id: str):
    try:
        _ = chatstore.get_chat(chat_id, limit=1, offset=0)
        return {"tags": chatstore.list_tags(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

@app.post("/api/chats/{chat_id}/tags/add")
async def api_add_tag(chat_id: str, req: TagReq):
    try:
        _ = chatstore.get_chat(chat_id, limit=1, offset=0)
        chatstore.add_tag(chat_id, req.tag)
        return {"ok": True, "tags": chatstore.list_tags(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

@app.post("/api/chats/{chat_id}/tags/remove")
async def api_remove_tag(chat_id: str, req: TagReq):
    try:
        _ = chatstore.get_chat(chat_id, limit=1, offset=0)
        chatstore.remove_tag(chat_id, req.tag)
        return {"ok": True, "tags": chatstore.list_tags(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

# -------- settings endpoints --------

@app.get("/api/chats/{chat_id}/settings")
async def api_get_settings(chat_id: str):
    try:
        _ = chatstore.get_chat(chat_id, limit=1, offset=0)
        return {"settings": chatstore.get_settings(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

@app.post("/api/chats/{chat_id}/settings")
async def api_set_settings(chat_id: str, req: SettingsReq):
    try:
        _ = chatstore.get_chat(chat_id, limit=1, offset=0)
        chatstore.set_settings(
            chat_id,
            model=req.model,
            temperature=req.temperature,
            num_ctx=req.num_ctx,
            top_k=req.top_k,
            use_mmr=req.use_mmr,
            mmr_lambda=req.mmr_lambda,
            autosummary_enabled=req.autosummary_enabled,
            autosummary_every=req.autosummary_every,
        )
        return {"ok": True, "settings": chatstore.get_settings(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

# -------- jump endpoint --------

@app.get("/api/chats/{chat_id}/jump")
async def api_jump(chat_id: str, msg_id: int = Query(..., ge=1), span: int = 20):
    try:
        return chatstore.get_message_context(chat_id, msg_id, span=span)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")

# -------- summary endpoint --------

@app.post("/api/chats/{chat_id}/summary")
async def api_summary(chat_id: str):
    try:
        data = chatstore.get_chat(chat_id, limit=2000, offset=0)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

    msgs = data["messages"][-config.config.max_summary_messages:]
    body = "\n".join([f"{m['role']}: {m['content']}" for m in msgs])

    settings = chatstore.get_settings(chat_id)
    model = settings.get("model") or os.getenv("DEFAULT_CHAT_MODEL") or "llama3.1"
    temp = settings.get("temperature")
    num_ctx = settings.get("num_ctx")

    prompt = (
        "Summarize this chat in 8-12 bullet points, then list 5 actionable next steps.\n\n"
        + body
    )

    try:
        if not _http:
            raise HTTPException(status_code=503, detail="client not initialized")
        opts = {}
        if temp is not None:
            opts["temperature"] = temp
        if num_ctx is not None:
            opts["num_ctx"] = int(num_ctx)
        out = await chat_with_tools(
            http=_http,
            ollama_url=OLLAMA_URL,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options=opts or None,
            embed_model=DEFAULT_EMBED_MODEL,
            ingest_queue=_web_ingest,
            kiwix_url=os.getenv("KIWIX_URL"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"summary failed: {e}")

    chatstore.append_messages(chat_id, [{
        "role": "assistant",
        "content": out,
        "model": model,
        "meta_json": {"summary": True}
    }])
    return {"ok": True, "summary": out}

# -------- autosummary endpoint --------

@app.post("/api/chats/{chat_id}/autosummary")
async def api_autosummary(chat_id: str, force: int = 0):
    try:
        data = chatstore.get_chat(chat_id, limit=5000, offset=0)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

    settings = chatstore.get_settings(chat_id)
    enabled = bool(settings.get("autosummary_enabled") or 0)
    every = int(settings.get("autosummary_every") or 12)
    last_done = settings.get("autosummary_last_msg_id")

    if not force and not enabled:
        return {"ok": True, "skipped": True, "reason": "disabled"}

    msgs = data["messages"]
    if not msgs:
        return {"ok": True, "skipped": True, "reason": "no messages"}

    ua = [m for m in msgs if m.get("role") in ("user", "assistant")]
    if len(ua) < 4:
        return {"ok": True, "skipped": True, "reason": "too short"}

    latest_id = int(msgs[-1]["id"])
    if not force and last_done is not None:
        idx = None
        for i, m in enumerate(ua):
            if int(m["id"]) == int(last_done):
                idx = i
                break
        if idx is not None:
            new_count = len(ua) - (idx + 1)
            if new_count < every:
                return {"ok": True, "skipped": True, "reason": f"need {every-new_count} more msgs"}

    window = ua[-min(80, len(ua)):]
    body = "\n".join([f"{m['role']}: {m['content']}" for m in window])

    model = settings.get("model") or os.getenv("DEFAULT_CHAT_MODEL") or "llama3.1"
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

    try:
        if not _http:
            raise HTTPException(status_code=503, detail="client not initialized")
        opts = {}
        if temp is not None:
            opts["temperature"] = float(temp)
        if num_ctx is not None:
            opts["num_ctx"] = int(num_ctx)
        out = await chat_with_tools(
            http=_http,
            ollama_url=OLLAMA_URL,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options=opts or None,
            embed_model=DEFAULT_EMBED_MODEL,
            ingest_queue=_web_ingest,
            kiwix_url=os.getenv("KIWIX_URL"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"autosummary failed: {e}")

    chatstore.append_messages(chat_id, [{
        "role": "assistant",
        "content": out,
        "model": model,
        "meta_json": {"autosummary": True}
    }])

    chatstore.set_settings(chat_id, autosummary_last_msg_id=latest_id)

    return {"ok": True, "summary": out, "latest_id": latest_id}

@app.post("/api/chats/{chat_id}/toggle_pin")
async def api_toggle_pin(chat_id: str):
    try:
        return {"ok": True, **chatstore.toggle_pinned(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

@app.post("/api/chats/{chat_id}/toggle_archive")
async def api_toggle_archive(chat_id: str):
    try:
        return {"ok": True, **chatstore.toggle_archived(chat_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")

# ---------------- model decider ----------------

class DecideReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str
    rag_enabled: bool = False

def _guess_task(query: str) -> str:
    q = (query or "").lower()
    if any(k in q for k in ["stack trace","traceback","error","refactor","bug","uvicorn","fastapi","docker","arch","systemd","regex"]):
        return "coding"
    if any(k in q for k in ["summarize","explain","write","essay","outline"]):
        return "writing"
    return "general"

def _extract_json_obj(s: str):
    return _json_obj_from_text(s)

def _json_obj_from_text(s: str, max_size: int = config.config.max_json_parse_size) -> Any:
    s = (s or "")
    if not s or len(s) > max_size:
        return None
    
    for i, ch in enumerate(s):
        if ch == "{":
            depth = 0
            in_string = False
            escape_next = False
            
            for j in range(i, min(len(s), i + max_size)):
                c = s[j]
                if escape_next:
                    escape_next = False
                elif c == "\\":
                    escape_next = True
                elif c == '"':
                    in_string = not in_string
                elif not in_string:
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            json_str = s[i:j+1]
                            try:
                                return json.loads(json_str)
                            except json.JSONDecodeError:
                                break
            break
    return None

@app.post("/api/decide_model")
async def decide_model(req: DecideReq):
    if not _http:
        return {"model": None, "auto": False, "error": "client not initialized"}
    try:
        models = await _model_registry.list_models(_http)
    except Exception as e:
        return {"model": None, "auto": False, "error": f"tags failed: {e}"}

    installed: list[dict[str, Any]] = []
    for m in models:
        name = m.name
        if not name:
            continue
        if "embed" in name.lower(): continue
        installed.append({"name": name, "size": int(m.size or 0)})

    if not installed:
        return {"model": None, "auto": False, "error": "No chat models installed"}

    installed.sort(key=lambda x: int(x.get("size") or 0))
    allowed = [m["name"] for m in installed]

    decider = os.getenv("DECIDER_MODEL")
    decider_model = decider if decider in allowed else allowed[0]

    task = _guess_task(req.query)
    prompt = (
        "Pick the best model from allowed list. Return ONLY JSON like "
        "{\"model\":\"<one of allowed>\"}.\n\n"
        f"Allowed: {allowed}\n"
        f"Task: {task}\n"
        f"RAG: {req.rag_enabled}\n"
        f"Query: {req.query}\n"
    )

    try:
        r = await _http.post(f"{OLLAMA_URL}/api/chat", json={
            "model": decider_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }, timeout=20.0)
        r.raise_for_status()
        content = (r.json().get("message") or {}).get("content", "")
    except Exception:
        if task == "coding" or len(req.query) > 700:
            return {"model": allowed[-1], "auto": False, "reason": "fallback largest"}
        return {"model": allowed[len(allowed)//2], "auto": False, "reason": "fallback mid"}

    obj = _extract_json_obj(content) or {}
    picked = obj.get("model")
    if picked in allowed:
        return {"model": picked, "auto": True, "decider": decider_model}

    if task == "coding" or len(req.query) > 700:
        return {"model": allowed[-1], "auto": False, "reason": "bad_json largest"}
    return {"model": allowed[len(allowed)//2], "auto": False, "reason": "bad_json mid"}

# ---------------- chat stream + rag ----------------

class RagConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    # retrieval selection
    use_docs: bool = True
    use_web: bool = False
    use_kiwix: bool = False

    # kiwix (ZIM) behavior
    kiwix_persist: bool = True
    kiwix_pages: int = Field(default=4, ge=1, le=10)

    # optional router (choose sources + rewrite queries)
    auto_route: bool = False
    router_model: str | None = None
    router_timeout_sec: float = Field(default=12.0, ge=3.0, le=60.0)

    # retrieval sizing
    top_k: int = Field(default=12, ge=1, le=20)
    doc_top_k: int | None = Field(default=None, ge=1, le=40)
    web_top_k: int | None = Field(default=None, ge=1, le=40)
    kiwix_top_k: int | None = Field(default=None, ge=1, le=40)
    per_source_cap: int = Field(default=6, ge=1, le=20)
    max_context_chars: int = Field(default=8000, ge=2000, le=60000)

    # doc constraints
    doc_ids: list[int] | None = None
    doc_group: str | None = None
    doc_source: str | None = None

    # web constraints
    domain_whitelist: list[str] | None = None

    # embedding + ranking
    embed_model: str | None = None
    use_mmr: bool = False
    mmr_lambda: float = 0.75

    # quality knobs
    rerank: bool = False
    rerank_model: str | None = None
    rerank_keep_n: int = Field(default=24, ge=4, le=60)

    require_citations: bool = True
    citation_retry: bool = True
    citation_retry_timeout_sec: float = Field(default=20.0, ge=5.0, le=120.0)

    # optional synthesis pass (use a different model for final answer)
    synth: bool = False
    synth_model: str | None = None
    synth_timeout_sec: float = Field(default=60.0, ge=5.0, le=600.0)

class ChatReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    messages: list[dict]
    options: dict | None = None
    keep_alive: str | None = None
    rag: RagConfig | None = None
    chat_id: str | None = None
    message_id: str | None = None
    use_intelligent_tools: bool = False


@app.post("/api/chat")
async def api_chat(req: ChatReq, request: Request):
    if not _http:
        raise HTTPException(503, "Client not initialized")
    http = _http

    # Generate IDs if not provided
    chat_id = req.chat_id or str(uuid.uuid4())
    message_id = req.message_id or str(uuid.uuid4())

    async def stream():
        try:
            # Emit IDs first
            yield json.dumps({"type": "ids", "chat_id": chat_id, "message_id": message_id}) + "\n"
            
            # Decide whether to use intelligent tool system
            use_intelligent = should_use_intelligent_tools(req.messages, req.use_intelligent_tools)
            
            if use_intelligent:
                # Use the new intelligent tool-calling system
                logger.info(f"Using intelligent tool system for chat_id={chat_id}")
                result = await stream_chat_intelligent(
                    http=http,
                    ollama_url=OLLAMA_URL,
                    model=req.model,
                    messages=req.messages,
                    options=req.options,
                    keep_alive=req.keep_alive,
                    embed_model=DEFAULT_EMBED_MODEL,
                    tool_registry=app.state.tool_registry,
                    tool_executor=app.state.tool_executor,
                    kiwix_url=os.getenv("KIWIX_URL"),
                    chat_id=chat_id,
                    message_id=message_id,
                )
                yield result
            else:
                # Use the existing tool system
                logger.info(f"Using legacy tool system for chat_id={chat_id}")
                stream_gen = stream_chat(
                    http=http,
                    model_registry=_model_registry,
                    ollama_url=OLLAMA_URL,
                    model=req.model,
                    messages=req.messages,
                    options=req.options,
                    keep_alive=req.keep_alive,
                    rag=req.rag.model_dump() if req.rag else None,
                    embed_model=DEFAULT_EMBED_MODEL,
                    web_ingest=_web_ingest,
                    kiwix_url=os.getenv("KIWIX_URL"),
                    request=request,
                    chat_id=chat_id,
                    message_id=message_id,
                )
                async for line in stream_gen:
                    yield line
        except Exception as e:
            yield json.dumps({"type": "error", "error": str(e)}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")

# -------- web pages endpoints --------

class WebUpsertReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str
    force: bool = False

@app.get("/api/web/pages")
async def api_web_pages(limit: int = 50, offset: int = 0, domain: str | None = None):
    return {"pages": webstore.list_pages(limit=limit, offset=offset, domain=domain)}

@app.post("/api/web/upsert")
async def api_web_upsert(req: WebUpsertReq):
    try:
        page = await webstore.upsert_page_from_url(req.url, force=bool(req.force))
        return {"ok": True, "page": page}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/web/chunks/{chunk_id}")
async def api_web_chunk(chunk_id: int):
    try:
        return webstore.get_chunk(chunk_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="chunk not found")

@app.get("/api/web/chunks/{chunk_id}/neighbors")
async def api_web_neighbors(chunk_id: int, span: int = 1):
    try:
        return webstore.get_neighbors(chunk_id, span=span)
    except KeyError:
        raise HTTPException(status_code=404, detail="chunk not found")

# -------- deep research endpoints --------

class ResearchReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chat_id: str | None = None
    query: str
    mode: str = "deep"
    use_docs: bool = True
    use_web: bool = True
    rounds: int = 3
    pages_per_round: int = 5
    web_top_k: int = 6
    doc_top_k: int = 6
    domain_whitelist: list[str] | None = None
    embed_model: str | None = None
    planner_model: str | None = None
    verifier_model: str | None = None
    synth_model: str | None = None

async def _ollama_chat_once(model: str, messages: list[dict], timeout: float = 60.0) -> str:
    if not _http:
        raise HTTPException(status_code=503, detail="client not initialized")
    payload = {"model": model, "messages": messages, "stream": False}
    r = await _http.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    return ((r.json().get("message") or {}).get("content") or "").strip()

def _format_sources_for_prompt(doc_hits: list[dict], web_hits: list[dict]) -> tuple[list[dict], list[str]]:
    sources_meta = []
    context_lines = []

    i = 1
    for h in doc_hits:
        tag = f"D{i}"
        sources_meta.append({
            "source_type": "doc",
            "ref_id": f"doc:{h['chunk_id']}",
            "title": h.get("filename"),
            "url": None,
            "domain": None,
            "score": h.get("score", 0.0),
            "snippet": (h.get("text") or "")[:240],
            "meta": {"chunk_id": h.get("chunk_id"), "doc_id": h.get("doc_id"), "chunk_index": h.get("chunk_index")},
        })
        context_lines.append(f"[{tag}] {h.get('filename')} (chunk {h.get('chunk_index')}, score {h.get('score'):.3f}, id {h.get('chunk_id')})\n{h.get('text')}\n")
        i += 1

    j = 1
    for h in web_hits:
        tag = f"W{j}"
        sources_meta.append({
            "source_type": "web",
            "ref_id": f"web:{h['chunk_id']}",
            "title": h.get("title") or h.get("domain"),
            "url": h.get("url"),
            "domain": h.get("domain"),
            "score": h.get("score", 0.0),
            "snippet": (h.get("text") or "")[:240],
            "meta": {"chunk_id": h.get("chunk_id"), "page_id": h.get("page_id"), "chunk_index": h.get("chunk_index")},
        })
        context_lines.append(f"[{tag}] {h.get('title') or h.get('domain')} — {h.get('url')} (score {h.get('score'):.3f}, id {h.get('chunk_id')})\n{h.get('text')}\n")
        j += 1

    return sources_meta, context_lines

async def _plan_queries(planner_model: str, query: str) -> dict:
    prompt = (
        "Return ONLY JSON.\n"
        "{"
        "\"subquestions\":[...],"
        "\"web_queries\":[...],"
        "\"doc_queries\":[...],"
        "\"done_if\":[...]\n"
        "}\n\n"
        f"User query:\n{query}\n"
    )
    out = await _ollama_chat_once(planner_model, [{"role":"user","content":prompt}], timeout=45.0)
    obj = cast(Dict, _json_obj_from_text(out) or {})
    subquestions = obj.get("subquestions")
    web_queries = obj.get("web_queries")
    doc_queries = obj.get("doc_queries")
    sq = subquestions if isinstance(subquestions, list) else []
    wq = web_queries if isinstance(web_queries, list) else []
    dq = doc_queries if isinstance(doc_queries, list) else []
    return {"subquestions": sq[:10], "web_queries": wq[:12], "doc_queries": dq[:12], "raw": out}

async def _verify_claims(verifier_model: str, query: str, context_lines: list[str]) -> dict:
    prompt = (
        "You are a verification agent.\n"
        "Given CONTEXT, produce ONLY JSON:\n"
        "{"
        "\"claims\":["
        "{\"claim\":\"...\",\"status\":\"supported|unclear|refuted\",\"citations\":[\"D1\",\"W2\"],\"notes\":\"...\"}"
        "]}\n\n"
        "Rules:\n"
        "- If not directly supported, mark unclear.\n"
        "- citations must refer to bracket tags in CONTEXT.\n\n"
        f"Question:\n{query}\n\n"
        "CONTEXT:\n" + "\n".join(context_lines)
    )
    out = await _ollama_chat_once(verifier_model, [{"role":"user","content":prompt}], timeout=60.0)
    obj = _json_obj_from_text(out) or {}
    claims_val = obj.get("claims")
    claims = claims_val if isinstance(claims_val, list) else []
    cleaned = []
    for c in claims[:40]:
        if not isinstance(c, dict):
            continue
        cleaned.append({
            "claim": str(c.get("claim") or "")[:1800],
            "status": (c.get("status") or "unclear"),
            "citations": c.get("citations") if isinstance(c.get("citations"), list) else [],
            "notes": str(c.get("notes") or "")[:2000],
        })
    return {"claims": cleaned, "raw": out}

async def _synthesize(synth_model: str, query: str, context_lines: list[str], verified_claims: list[dict]) -> str:
    vc = json.dumps(verified_claims, ensure_ascii=False)
    prompt = (
        "Write best possible answer.\n"
        "Rules:\n"
        "- Only assert claims marked supported.\n"
        "- If unclear/refuted, say so.\n"
        "- Cite sources inline like [D1] or [W2].\n\n"
        f"Question:\n{query}\n\n"
        f"Verified claims JSON:\n{vc}\n\n"
        "CONTEXT:\n" + "\n".join(context_lines)
    )
    return await _ollama_chat_once(synth_model, [{"role":"user","content":prompt}], timeout=90.0)

@app.post("/api/research/run")
async def api_research_run(req: ResearchReq):
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    if not _http:
        raise HTTPException(status_code=503, detail="client not initialized")
    http = _http

    planner_model = req.planner_model or os.getenv("RESEARCH_PLANNER_MODEL") or os.getenv("DEFAULT_CHAT_MODEL") or "llama3.1"
    verifier_model = req.verifier_model or os.getenv("RESEARCH_VERIFIER_MODEL") or planner_model
    synth_model = req.synth_model or os.getenv("RESEARCH_SYNTH_MODEL") or planner_model

    settings = req.model_dump(exclude_none=True)
    embed_model = req.embed_model or DEFAULT_EMBED_MODEL
    kiwix_url = os.getenv("KIWIX_URL")

    try:
        return await run_research(
            http=http,
            base_url=OLLAMA_URL,
            ingest_queue=_web_ingest,
            kiwix_url=kiwix_url,
            chat_id=req.chat_id,
            query=query,
            mode=req.mode,
            use_docs=req.use_docs,
            use_web=req.use_web,
            rounds=req.rounds,
            pages_per_round=req.pages_per_round,
            web_top_k=req.web_top_k,
            doc_top_k=req.doc_top_k,
            domain_whitelist=req.domain_whitelist,
            embed_model=embed_model,
            planner_model=planner_model,
            verifier_model=verifier_model,
            synth_model=synth_model,
            settings=settings,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/research/runs")
async def api_research_runs(chat_id: str | None = None, limit: int = 50, offset: int = 0):
    return {"runs": researchstore.list_runs(chat_id=chat_id, limit=limit, offset=offset)}

@app.get("/api/research/{run_id}")
async def api_research_get(run_id: str):
    try:
        return {"run": researchstore.get_run(run_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found")

@app.get("/api/research/{run_id}/trace")
async def api_research_trace(run_id: str, limit: int = 200, offset: int = 0):
    return {"trace": researchstore.get_trace(run_id, limit=limit, offset=offset)}

@app.get("/api/research/{run_id}/sources")
async def api_research_sources(run_id: str):
    return {"sources": researchstore.get_sources(run_id)}

@app.get("/api/research/{run_id}/claims")
async def api_research_claims(run_id: str):
    return {"claims": researchstore.get_claims(run_id)}

class SourceFlagReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pinned: bool | None = None
    excluded: bool | None = None

@app.post("/api/research/{run_id}/sources/{source_id}/flag")
async def api_research_source_flag(run_id: str, source_id: int, req: SourceFlagReq):
    researchstore.set_source_flag(run_id, source_id, pinned=req.pinned, excluded=req.excluded)
    return {"ok": True}


def main():
    """Entry point for running the CogniHub application."""
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "false").lower() == "true"
    uvicorn.run("cognihub.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
