from __future__ import annotations

import os
from pathlib import Path


def _prompt(question: str, default: str | None = None) -> str:
    if default:
        q = f"{question} [{default}]: "
    else:
        q = f"{question}: "
    ans = input(q).strip()
    return ans or (default or "")


def _prompt_bool(question: str, default: bool = False) -> bool:
    d = "Y/n" if default else "y/N"
    ans = input(f"{question} ({d}): ").strip().lower()
    if not ans:
        return default
    return ans in {"y", "yes", "true", "1"}


def _expand(p: str) -> str:
    return os.path.expanduser(p.strip())


def main() -> int:
    print("ContextHarbor setup wizard")
    print("- Writes .env (gitignored)")
    print("- You can edit it later")
    print("")

    ollama_url = _prompt("Ollama URL", "http://127.0.0.1:11434").rstrip("/")
    embed_model = _prompt("Embedding model", "nomic-embed-text")
    chat_model = _prompt("Default chat model", "llama3.1")

    print("")
    print("Optional model role overrides (leave blank to keep defaults)")
    decider_model = _prompt("Decider model (optional; /api/decide_model)", "").strip()
    rag_router_model = _prompt("RAG router model (optional; rag.auto_route)", "").strip()
    rag_rerank_model = _prompt("RAG rerank model (optional; rag.rerank)", "").strip()
    rag_synth_model = _prompt("RAG synthesis model (optional; rag.synth)", "").strip()
    research_planner_model = _prompt("Research planner model (optional)", "").strip()
    research_verifier_model = _prompt("Research verifier model (optional)", "").strip()
    research_synth_model = _prompt("Research synth model (optional)", "").strip()

    use_kiwix = _prompt_bool("Use Kiwix offline ZIMs?", default=False)
    kiwix_url = ""
    kiwix_zim_dir = ""
    if use_kiwix:
        kiwix_url = _prompt("Kiwix URL", "http://127.0.0.1:8081").rstrip("/")
        kiwix_zim_dir = _expand(_prompt("ZIM directory", "~/zims"))

    use_epubs = _prompt_bool("Use EPUB ingestion?", default=False)
    ebooks_dir = ""
    if use_epubs:
        ebooks_dir = _expand(_prompt("Ebooks directory (or Calibre library root)", "~/Ebooks"))

    use_web_search = _prompt_bool("Enable web search (SearxNG)?", default=False)
    searxng_url = ""
    search_provider = ""
    if use_web_search:
        searxng_url = _prompt("SearxNG URL", "http://localhost:8080/search").strip()
        search_provider = _prompt("Search provider order", "searxng").strip()

    allow_shell = _prompt_bool("Enable shell tool (dangerous)?", default=False)

    lines: list[str] = []
    lines.append(f"OLLAMA_URL={ollama_url}")
    lines.append(f"EMBED_MODEL={embed_model}")
    lines.append(f"DEFAULT_CHAT_MODEL={chat_model}")

    if decider_model:
        lines.append(f"DECIDER_MODEL={decider_model}")
    if rag_router_model:
        lines.append(f"RAG_ROUTER_MODEL={rag_router_model}")
    if rag_rerank_model:
        lines.append(f"RAG_RERANK_MODEL={rag_rerank_model}")
    if rag_synth_model:
        lines.append(f"RAG_SYNTH_MODEL={rag_synth_model}")

    if research_planner_model:
        lines.append(f"RESEARCH_PLANNER_MODEL={research_planner_model}")
    if research_verifier_model:
        lines.append(f"RESEARCH_VERIFIER_MODEL={research_verifier_model}")
    if research_synth_model:
        lines.append(f"RESEARCH_SYNTH_MODEL={research_synth_model}")

    if use_kiwix:
        lines.append(f"KIWIX_URL={kiwix_url}")
        lines.append(f"KIWIX_ZIM_DIR={kiwix_zim_dir}")

    if use_epubs:
        lines.append(f"EBOOKS_DIR={ebooks_dir}")

    if use_web_search:
        lines.append(f"SEARXNG_URL={searxng_url}")
        lines.append(f"CONTEXTHARBOR_SEARCH_PROVIDER={search_provider}")

    if allow_shell:
        lines.append("ALLOW_SHELL_EXEC=1")

    out = Path(__file__).resolve().parents[1] / ".env"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("")
    print(f"Wrote: {out}")
    print("")
    print("Run with:")
    print("  uvicorn contextharbor.app:app --reload --env-file .env --host 0.0.0.0 --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
