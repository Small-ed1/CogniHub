from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Optional

from ..stores import ragstore, webstore
from . import kiwix


@dataclass
class RetrievalResult:
    source_type: str
    ref_id: str
    chunk_id: int
    title: str | None
    url: str | None
    domain: str | None
    score: float
    text: str
    meta: dict[str, Any]


class RetrievalProvider:
    name: str = "base"

    async def retrieve(self, query: str, top_k: int, embed_model: str | None = None, **kwargs) -> list[RetrievalResult]:
        raise NotImplementedError


class DocRetrievalProvider(RetrievalProvider):
    name = "doc"

    async def retrieve(self, query: str, top_k: int, embed_model: str | None = None, **kwargs) -> list[RetrievalResult]:
        doc_ids = kwargs.get("doc_ids")
        use_mmr = kwargs.get("use_mmr")
        mmr_lambda = kwargs.get("mmr_lambda", 0.75)
        group_name = kwargs.get("group_name")
        source = kwargs.get("source")
        hits = await ragstore.retrieve(
            query,
            top_k=top_k,
            doc_ids=doc_ids,
            group_name=group_name,
            source=source,
            embed_model=embed_model,
            use_mmr=use_mmr,
            mmr_lambda=mmr_lambda,
        )
        results = []
        for h in hits:
            doc_title = h.get("title") or h.get("filename")
            section = h.get("section")
            display = doc_title
            if section:
                display = f"{doc_title} — {section}"
            results.append(
                RetrievalResult(
                    source_type="doc",
                    ref_id=f"doc:{h['chunk_id']}",
                    chunk_id=int(h["chunk_id"]),
                    title=display,
                    url=None,
                    domain=None,
                    score=float(h.get("score") or 0.0),
                    text=h.get("text") or "",
                    meta={
                        "doc_id": h.get("doc_id"),
                        "chunk_index": h.get("chunk_index"),
                        "doc_weight": h.get("doc_weight", 1.0),
                        "filename": h.get("filename"),
                        "title": h.get("title"),
                        "author": h.get("author"),
                        "path": h.get("path"),
                        "source": h.get("source"),
                        "section": h.get("section"),
                    },
                )
            )
        return results


class WebRetrievalProvider(RetrievalProvider):
    name = "web"

    async def retrieve(self, query: str, top_k: int, embed_model: str | None = None, **kwargs) -> list[RetrievalResult]:
        domain_whitelist = kwargs.get("domain_whitelist")
        hits = await webstore.retrieve(query, top_k=top_k, domain_whitelist=domain_whitelist, embed_model=embed_model)
        results = []
        for h in hits:
            results.append(
                RetrievalResult(
                    source_type="web",
                    ref_id=f"web:{h['chunk_id']}",
                    chunk_id=int(h["chunk_id"]),
                    title=h.get("title") or h.get("domain"),
                    url=h.get("url"),
                    domain=h.get("domain"),
                    score=float(h.get("score") or 0.0),
                    text=h.get("text") or "",
                    meta={
                        "page_id": h.get("page_id"),
                        "chunk_index": h.get("chunk_index"),
                    },
                )
            )
        return results


class KiwixRetrievalProvider(RetrievalProvider):
    name = "kiwix"

    def __init__(self, base_url: Optional[str] = None):
        self._base_url = (base_url or "").rstrip("/")

    async def retrieve(self, query: str, top_k: int, embed_model: str | None = None, **kwargs) -> list[RetrievalResult]:
        if not self._base_url:
            return []
        q = (query or "").strip()
        if not q:
            return []

        results = await kiwix.search(self._base_url, q, top_k=top_k)
        if not results:
            return []

        persist = bool(kwargs.get("persist", False))
        pages = int(kwargs.get("pages") or 4)
        pages = max(1, min(pages, 10))

        embed_model = embed_model or ragstore.DEFAULT_EMBED_MODEL
        domain = self._base_url.replace("http://", "").replace("https://", "")

        if not persist:
            pages_meta = []
            for item in results[:pages]:
                path = item.get("path") or item.get("url") or ""
                page = await kiwix.fetch_page(self._base_url, path)
                if not page:
                    continue
                pages_meta.append({
                    "title": item.get("title") or item.get("path"),
                    "path": item.get("path"),
                    "url": page.get("url"),
                    "domain": domain,
                    "text": page.get("text") or "",
                })
            if not pages_meta:
                return []

            query_emb = (await ragstore.embed_texts([q], model=embed_model))[0]
            qvec = ragstore.embedding_to_array(query_emb)
            texts: list[str] = [str(p.get("text") or "") for p in pages_meta]
            embeddings = await ragstore.embed_texts(texts, model=embed_model)

            items: list[RetrievalResult] = []
            for meta, emb in zip(pages_meta, embeddings):
                vec = ragstore.embedding_to_array(emb)
                score = float(ragstore.cosine(qvec, vec))
                url = str(meta.get("url") or "")
                chunk_id = int(hashlib.sha256(url.encode("utf-8", errors="ignore")).hexdigest()[:12], 16)
                items.append(
                    RetrievalResult(
                        source_type="kiwix",
                        ref_id=f"kiwix:{chunk_id}",
                        chunk_id=chunk_id,
                        title=meta.get("title"),
                        url=meta.get("url"),
                        domain=meta.get("domain"),
                        score=score,
                        text=meta.get("text") or "",
                        meta={"path": meta.get("path")},
                    )
                )
            items.sort(key=lambda x: x.score, reverse=True)
            return items[:top_k]

        ingested_doc_ids: list[int] = []
        for item in results[:pages]:
            path = item.get("path") or item.get("url") or ""
            page = await kiwix.fetch_page(self._base_url, path)
            if not page:
                continue
            text = (page.get("text") or "").strip()
            if not text:
                continue
            title = str(item.get("title") or path or "kiwix")
            url = str(page.get("url") or "")
            meta_json = json.dumps({"source": "kiwix", "path": path, "url": url}, ensure_ascii=False)
            doc_id = await ragstore.add_document(
                f"kiwix:{title}",
                text,
                embed_model=embed_model,
                source="kiwix",
                title=title,
                author=None,
                path=url or path,
                meta_json=meta_json,
                group_name="kiwix",
            )
            ingested_doc_ids.append(int(doc_id))

        if not ingested_doc_ids:
            return []

        hits = await ragstore.retrieve(q, top_k=top_k, doc_ids=ingested_doc_ids, embed_model=embed_model)

        out: list[RetrievalResult] = []
        for h in hits:
            out.append(
                RetrievalResult(
                    source_type="kiwix",
                    ref_id=f"kiwix:{h['chunk_id']}",
                    chunk_id=int(h["chunk_id"]),
                    title=h.get("title") or h.get("filename"),
                    url=h.get("path"),
                    domain=domain,
                    score=float(h.get("score") or 0.0),
                    text=h.get("text") or "",
                    meta={
                        "path": h.get("path"),
                        "doc_id": h.get("doc_id"),
                        "chunk_index": h.get("chunk_index"),
                    },
                )
            )
        return out
