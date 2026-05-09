"""Firm library backend tests (Phase 2 / Week 5 / Day 1).

Live-DB tests — they exercise migrations 024 + 025 against the dev
Postgres. Per the existing test pattern (`test_edgar_ingest.py` etc.),
they're auto-isolated by per-test UUIDs and clean up after themselves.

Five contracts pinned by the spec:
  1. ingest_writes_chunks_with_firm_scope — chunks land with firm_id set,
     session_id=NULL, source_type='firm_library', firm_content_id linked.
  2. ingest_idempotent_on_same_filehash — second ingest returns the same
     row without writing new chunks.
  3. retire_excludes_chunks_from_retrieval — after retire, hybrid_search
     doesn't surface the chunks even when they'd otherwise rank high.
  4. cross_firm_isolation — Firm A's content is invisible to Firm B's
     library list AND to Firm B's hybrid_search.
  5. chunk_count_updated_after_ingest — firm_content.chunk_count matches
     the actual chunks table row count.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any

import pytest

from core.firm_library import ingest_firm_content, retire_firm_content
from core.retrieval_chunks import hybrid_search
from storage.firm_content_queries import (
    find_active_by_filehash,
    get_firm_content,
    list_firm_content,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _db_pool():
    """Spin up + tear down asyncpg pool per test."""
    from db.connection import close_db, init_db

    await init_db()
    try:
        yield
    finally:
        await close_db()


@pytest.fixture
def deterministic_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace embed_texts with a hash-based 1536-dim vector. Avoids OpenAI."""
    import hashlib

    async def _stub(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            full = (h * (1536 // len(h) + 1))[:1536]
            out.append([(b - 128) / 128.0 for b in full])
        return out

    # The service imports embed_texts at module level — patch there.
    import core.firm_library.service as svc

    monkeypatch.setattr(svc, "embed_texts", _stub)


@pytest.fixture
async def fresh_firm() -> Any:
    """Create a fresh firm with a unique slug for the test, plus one user
    enrolled as a member. Cleans up at the end.
    """
    from db.connection import acquire

    firm_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    slug = f"test-firm-{firm_id[:8]}"

    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO firms (id, name, slug) VALUES ($1::uuid, $2, $3)",
            firm_id,
            f"Test Firm {firm_id[:6]}",
            slug,
        )
        await conn.execute(
            """
            INSERT INTO users (id, email, password_hash, full_name, role)
            VALUES ($1::uuid, $2, 'x', 'Test User', 'member')
            """,
            user_id,
            f"u-{firm_id[:8]}@test.argus.invalid",
        )
        await conn.execute(
            """
            INSERT INTO firm_memberships (firm_id, user_id, role)
            VALUES ($1::uuid, $2::uuid, 'member')
            """,
            firm_id,
            user_id,
        )
    try:
        yield {"firm_id": firm_id, "user_id": user_id}
    finally:
        async with acquire() as conn:
            # Cascade through chunks + firm_content, then firms (FK cascade
            # handles memberships).
            await conn.execute(
                "DELETE FROM chunks WHERE firm_id = $1::uuid", firm_id
            )
            await conn.execute(
                "DELETE FROM firm_content WHERE firm_id = $1::uuid", firm_id
            )
            await conn.execute(
                "DELETE FROM audit_events WHERE resource_type = 'firm_content' "
                "AND resource_id = ANY(SELECT id::text FROM firm_content WHERE firm_id = $1::uuid)",
                firm_id,
            )
            await conn.execute("DELETE FROM firms WHERE id = $1::uuid", firm_id)
            await conn.execute("DELETE FROM users WHERE id = $1::uuid", user_id)


def _markdown_blob(headline: str, n_paragraphs: int = 4) -> bytes:
    """Build a multi-paragraph .md body big enough to chunk into 2-3 chunks.

    The web/knowledge chunker emits chunks at paragraph boundaries with a
    minimum chunk size — anything below that gets folded.
    """
    paras = [
        f"# {headline}",
        *[
            "When advising a public-company client on a target screen, the "
            "first cut is always whether the deal thesis survives a "
            "headline test: 'X buys Y for £Zbn'. If a senior partner can't "
            "articulate the thesis in one sentence, the deal isn't ready. "
            f"Section {i} continues with sourcing, diligence, and "
            "post-close integration considerations specific to the "
            "boutique-firm context. " * 3
            for i in range(n_paragraphs)
        ],
    ]
    return "\n\n".join(paras).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. ingest_writes_chunks_with_firm_scope
# ---------------------------------------------------------------------------


async def test_ingest_writes_chunks_with_firm_scope(
    fresh_firm: dict, deterministic_embed
) -> None:
    blob = _markdown_blob("M&A target screen playbook")
    result = await ingest_firm_content(
        firm_id=fresh_firm["firm_id"],
        title="M&A Target Screen Playbook",
        category="playbook",
        file_bytes=blob,
        source_filename="ma_screen.md",
        uploaded_by=fresh_firm["user_id"],
        intended_modes=["target_screen", "diligence"],
        sector_tags=["payments"],
    )
    assert result.cached is False
    assert result.chunks_written > 0

    from db.connection import acquire
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT firm_id, session_id, source_type, firm_content_id,
                   trust_level, source_filename, metadata
            FROM chunks WHERE firm_content_id = $1::uuid
            """,
            result.firm_content_id,
        )
    assert len(rows) == result.chunks_written
    for r in rows:
        assert str(r["firm_id"]) == fresh_firm["firm_id"]
        assert r["session_id"] is None
        assert r["source_type"] == "firm_library"
        assert str(r["firm_content_id"]) == result.firm_content_id
        assert r["trust_level"] == "firm_vetted"
        meta = r["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert meta.get("category") == "playbook"
        assert meta.get("intended_modes") == ["target_screen", "diligence"]
        assert meta.get("sector_tags") == ["payments"]


# ---------------------------------------------------------------------------
# 2. ingest_idempotent_on_same_filehash
# ---------------------------------------------------------------------------


async def test_ingest_idempotent_on_same_filehash(
    fresh_firm: dict, deterministic_embed
) -> None:
    blob = _markdown_blob("Sector primer — payments")
    first = await ingest_firm_content(
        firm_id=fresh_firm["firm_id"],
        title="Payments Sector Primer",
        category="sector_primer",
        file_bytes=blob,
        source_filename="payments_primer.md",
        uploaded_by=fresh_firm["user_id"],
    )
    assert first.cached is False
    assert first.chunks_written > 0

    second = await ingest_firm_content(
        firm_id=fresh_firm["firm_id"],
        title="Payments Sector Primer (duplicate)",
        category="sector_primer",
        file_bytes=blob,
        source_filename="payments_primer.md",
        uploaded_by=fresh_firm["user_id"],
    )
    assert second.cached is True
    assert second.firm_content_id == first.firm_content_id
    # Chunks still equal first.chunks_written, nothing duplicated.
    from db.connection import acquire
    async with acquire() as conn:
        n = await conn.fetchval(
            "SELECT count(*)::int FROM chunks WHERE firm_content_id = $1::uuid",
            first.firm_content_id,
        )
    assert n == first.chunks_written


# ---------------------------------------------------------------------------
# 3. retire_excludes_chunks_from_retrieval
# ---------------------------------------------------------------------------


async def test_retire_excludes_chunks_from_retrieval(
    fresh_firm: dict, deterministic_embed
) -> None:
    blob = _markdown_blob("Boutique pricing review playbook")
    result = await ingest_firm_content(
        firm_id=fresh_firm["firm_id"],
        title="Boutique Pricing Review",
        category="playbook",
        file_bytes=blob,
        source_filename="pricing_playbook.md",
        uploaded_by=fresh_firm["user_id"],
    )
    assert result.chunks_written > 0

    # Need an engagement_id for hybrid_search; create one for this firm.
    from db.connection import acquire

    sid = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (id, title, query, status, report_mode,
                                  pipeline_state, metadata, gap_report,
                                  intake_questions, intake_answers, updated_at,
                                  firm_id)
            VALUES ($1::uuid, 'engagement', 'q', 'draft', 'general', 'idle',
                    '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    NOW(), $2::uuid)
            """,
            sid,
            fresh_firm["firm_id"],
        )

    try:
        # Pre-retire: keyword search hits the playbook.
        before = await hybrid_search(
            engagement_id=sid,
            query="boutique pricing review playbook",
            mode="keyword",
            k=10,
        )
        before_ids = {r["id"] for r in (before.get("results") or [])}
        assert before_ids, "expected pre-retire keyword hits"

        # Retire.
        await retire_firm_content(
            firm_id=fresh_firm["firm_id"],
            content_id=result.firm_content_id,
            retired_by=fresh_firm["user_id"],
        )

        after = await hybrid_search(
            engagement_id=sid,
            query="boutique pricing review playbook",
            mode="keyword",
            k=10,
        )
        after_ids = {r["id"] for r in (after.get("results") or [])}
        # None of the retired chunk ids should be in after_ids.
        retired_ids = before_ids
        assert not (retired_ids & after_ids), (
            f"retired chunks still surfacing in hybrid_search: "
            f"{sorted(retired_ids & after_ids)}"
        )

        # The firm_content row keeps retired_at populated.
        fc = await get_firm_content(fresh_firm["firm_id"], result.firm_content_id)
        assert fc and fc.get("retired_at")
    finally:
        async with acquire() as conn:
            await conn.execute("DELETE FROM sessions WHERE id = $1::uuid", sid)


# ---------------------------------------------------------------------------
# 4. cross_firm_isolation
# ---------------------------------------------------------------------------


async def test_cross_firm_isolation(deterministic_embed) -> None:
    """Two fresh firms; ingest into A; query B's library + retrieval; expect zero."""
    from db.connection import acquire

    firm_a = str(uuid.uuid4())
    firm_b = str(uuid.uuid4())
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    sid_b = str(uuid.uuid4())

    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO firms (id, name, slug) VALUES "
            "($1::uuid, $2, $3), ($4::uuid, $5, $6)",
            firm_a, f"Firm A {firm_a[:6]}", f"firm-a-{firm_a[:8]}",
            firm_b, f"Firm B {firm_b[:6]}", f"firm-b-{firm_b[:8]}",
        )
        await conn.execute(
            """
            INSERT INTO users (id, email, password_hash, full_name, role) VALUES
            ($1::uuid, $2, 'x', 'A', 'member'),
            ($3::uuid, $4, 'x', 'B', 'member')
            """,
            user_a, f"a-{firm_a[:8]}@test.argus.invalid",
            user_b, f"b-{firm_b[:8]}@test.argus.invalid",
        )
        await conn.execute(
            """
            INSERT INTO firm_memberships (firm_id, user_id, role) VALUES
            ($1::uuid, $2::uuid, 'member'),
            ($3::uuid, $4::uuid, 'member')
            """,
            firm_a, user_a, firm_b, user_b,
        )
        # Firm B engagement (so we can run hybrid_search scoped to it).
        await conn.execute(
            """
            INSERT INTO sessions (id, title, query, status, report_mode,
                                  pipeline_state, metadata, gap_report,
                                  intake_questions, intake_answers, updated_at,
                                  firm_id)
            VALUES ($1::uuid, 'B engagement', 'q', 'draft', 'general', 'idle',
                    '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    NOW(), $2::uuid)
            """,
            sid_b, firm_b,
        )

    try:
        blob = _markdown_blob("Firm A confidential M&A playbook UNIQUE_TOKEN_XYZQ")
        result_a = await ingest_firm_content(
            firm_id=firm_a,
            title="Firm A Playbook",
            category="playbook",
            file_bytes=blob,
            source_filename="firm_a_secret.md",
            uploaded_by=user_a,
        )
        assert result_a.chunks_written > 0

        # Library list scoped to Firm B → 0 rows.
        b_list = await list_firm_content(firm_b)
        assert b_list == []

        # hybrid_search scoped to a Firm B engagement → no Firm A chunks.
        # We use the unique token in the body to make the keyword query
        # specific.
        b_hits = await hybrid_search(
            engagement_id=sid_b,
            query="UNIQUE_TOKEN_XYZQ confidential",
            mode="keyword",
            k=20,
        )
        assert (b_hits.get("results") or []) == [], (
            "Firm B keyword search returned Firm A chunks — cross-firm leak"
        )
    finally:
        async with acquire() as conn:
            await conn.execute("DELETE FROM chunks WHERE firm_id IN ($1::uuid, $2::uuid)", firm_a, firm_b)
            await conn.execute("DELETE FROM firm_content WHERE firm_id IN ($1::uuid, $2::uuid)", firm_a, firm_b)
            await conn.execute("DELETE FROM sessions WHERE firm_id IN ($1::uuid, $2::uuid)", firm_a, firm_b)
            await conn.execute("DELETE FROM firms WHERE id IN ($1::uuid, $2::uuid)", firm_a, firm_b)
            await conn.execute("DELETE FROM users WHERE id IN ($1::uuid, $2::uuid)", user_a, user_b)


# ---------------------------------------------------------------------------
# 5. chunk_count_updated_after_ingest
# ---------------------------------------------------------------------------


async def test_chunk_count_updated_after_ingest(
    fresh_firm: dict, deterministic_embed
) -> None:
    blob = _markdown_blob("Diligence framework v3")
    result = await ingest_firm_content(
        firm_id=fresh_firm["firm_id"],
        title="Diligence Framework v3",
        category="framework",
        file_bytes=blob,
        source_filename="dilig_v3.md",
        uploaded_by=fresh_firm["user_id"],
    )
    fc = await get_firm_content(fresh_firm["firm_id"], result.firm_content_id)
    assert fc is not None
    assert fc["chunk_count"] == result.chunks_written
    from db.connection import acquire
    async with acquire() as conn:
        actual = await conn.fetchval(
            "SELECT count(*)::int FROM chunks WHERE firm_content_id = $1::uuid",
            result.firm_content_id,
        )
    assert actual == fc["chunk_count"]


# ---------------------------------------------------------------------------
# Bonus — file-type rejection
# ---------------------------------------------------------------------------


async def test_unsupported_file_type_rejected(
    fresh_firm: dict, deterministic_embed
) -> None:
    from core.firm_library import UnsupportedFileTypeError

    with pytest.raises(UnsupportedFileTypeError):
        await ingest_firm_content(
            firm_id=fresh_firm["firm_id"],
            title="bad",
            category="other",
            file_bytes=b"\x00\x01image-bytes",
            source_filename="image.png",
            uploaded_by=fresh_firm["user_id"],
        )
