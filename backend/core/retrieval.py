import os
import re

import httpx

from core.embeddings import embed_query
from db.queries import semantic_search, semantic_search_hits
from models.evidence import RetrievedChunk

COHERE_API_KEY = os.getenv("COHERE_API_KEY")
_HYBRID = os.getenv("ARGUS_HYBRID_RETRIEVAL", "").lower() in ("1", "true", "yes")
_VECTOR_WEIGHT = float(os.getenv("ARGUS_HYBRID_VECTOR_WEIGHT", "0.65"))


def _lexical_overlap_score(query: str, chunk_text: str) -> float:
    q = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 2}
    c = {w for w in re.findall(r"\w+", chunk_text.lower()) if len(w) > 2}
    stop = {"the", "a", "an", "is", "to", "of", "and", "or", "in", "for", "that", "this"}
    q = {w for w in q if w not in stop}
    c = {w for w in c if w not in stop}
    if not q:
        return 0.0
    return len(q & c) / max(len(q), 1)


async def _cohere_rerank(query: str, documents: list[str], top_n: int) -> list[int] | None:
    if not COHERE_API_KEY or not documents:
        return None
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(
                "https://api.cohere.com/v1/rerank",
                headers={
                    "Authorization": f"Bearer {COHERE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "rerank-english-v3.0",
                    "query": query,
                    "documents": documents,
                    "top_n": min(top_n, len(documents)),
                },
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("results") or []
            return [int(x["index"]) for x in results if "index" in x]
    except Exception:
        return None


async def retrieve_chunks(session_id: str, question: str, top_k: int = 5) -> list[str]:
    qemb = await embed_query(question)
    return await semantic_search(session_id, qemb, top_k=top_k)


async def retrieve_evidence(
    session_id: str,
    question: str,
    *,
    top_k: int = 5,
    candidate_pool: int | None = None,
    min_similarity: float = 0.08,
) -> list[RetrievedChunk]:
    """Vector retrieval; optional hybrid lexical+vector fusion when ARGUS_HYBRID_RETRIEVAL=1."""
    qemb = await embed_query(question)
    pool_n = candidate_pool or max(top_k * 4, 12)
    rows = await semantic_search_hits(
        session_id,
        qemb,
        top_k=pool_n,
        candidate_pool=pool_n,
        min_similarity=min_similarity,
    )
    if not rows:
        return []
    doc_texts = [str(r["chunk_text"])[:3500] for r in rows]
    idx_order = await _cohere_rerank(question, doc_texts, top_n=len(rows))
    if idx_order:
        rows = [rows[i] for i in idx_order if 0 <= i < len(rows)]

    if _HYBRID:
        vw = max(0.0, min(1.0, _VECTOR_WEIGHT))
        lw = 1.0 - vw
        scored: list[tuple[float, dict]] = []
        for r in rows:
            sim = float(r["similarity"])
            lex = _lexical_overlap_score(question, str(r.get("chunk_text") or ""))
            fused = vw * sim + lw * lex
            scored.append((fused, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        rows = [r for _, r in scored[:top_k]]
    else:
        rows = rows[:top_k]

    return [RetrievedChunk.from_row(r) for r in rows]
