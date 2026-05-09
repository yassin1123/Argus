"""Firm-library retrieval integration tests (Phase 2 / Week 5 / Day 4).

Five contracts:

  1. test_engagement_retrieval_surfaces_firm_content — hybrid_search for
     an engagement in firm A returns firm-library chunks ingested for
     that firm.
  2. test_engagement_in_different_firm_does_not_see_content — same
     query from a firm-B engagement returns zero firm-A chunks.
  3. test_retired_firm_content_excluded — retired chunks are excluded
     from new searches (already covered by Day 1's service test, this
     re-verifies via the orchestrator's _retrieve_by_priorities path).
  4. test_uploaded_priority_expands_to_firm_library — when the planner
     emits source_priorities=["uploaded"], _retrieve_by_priorities
     queries BOTH 'uploaded' and 'firm_library' source_types so firm-
     curated content surfaces under the same priority.
  5. test_evidence_object_carries_firm_library_breadcrumb — converting
     a firm-library chunk to an EvidenceObject yields source_type=
     'firm_library' AND metadata.firm_library_title / category /
     section so the citation popover can render the breadcrumb.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from agents.research.orchestrator import (
    _chunk_dict_to_evidence,
    _retrieve_by_priorities,
)
from core.firm_library import ingest_firm_content, retire_firm_content
from core.retrieval_chunks import hybrid_search

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "firm_library"
    / "ma_target_screen_playbook.md"
)


@pytest.fixture(autouse=True)
async def _db_pool():
    from db.connection import close_db, init_db

    await init_db()
    try:
        yield
    finally:
        await close_db()


@pytest.fixture
def deterministic_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub embed_texts with a content-aware vector so the playbook query
    actually retrieves the playbook chunks (random hash vectors won't
    similarity-match deterministically). Each text gets a 1536-dim
    sparse vector from its content tokens.
    """
    import hashlib
    import re

    def _bow(text: str) -> list[float]:
        """Bag-of-words vector keyed on hashed content tokens."""
        vec = [0.0] * 1536
        for tok in re.findall(r"[a-z]{3,}", text.lower()):
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % 1536
            vec[idx] += 1.0
        # L2 normalise so cosine similarity is meaningful.
        n = sum(v * v for v in vec) ** 0.5
        return [v / n if n else 0.0 for v in vec]

    async def _stub_embed_texts(texts: list[str]) -> list[list[float]]:
        return [_bow(t) for t in texts]

    async def _stub_embed_query(text: str) -> list[float]:
        return _bow(text)

    import core.firm_library.service as svc
    import core.retrieval_chunks as rc

    monkeypatch.setattr(svc, "embed_texts", _stub_embed_texts)
    monkeypatch.setattr(rc, "embed_texts", _stub_embed_texts)


async def _create_firm_engagement_user(name_prefix: str) -> dict[str, Any]:
    from db.connection import acquire

    fid = str(uuid.uuid4())
    uid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO firms (id, name, slug) VALUES ($1::uuid, $2, $3)",
            fid, f"{name_prefix} {fid[:6]}", f"{name_prefix.lower()}-{fid[:8]}",
        )
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, full_name, role) "
            "VALUES ($1::uuid, $2, 'x', $3, 'member')",
            uid, f"u-{fid[:8]}@test.argus.invalid", name_prefix,
        )
        await conn.execute(
            "INSERT INTO firm_memberships (firm_id, user_id, role) "
            "VALUES ($1::uuid, $2::uuid, 'admin')",
            fid, uid,
        )
        await conn.execute(
            """
            INSERT INTO sessions (id, title, query, status, report_mode,
                                  pipeline_state, metadata, gap_report,
                                  intake_questions, intake_answers, updated_at,
                                  firm_id, created_by_user_id)
            VALUES ($1::uuid, 'eng', 'q', 'draft', 'general', 'idle',
                    '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    NOW(), $2::uuid, $3::uuid)
            """,
            sid, fid, uid,
        )
    return {"firm_id": fid, "user_id": uid, "session_id": sid}


async def _cleanup_firm(firm_id: str) -> None:
    from db.connection import acquire

    async with acquire() as conn:
        await conn.execute("DELETE FROM evidence_objects WHERE session_id IN (SELECT id FROM sessions WHERE firm_id = $1::uuid)", firm_id)
        await conn.execute("DELETE FROM chunks WHERE firm_id = $1::uuid", firm_id)
        await conn.execute("DELETE FROM firm_content WHERE firm_id = $1::uuid", firm_id)
        await conn.execute("DELETE FROM sessions WHERE firm_id = $1::uuid", firm_id)
        await conn.execute(
            "DELETE FROM users WHERE id IN (SELECT user_id FROM firm_memberships WHERE firm_id = $1::uuid)",
            firm_id,
        )
        await conn.execute("DELETE FROM firms WHERE id = $1::uuid", firm_id)


# ---------------------------------------------------------------------------
# 1. retrieval surfaces firm content for the same-firm engagement
# ---------------------------------------------------------------------------


async def test_engagement_retrieval_surfaces_firm_content(
    deterministic_embed,
) -> None:
    fixture_bytes = FIXTURE.read_bytes()
    a = await _create_firm_engagement_user("FirmA")
    try:
        result = await ingest_firm_content(
            firm_id=a["firm_id"],
            title="M&A target screen playbook",
            category="playbook",
            file_bytes=fixture_bytes,
            source_filename="ma_target_screen_playbook.md",
            uploaded_by=a["user_id"],
            intended_modes=["due_diligence"],
            sector_tags=["Payments"],
        )
        assert result.chunks_written > 0

        out = await hybrid_search(
            engagement_id=a["session_id"],
            query="M&A target identification criteria size band gross margin",
            mode="hybrid",
            k=10,
            source_types=["firm_library"],
        )
        results = out.get("results") or []
        firm_lib_hits = [r for r in results if r.get("source_type") == "firm_library"]
        assert firm_lib_hits, (
            "expected firm_library hits in the same-firm engagement; got: "
            f"{[r.get('source_type') for r in results]}"
        )
    finally:
        await _cleanup_firm(a["firm_id"])


# ---------------------------------------------------------------------------
# 2. cross-firm isolation: firm B can't see firm A's content
# ---------------------------------------------------------------------------


async def test_engagement_in_different_firm_does_not_see_content(
    deterministic_embed,
) -> None:
    fixture_bytes = FIXTURE.read_bytes()
    a = await _create_firm_engagement_user("FirmA")
    b = await _create_firm_engagement_user("FirmB")
    try:
        await ingest_firm_content(
            firm_id=a["firm_id"],
            title="Firm A confidential M&A target screen",
            category="playbook",
            file_bytes=fixture_bytes,
            source_filename="firm_a_secret.md",
            uploaded_by=a["user_id"],
        )
        out = await hybrid_search(
            engagement_id=b["session_id"],
            query="M&A target identification criteria size band",
            mode="hybrid",
            k=10,
            source_types=["firm_library"],
        )
        # Firm B's engagement must not see Firm A's library content.
        results = out.get("results") or []
        assert results == [], (
            f"cross-firm leak: Firm B saw Firm A's chunks: "
            f"{[r.get('source_filename') for r in results]}"
        )
    finally:
        await _cleanup_firm(a["firm_id"])
        await _cleanup_firm(b["firm_id"])


# ---------------------------------------------------------------------------
# 3. retired firm content is excluded
# ---------------------------------------------------------------------------


async def test_retired_firm_content_excluded(deterministic_embed) -> None:
    fixture_bytes = FIXTURE.read_bytes()
    a = await _create_firm_engagement_user("FirmA")
    try:
        result = await ingest_firm_content(
            firm_id=a["firm_id"],
            title="Soon-to-be-retired playbook",
            category="playbook",
            file_bytes=fixture_bytes,
            source_filename="retired_playbook.md",
            uploaded_by=a["user_id"],
        )

        # Pre-retire: surfaces in retrieval.
        before = await hybrid_search(
            engagement_id=a["session_id"],
            query="M&A target identification criteria size band gross margin",
            mode="hybrid",
            k=10,
            source_types=["firm_library"],
        )
        before_ids = {r["id"] for r in (before.get("results") or [])}
        assert before_ids, "expected pre-retire firm_library hits"

        # Retire and re-query.
        await retire_firm_content(
            firm_id=a["firm_id"],
            content_id=result.firm_content_id,
            retired_by=a["user_id"],
        )
        after = await hybrid_search(
            engagement_id=a["session_id"],
            query="M&A target identification criteria size band gross margin",
            mode="hybrid",
            k=10,
            source_types=["firm_library"],
        )
        after_ids = {r["id"] for r in (after.get("results") or [])}
        assert not (before_ids & after_ids), (
            f"retired firm_library chunks still surfacing: {sorted(before_ids & after_ids)}"
        )
    finally:
        await _cleanup_firm(a["firm_id"])


# ---------------------------------------------------------------------------
# 4. _retrieve_by_priorities expands "uploaded" to include firm_library
# ---------------------------------------------------------------------------


async def test_uploaded_priority_expands_to_firm_library(
    deterministic_embed,
) -> None:
    """The planner emits source_priorities=['uploaded'] and Day 4
    routing pulls in firm_library chunks under the same bucket so firm
    content surfaces without the planner needing a new literal."""
    fixture_bytes = FIXTURE.read_bytes()
    a = await _create_firm_engagement_user("FirmA")
    try:
        await ingest_firm_content(
            firm_id=a["firm_id"],
            title="M&A target screen playbook",
            category="playbook",
            file_bytes=fixture_bytes,
            source_filename="playbook.md",
            uploaded_by=a["user_id"],
        )

        hits, consulted = await _retrieve_by_priorities(
            a["session_id"],
            "M&A target identification criteria size band gross margin",
            ["uploaded"],
        )
        assert "uploaded" in consulted
        firm_lib_hits = [h for h in hits if (h.get("source_type") == "firm_library")]
        assert firm_lib_hits, (
            "uploaded priority did not surface firm_library chunks; got "
            f"{[h.get('source_type') for h in hits]}"
        )
    finally:
        await _cleanup_firm(a["firm_id"])


# ---------------------------------------------------------------------------
# 5. evidence object carries firm-library breadcrumb metadata
# ---------------------------------------------------------------------------


def test_evidence_object_carries_firm_library_breadcrumb() -> None:
    """Direct conversion test — _chunk_dict_to_evidence keeps
    source_type='firm_library' and populates metadata so the citation
    popover can render '📚 Firm Library — title (category) · Section: …'.
    """
    chunk_hit = {
        "id": "chunk-1",
        "content": "When advising on a target screen, the partner-led checklist...",
        "source_type": "firm_library",
        "position": 0,
        "page": None,
        "section_heading": "Target identification criteria",
        "source_filename": "ma_target_screen_playbook.md",
        "source_url": None,
        "trust_level": "firm_vetted",
        "session_id": None,
        "metadata": {
            "firm_content_id": "fc-uuid-123",
            "title": "M&A target screen playbook",
            "category": "playbook",
            "intended_modes": ["due_diligence"],
            "sector_tags": ["Payments"],
        },
        "score": 0.42,
    }
    eo = _chunk_dict_to_evidence(
        session_id="00000000-0000-0000-0000-000000000aa1",
        task_id=1,
        hit=chunk_hit,
    )

    assert eo.source_type == "firm_library", (
        f"expected source_type=firm_library; got {eo.source_type!r}"
    )
    assert eo.source_title == "M&A target screen playbook"
    assert eo.metadata["firm_content_id"] == "fc-uuid-123"
    assert eo.metadata["firm_library_title"] == "M&A target screen playbook"
    assert eo.metadata["category"] == "playbook"
    assert eo.metadata["intended_modes"] == ["due_diligence"]
    assert eo.metadata["sector_tags"] == ["Payments"]
    assert eo.metadata["section"] == "Target identification criteria"


def test_non_firm_library_chunks_keep_legacy_source_type() -> None:
    """Day 4 backwards-compat: SEC / news / transcript chunks still flatten
    to source_type='document' so the existing citation rendering keeps
    working unchanged."""
    sec_hit = {
        "id": "sec-1",
        "content": "Apple delivered $416B revenue...",
        "source_type": "sec_filing",
        "position": 0,
        "section_heading": "1A · Risk Factors",
        "source_filename": "10-K · 2025-09-27 · Apple Inc.",
        "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm",
        "trust_level": "firm_vetted",
        "session_id": None,
        "metadata": {"form": "10-K", "filing_date": "2025-09-27", "accession_number": "x"},
        "score": 0.5,
    }
    eo = _chunk_dict_to_evidence(
        session_id="00000000-0000-0000-0000-000000000bb2",
        task_id=1,
        hit=sec_hit,
    )
    assert eo.source_type == "document"
    assert eo.metadata == {}
