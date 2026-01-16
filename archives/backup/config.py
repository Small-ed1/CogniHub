from __future__ import annotations
import os
from typing import Optional

class Config:
    def __init__(self):
        self.ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        self.default_embed_model = os.getenv("EMBED_MODEL", "embeddinggemma")
        self.default_chat_model = os.getenv("DEFAULT_CHAT_MODEL", "llama3.1")
        self.max_upload_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
        self.web_user_agent = os.getenv("WEB_UA", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari")
        self.web_allowed_hosts = os.getenv("WEB_ALLOWED_HOSTS", "")
        self.web_blocked_hosts = os.getenv("WEB_BLOCKED_HOSTS", "")
        
        self.rag_db = os.getenv("RAG_DB", "rag.sqlite3")
        self.chat_db = os.getenv("CHAT_DB", "chat.sqlite3")
        self.web_db = os.getenv("WEB_DB", "web.sqlite3")
        self.research_db = os.getenv("RESEARCH_DB", "research.sqlite3")
        
        self.decider_model = os.getenv("DECIDER_MODEL")
        self.research_planner_model = os.getenv("RESEARCH_PLANNER_MODEL")
        self.research_verifier_model = os.getenv("RESEARCH_VERIFIER_MODEL")
        self.research_synth_model = os.getenv("RESEARCH_SYNTH_MODEL")
        
        self.max_summary_messages = 60
        self.min_autosummary_messages = 4
        self.default_autosummary_every = 12
        self.max_research_rounds = 6
        self.max_pages_per_round = 12
        self.max_web_queries = 6
        self.max_doc_queries = 6
        self.default_web_top_k = 6
        self.default_doc_top_k = 6
        self.max_json_parse_size = 100000
        self.default_chunks_per_upload = 6

config = Config()
