"""Hybrid retrieval over the `chunks` table.

Combines:
  - Semantic search via pgvector cosine distance
  - Keyword search via Postgres tsvector + ts_rank

Merges with Reciprocal Rank Fusion (RRF). Permission-aware: only returns chunks
the user is allowed to see for the engagement.

Optional Cohere rerank: enabled when COHERE_API_KEY is set, otherwise no-op.
"""

from __future__ import annotations

import os
import re
from typing import Any, Sequence

from core.embeddings import embed_texts
from db.connection import acquire

# Reciprocal-rank-fusion constant (Cormack et al. — 60 is the empirical default).
_RRF_K = 60


def _vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


def _to_websearch_tsquery(q: str) -> str:
    """Postgres `websearch_to_tsquery` accepts user-typed input directly.
    We sanitize lightly to drop control characters but otherwise let it through.
    """
    cleaned = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", q).strip()
    return cleaned or "*"


# ----------------------------------------------------------------------------
# Per-modality candidate sets
# ----------------------------------------------------------------------------


async def _resolve_engagement_firm_id(engagement_id: str) -> str | None:
    """Look up the firm_id for an engagement.

    Migration 024 made sessions.firm_id NOT NULL with a default-firm
    backfill, so any real engagement resolves to a firm. Returns None
    only when engagement_id doesn't refer to a real session — caller
    treats that as 'no chunks visible' rather than 'all chunks visible'
    (fail-closed tenancy).
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT firm_id FROM sessions WHERE id = $1::uuid",
            engagement_id,
        )
    return str(row["firm_id"]) if row and row["firm_id"] else None


async def _vector_candidates(
    engagement_id: str,
    query_vec: list[float],
    k: int,
    *,
    source_types: list[str] | None = None,
    firm_id: str | None = None,
) -> list[dict[str, Any]]:
    """Top-k chunks by cosine distance, scoped to engagement + firm sources.

    Phase 2 multi-tenancy: ALWAYS firm-scoped. Two tiers of visibility
    within the firm:
      - chunks attached to this engagement (c.session_id = engagement_id)
      - firm-global chunks (c.session_id IS NULL OR uploaded_files.scope='firm')
    Both are gated by c.firm_id = the engagement's firm — that's the
    cross-firm isolation guarantee.

    When ``source_types`` is given, restrict to chunks whose ``source_type``
    is in the list (Day 4 of Week 3 task-aware retrieval routing).
    """
    if firm_id is None:
        firm_id = await _resolve_engagement_firm_id(engagement_id)
        if firm_id is None:
            return []
    async with acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT c.id, c.content, c.source_type, c.position, c.page, c.slide,
                   c.timestamp_str, c.speaker, c.section_heading, c.source_filename,
                   c.source_url, c.trust_level, c.session_id, c.metadata,
                   1 - (c.embedding <=> $2::vector) AS similarity
            FROM chunks c
            LEFT JOIN uploaded_files f ON f.id = c.source_file_id
            WHERE c.firm_id = $5::uuid
              AND (c.session_id = $1::uuid OR f.scope = 'firm' OR c.session_id IS NULL)
              AND (c.metadata->>'retired_at') IS NULL
              AND c.embedding IS NOT NULL
              AND ($4::text[] IS NULL OR c.source_type = ANY($4::text[]))
            ORDER BY c.embedding <=> $2::vector ASC
            LIMIT $3
            """,
            engagement_id,
            _vector_literal(query_vec),
            int(k),
            list(source_types) if source_types else None,
            firm_id,
        )
    return [_chunk_row_dict(r, score=float(r["similarity"])) for r in rows]


async def _keyword_candidates(
    engagement_id: str,
    query: str,
    k: int,
    *,
    source_types: list[str] | None = None,
    firm_id: str | None = None,
) -> list[dict[str, Any]]:
    """Top-k chunks by ts_rank against the user's query.

    Same firm-scoping rules as :func:`_vector_candidates`.
    """
    if firm_id is None:
        firm_id = await _resolve_engagement_firm_id(engagement_id)
        if firm_id is None:
            return []
    tsq = _to_websearch_tsquery(query)
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.content, c.source_type, c.position, c.page, c.slide,
                   c.timestamp_str, c.speaker, c.section_heading, c.source_filename,
                   c.source_url, c.trust_level, c.session_id, c.metadata,
                   ts_rank_cd(c.content_tsv, websearch_to_tsquery('english', $2)) AS rank,
                   ts_headline('english', c.content,
                               websearch_to_tsquery('english', $2),
                               'StartSel=<<,StopSel=>>,MaxFragments=2,MinWords=8,MaxWords=22') AS snippet
            FROM chunks c
            LEFT JOIN uploaded_files f ON f.id = c.source_file_id
            WHERE c.firm_id = $5::uuid
              AND (c.session_id = $1::uuid OR f.scope = 'firm' OR c.session_id IS NULL)
              AND (c.metadata->>'retired_at') IS NULL
              AND c.content_tsv @@ websearch_to_tsquery('english', $2)
              AND ($4::text[] IS NULL OR c.source_type = ANY($4::text[]))
            ORDER BY rank DESC
            LIMIT $3
            """,
            engagement_id,
            tsq,
            int(k),
            list(source_types) if source_types else None,
            firm_id,
        )
    out = []
    for r in rows:
        d = _chunk_row_dict(r, score=float(r["rank"]))
        d["snippet"] = r["snippet"] or None
        out.append(d)
    return out


def _chunk_row_dict(r: Any, *, score: float) -> dict[str, Any]:
    meta = r["metadata"] if "metadata" in r.keys() else None
    if isinstance(meta, str):
        import json as _json

        try:
            meta = _json.loads(meta)
        except Exception:
            meta = {}
    return {
        "id": str(r["id"]),
        "session_id": str(r["session_id"]) if r["session_id"] else None,
        "content": r["content"],
        "source_type": r["source_type"],
        "position": int(r["position"]) if r["position"] is not None else 0,
        "page": r["page"],
        "slide": r["slide"],
        "timestamp_str": r["timestamp_str"],
        "speaker": r["speaker"],
        "section_heading": r["section_heading"],
        "source_filename": r["source_filename"] or "",
        "source_url": r["source_url"],
        "trust_level": r["trust_level"] or "web_general",
        "metadata": meta or {},
        "score": score,
    }


# ----------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ----------------------------------------------------------------------------


def _rrf_merge(*lists: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """Merge ranked candidate lists by Reciprocal Rank Fusion.

    Score = Σ 1 / (k + rank_i) for each list the chunk appears in.
    Returns top-k by RRF score, preserving the original chunk dicts.
    """
    rrf: dict[str, float] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for lst in lists:
        for rank, item in enumerate(lst, start=1):
            cid = item["id"]
            rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
            # Prefer the dict with a snippet, otherwise keep first-seen.
            existing = by_id.get(cid)
            if not existing or (item.get("snippet") and not existing.get("snippet")):
                by_id[cid] = item

    ordered = sorted(rrf.items(), key=lambda x: x[1], reverse=True)
    out: list[dict[str, Any]] = []
    for cid, fused in ordered[:k]:
        d = dict(by_id[cid])
        d["fused_score"] = fused
        out.append(d)
    return out


# ----------------------------------------------------------------------------
# Public hybrid search
# ----------------------------------------------------------------------------


async def hybrid_search(
    *,
    engagement_id: str,
    query: str,
    k: int = 20,
    candidate_k: int = 30,
    mode: str = "hybrid",
    source_types: list[str] | None = None,
) -> dict[str, Any]:
    """Run the requested retrieval mode and return ranked chunks.

    mode ∈ {"hybrid", "vector", "keyword"}

    ``source_types`` (optional): restrict candidates to chunks whose
    ``source_type`` is in this list. Used by Day 4 task-aware retrieval
    routing (e.g. only ``sec_filing`` for tasks the planner says are
    grounded in SEC content). When None, no filter is applied.
    """
    query = (query or "").strip()
    if not query:
        return {"mode": mode, "results": [], "vector_count": 0, "keyword_count": 0}

    # Resolve firm_id once and thread it into both candidate paths so we
    # don't double up on the lookup. Phase 2 multi-tenancy: when the
    # engagement doesn't resolve to a firm (caller passed a bogus ID),
    # we fail-closed and return zero candidates rather than fall back to
    # a global view. Cross-firm isolation is the contract.
    firm_id = await _resolve_engagement_firm_id(engagement_id)
    if firm_id is None:
        return {"mode": mode, "results": [], "vector_count": 0, "keyword_count": 0}

    vector_results: list[dict[str, Any]] = []
    keyword_results: list[dict[str, Any]] = []

    # Run keyword always (cheap); run vector unless mode forbids.
    if mode in ("hybrid", "keyword"):
        keyword_results = await _keyword_candidates(
            engagement_id, query, candidate_k,
            source_types=source_types, firm_id=firm_id,
        )

    if mode in ("hybrid", "vector"):
        try:
            embeds = await embed_texts([query])
            if embeds:
                vector_results = await _vector_candidates(
                    engagement_id, embeds[0], candidate_k,
                    source_types=source_types, firm_id=firm_id,
                )
        except Exception:
            # Embedding failed — keyword-only fallback is still useful.
            vector_results = []

    if mode == "vector":
        merged = vector_results[:k]
    elif mode == "keyword":
        merged = keyword_results[:k]
    else:  # hybrid
        merged = _rrf_merge(vector_results, keyword_results, k=k)

    # Optional rerank step (Cohere) — gated on env.
    if mode == "hybrid" and merged and os.getenv("COHERE_API_KEY"):
        try:
            merged = await _cohere_rerank(query, merged, top_n=k)
        except Exception:
            pass  # rerank failures shouldn't break retrieval

    return {
        "mode": mode,
        "vector_count": len(vector_results),
        "keyword_count": len(keyword_results),
        "results": merged,
    }


async def _cohere_rerank(query: str, items: list[dict[str, Any]], *, top_n: int) -> list[dict[str, Any]]:
    """Cohere rerank if COHERE_API_KEY is set. No-op if it isn't."""
    api_key = os.getenv("COHERE_API_KEY", "").strip()
    if not api_key:
        return items
    import httpx
    docs = [it.get("content", "")[:2000] for it in items]
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.post(
            "https://api.cohere.com/v1/rerank",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "rerank-v3.5", "query": query, "documents": docs, "top_n": top_n},
        )
        resp.raise_for_status()
        data = resp.json()
    out: list[dict[str, Any]] = []
    for r in data.get("results", []):
        idx = int(r.get("index", -1))
        if 0 <= idx < len(items):
            d = dict(items[idx])
            d["rerank_score"] = float(r.get("relevance_score", 0.0))
            out.append(d)
    return out or items
