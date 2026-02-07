from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import httpx

from .context import build_context
from .retrieval import DocRetrievalProvider, WebRetrievalProvider, KiwixRetrievalProvider
from .web_ingest import WebIngestQueue
from .web_search import web_search_with_fallback, SearchError
from ..stores import researchstore, webstore
from .. import config


async def _ollama_chat_once(http: httpx.AsyncClient, base_url: str, model: str, messages: list[dict], timeout: float = 60.0) -> str:
    payload = {"model": model, "messages": messages, "stream": False}
    r = await http.post(f"{base_url}/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    return ((r.json().get("message") or {}).get("content") or "").strip()


async def _plan_queries(http: httpx.AsyncClient, base_url: str, planner_model: str, query: str) -> dict:
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
    out = await _ollama_chat_once(http, base_url, planner_model, [{"role": "user", "content": prompt}], timeout=45.0)
    obj = cast(dict, _json_obj_from_text(out) or {})
    subquestions = obj.get("subquestions")
    web_queries = obj.get("web_queries")
    doc_queries = obj.get("doc_queries")
    sq = subquestions if isinstance(subquestions, list) else []
    wq = web_queries if isinstance(web_queries, list) else []
    dq = doc_queries if isinstance(doc_queries, list) else []
    return {"subquestions": sq[:10], "web_queries": wq[:12], "doc_queries": dq[:12], "raw": out}


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
                            json_str = s[i : j + 1]
                            try:
                                return json.loads(json_str)
                            except json.JSONDecodeError:
                                break
            break
    return None


async def _verify_claims(http: httpx.AsyncClient, base_url: str, verifier_model: str, query: str, context_lines: list[str]) -> dict:
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
    out = await _ollama_chat_once(http, base_url, verifier_model, [{"role": "user", "content": prompt}], timeout=60.0)
    obj = _json_obj_from_text(out) or {}
    claims_val = obj.get("claims")
    claims = claims_val if isinstance(claims_val, list) else []
    cleaned = []
    for c in claims[:40]:
        if not isinstance(c, dict):
            continue
        cleaned.append(
            {
                "claim": str(c.get("claim") or "")[:1800],
                "status": (c.get("status") or "unclear"),
                "citations": c.get("citations") if isinstance(c.get("citations"), list) else [],
                "notes": str(c.get("notes") or "")[:2000],
            }
        )
    return {"claims": cleaned, "raw": out}


async def _synthesize(
    http: httpx.AsyncClient,
    base_url: str,
    synth_model: str,
    query: str,
    context_lines: list[str],
    verified_claims: list[dict],
    *,
    embed_model: str,
    ingest_queue: WebIngestQueue | None,
    kiwix_url: str | None,
) -> str:
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
    # Research mode synthesis is tool-free: all sources are explicit in trace.
    return await _ollama_chat_once(
        http=http,
        base_url=base_url,
        model=synth_model,
        messages=[{"role": "user", "content": prompt}],
        timeout=90.0,
    )


async def run_research(
    *,
    http: httpx.AsyncClient,
    base_url: str,
    ingest_queue: WebIngestQueue,
    kiwix_url: str | None,
    chat_id: str | None,
    query: str,
    mode: str,
    use_docs: bool,
    use_web: bool,
    rounds: int,
    pages_per_round: int,
    web_top_k: int,
    doc_top_k: int,
    domain_whitelist: list[str] | None,
    embed_model: str,
    planner_model: str,
    verifier_model: str,
    synth_model: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    run_id = researchstore.create_run(chat_id, query, mode, settings)
    researchstore.add_trace(run_id, "start", {"query": query, "settings": settings})

    steps: list[dict[str, Any]] = []

    try:
        plan = await _plan_queries(http, base_url, planner_model, query)
        researchstore.add_trace(run_id, "plan", plan)
        steps.append(
            {
                "type": "plan",
                "subquestions": plan.get("subquestions") or [],
                "web_queries": plan.get("web_queries") or [],
                "doc_queries": plan.get("doc_queries") or [],
            }
        )

        rounds = max(1, min(int(rounds), config.config.max_research_rounds))
        pages_per_round = max(1, min(int(pages_per_round), config.config.max_pages_per_round))

        all_doc_hits: list = []
        all_web_hits: list = []
        all_kiwix_hits: list = []
        seen_urls: set[str] = set()
        context_lines: list[str] = []
        verify: dict[str, Any] = {"claims": []}

        doc_provider = DocRetrievalProvider()
        web_provider = WebRetrievalProvider()
        kiwix_provider = KiwixRetrievalProvider(kiwix_url)

        for rno in range(1, rounds + 1):
            researchstore.add_trace(run_id, "round_begin", {"round": rno})
            round_step: dict[str, Any] = {"type": "round", "round": rno}

            if use_docs:
                doc_queries = plan.get("doc_queries") or plan.get("subquestions") or [query]
                doc_queries = [str(x) for x in doc_queries if str(x).strip()][: config.config.max_doc_queries]
                doc_round_hits = []
                for dq in doc_queries:
                    doc_round_hits.extend(
                        await doc_provider.retrieve(
                            dq,
                            top_k=int(doc_top_k),
                            embed_model=embed_model,
                            use_mmr=False,
                            mmr_lambda=0.75,
                        )
                    )
                uniq = {int(h.chunk_id): h for h in doc_round_hits}
                doc_round_hits = list(uniq.values())
                doc_round_hits.sort(key=lambda x: x.score, reverse=True)
                all_doc_hits.extend(doc_round_hits[: int(doc_top_k)])

                researchstore.add_trace(run_id, "docs_retrieve", {"queries": doc_queries, "hits": len(doc_round_hits)})
                round_step["docs"] = {"queries": len(doc_queries), "hits": len(doc_round_hits)}

            if use_web:
                web_queries = plan.get("web_queries") or plan.get("subquestions") or [query]
                web_queries = [str(x) for x in web_queries if str(x).strip()][: config.config.max_web_queries]

                urls = []
                urls_per_query = max(1, pages_per_round // len(web_queries)) if web_queries else pages_per_round
                if not config.config.search_enabled:
                    err = "web search disabled by config"
                    researchstore.add_trace(run_id, "web_search_error", {"query": "*", "error": err})
                    round_step["web"] = {"queries": len(web_queries), "urls": 0, "error": err}
                else:
                    search_tasks = [web_search_with_fallback(http, wq, n=urls_per_query) for wq in web_queries]
                    search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

                    for wq, result in zip(web_queries, search_results):
                        if isinstance(result, Exception):
                            researchstore.add_trace(run_id, "web_search_error", {"query": wq, "error": str(result)})
                        else:
                            found_urls, _provider = result
                            if isinstance(found_urls, list) and found_urls:
                                urls.extend(found_urls)

                cleaned_urls = []
                for u in urls:
                    if u in seen_urls:
                        continue
                    seen_urls.add(u)
                    cleaned_urls.append(u)
                    if len(cleaned_urls) >= pages_per_round:
                        break

                researchstore.add_trace(run_id, "web_search", {"queries": web_queries, "urls": cleaned_urls})
                if "web" not in round_step:
                    round_step["web"] = {"queries": len(web_queries), "urls": len(cleaned_urls)}

                for u in cleaned_urls:
                    await ingest_queue.enqueue(u)
                    try:
                        page = await webstore.upsert_page_from_url(u, force=False)
                        researchstore.add_trace(run_id, "web_upsert", {"url": u, "page_id": page.get("id"), "title": page.get("title")})
                    except Exception as e:
                        researchstore.add_trace(run_id, "web_upsert_error", {"url": u, "error": str(e)})

                web_round_hits = []
                for wq in web_queries:
                    try:
                        web_round_hits.extend(
                            await web_provider.retrieve(
                                wq,
                                top_k=int(web_top_k),
                                domain_whitelist=domain_whitelist,
                                embed_model=embed_model,
                            )
                        )
                    except Exception as e:
                        researchstore.add_trace(run_id, "web_retrieve_error", {"query": wq, "error": str(e)})

                web_uniq = {int(h.chunk_id): h for h in web_round_hits}
                web_round_hits = list(web_uniq.values())
                web_round_hits.sort(key=lambda x: x.score, reverse=True)
                all_web_hits.extend(web_round_hits[: int(web_top_k)])
                researchstore.add_trace(run_id, "web_retrieve", {"hits": len(web_round_hits)})
                if isinstance(round_step.get("web"), dict):
                    round_step["web"]["hits"] = len(web_round_hits)

            kiwix_hits = []
            if kiwix_url:
                try:
                    kiwix_hits = await kiwix_provider.retrieve(query, top_k=3, embed_model=embed_model)
                except Exception:
                    kiwix_hits = []
            all_kiwix_hits.extend(kiwix_hits)

            doc_uniq = {int(h.chunk_id): h for h in all_doc_hits}
            web_uniq = {int(h.chunk_id): h for h in all_web_hits}
            kiwix_uniq = {int(h.chunk_id): h for h in all_kiwix_hits}

            doc_hits = sorted(doc_uniq.values(), key=lambda x: x.score, reverse=True)[: int(doc_top_k)]
            web_hits = sorted(web_uniq.values(), key=lambda x: x.score, reverse=True)[: int(web_top_k)]
            kiwix_hits = sorted(kiwix_uniq.values(), key=lambda x: x.score, reverse=True)[:3]

            sources_meta, context_lines = build_context([*doc_hits, *web_hits, *kiwix_hits])

            researchstore.clear_sources(run_id)
            researchstore.add_sources(run_id, sources_meta)

            verify = await _verify_claims(http, base_url, verifier_model, query, context_lines)
            researchstore.clear_claims(run_id)
            researchstore.add_claims(run_id, verify["claims"])
            researchstore.add_trace(run_id, "verify", {"claims": len(verify["claims"])})

            supported = sum(1 for c in verify["claims"] if (c.get("status") == "supported"))
            unclear = sum(1 for c in verify["claims"] if (c.get("status") != "supported"))
            researchstore.add_trace(run_id, "round_end", {"round": rno, "supported": supported, "other": unclear})

            round_step["verify"] = {"claims": len(verify["claims"]), "supported": supported, "other": unclear}
            steps.append(round_step)

            if supported >= 6:
                break

        final = await _synthesize(
            http,
            base_url,
            synth_model,
            query,
            context_lines,
            verify["claims"],
            embed_model=embed_model,
            ingest_queue=ingest_queue,
            kiwix_url=kiwix_url,
        )
        researchstore.set_run_done(run_id, final)
        researchstore.add_trace(run_id, "done", {"len": len(final)})
        return {
            "ok": True,
            "run_id": run_id,
            "answer": final,
            "sources": sources_meta,
            "steps": steps,
        }
    except Exception as e:
        researchstore.set_run_error(run_id, str(e))
        researchstore.add_trace(run_id, "error", {"error": str(e)})
        raise
