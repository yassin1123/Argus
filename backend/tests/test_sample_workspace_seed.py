"""Phase 3 / Week 14 / Day 3 — sample workspace seeder tests.

Five tests per spec:
  1. seed creates the Meridian firm with three users + memberships.
  2. seed is idempotent — running twice produces no duplicates.
  3. seeded engagements have the full artifact bundle on disk + in DB.
  4. cache restore avoids LLM calls (no writer / analyst / critic
     rows land in llm_calls when the seeder restores from fixture).
  5. growth engagement has Porter's Five Forces populated end-to-end
     (W14/D1 carry-forward demonstrably resolved by the seeder).

These tests touch the live DB and the live filesystem. The
``--reset`` path is exercised in test 2 so the second seed lands on
a clean baseline. WeasyPrint's PDF formats are tolerated as
``skipped_no_weasyprint`` on Windows dev hosts; the count assertions
gate on the non-PDF set so the test suite runs identically across
environments.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# The seeder lives at tools/, not under backend/. Add the repo root
# to sys.path so we can import it as a module.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Skip the whole module if DATABASE_URL isn't set — these tests are
# integration-tier and need the live Postgres.
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="sample-workspace tests need DATABASE_URL set + Postgres available",
)


_FIRM_SLUG = "meridian-advisory"
_FIXTURES = (
    _REPO_ROOT / "backend" / "tests" / "fixtures" / "sample_workspace"
)


def _seeder_module():
    """Reimport to pick up any in-test monkeypatches on the seeder."""
    if "tools.seed_sample_workspace" in sys.modules:
        return importlib.reload(sys.modules["tools.seed_sample_workspace"])
    return importlib.import_module("tools.seed_sample_workspace")


async def _run_seeder(*, reset: bool = False, skip_artifacts: bool = False):
    """Invoke the seeder programmatically via the pool-aware ``seed()``
    entry. The autouse ``_db_pool`` fixture owns init/close so we use
    the inner function which doesn't manage the pool lifecycle."""
    sw = _seeder_module()
    return await sw.seed(reset=reset, skip_artifacts=skip_artifacts)


@pytest.fixture(autouse=True)
async def _db_pool():
    from db.connection import close_db, init_db
    await init_db()
    try:
        yield
    finally:
        await close_db()


# ---------------------------------------------------------------------------
# Test 1 — firm with three users + memberships
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_creates_firm_with_three_users() -> None:
    summary = await _run_seeder(reset=True, skip_artifacts=True)
    assert summary.firm_slug == _FIRM_SLUG
    assert len(summary.user_ids) == 3

    from db.connection import acquire

    async with acquire() as conn:
        firm = await conn.fetchrow(
            "SELECT id, name FROM firms WHERE slug = $1", _FIRM_SLUG,
        )
        assert firm is not None
        assert firm["name"] == "Meridian Advisory"

        mem_rows = await conn.fetch(
            """
            SELECT m.role AS firm_role, u.email
              FROM firm_memberships m
              JOIN users u ON u.id = m.user_id
             WHERE m.firm_id = $1::uuid
             ORDER BY u.email
            """,
            firm["id"],
        )
        emails = [r["email"] for r in mem_rows]
        assert "helena.voss@meridian.invalid" in emails
        assert "marcus.thorne@meridian.invalid" in emails
        assert "priya.shah@meridian.invalid" in emails

        # Helena is the firm admin; the other two are members.
        helena_row = next(r for r in mem_rows if r["email"] == "helena.voss@meridian.invalid")
        assert helena_row["firm_role"] == "admin"


# ---------------------------------------------------------------------------
# Test 2 — idempotency (no duplicates)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_idempotent() -> None:
    # First seed (reset to clean slate so we own the baseline count).
    s1 = await _run_seeder(reset=True, skip_artifacts=True)
    # Capture counts.
    from db.connection import acquire

    async with acquire() as conn:
        n_firms = await conn.fetchval("SELECT COUNT(*) FROM firms WHERE slug = $1", _FIRM_SLUG)
        n_users = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE email LIKE '%@meridian.invalid'",
        )
        n_sessions = await conn.fetchval(
            "SELECT COUNT(*) FROM sessions WHERE firm_id = $1::uuid", s1.firm_id,
        )
        n_reports = await conn.fetchval(
            "SELECT COUNT(*) FROM reports r JOIN sessions s ON s.id = r.session_id "
            "WHERE s.firm_id = $1::uuid", s1.firm_id,
        )

    # Second seed — must NOT increase any of the counts.
    s2 = await _run_seeder(reset=False, skip_artifacts=True)

    async with acquire() as conn:
        assert n_firms == await conn.fetchval(
            "SELECT COUNT(*) FROM firms WHERE slug = $1", _FIRM_SLUG,
        )
        assert n_users == await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE email LIKE '%@meridian.invalid'",
        )
        assert n_sessions == await conn.fetchval(
            "SELECT COUNT(*) FROM sessions WHERE firm_id = $1::uuid", s2.firm_id,
        )
        assert n_reports == await conn.fetchval(
            "SELECT COUNT(*) FROM reports r JOIN sessions s ON s.id = r.session_id "
            "WHERE s.firm_id = $1::uuid", s2.firm_id,
        )

    # Same firm + same session ids on both runs (in-place upsert).
    assert s1.firm_id == s2.firm_id
    s1_ids = sorted(e["session_id"] for e in s1.engagements)
    s2_ids = sorted(e["session_id"] for e in s2.engagements)
    assert s1_ids == s2_ids


# ---------------------------------------------------------------------------
# Test 3 — full artifact bundle per engagement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_engagements_have_full_artifact_bundle() -> None:
    summary = await _run_seeder(reset=True, skip_artifacts=False)
    assert len(summary.engagements) == 2

    # The bundle expected per engagement: 7 non-PDF + 3 PDF formats.
    # On hosts without WeasyPrint, the PDFs land as
    # ``skipped_no_weasyprint`` rather than ``ready`` — both states are
    # acceptable for the per-engagement bundle.
    non_pdf_expected = {
        ("one_pager", "html"),
        ("deck", "pptx"),
        ("excel_model", "xlsx"),
        ("email", "md"),
        ("email", "html"),
        ("interview_guide", "md"),
        ("interview_guide", "html"),
    }
    pdf_expected = {
        ("one_pager", "pdf"),
        ("email", "pdf"),
        ("interview_guide", "pdf"),
    }
    for eng in summary.engagements:
        present = {
            (a["artifact_type"], a["format"]) for a in eng["artifacts"]
        }
        assert non_pdf_expected.issubset(present), (
            f"engagement {eng['title']!r} missing non-PDF formats: "
            f"{non_pdf_expected - present}"
        )
        assert pdf_expected.issubset(present), (
            f"engagement {eng['title']!r} missing PDF format slots"
        )
        # Every non-PDF format must be ``ready``.
        for art in eng["artifacts"]:
            if art["format"] == "pdf":
                # ready or skipped both fine.
                assert art["status"] in ("ready", "skipped_no_weasyprint"), (
                    f"PDF artifact {art} in unexpected state"
                )
            else:
                assert art["status"] == "ready", (
                    f"non-PDF artifact {art} not ready"
                )


# ---------------------------------------------------------------------------
# Test 4 — cache restore avoids LLM calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cached_restore_avoids_llm_calls() -> None:
    """No writer / analyst / critic / verifier ``llm_calls`` rows
    should be inserted during a seed run. The artifact templates are
    pure renders (no LLM). The cached fixture data populates report
    + evidence + agent_outputs directly via SQL inserts."""
    from db.connection import acquire

    # Reset + reseed once to land on a clean baseline.
    summary = await _run_seeder(reset=True, skip_artifacts=False)

    # Sample-workspace sessions don't drive the writer / analyst /
    # critic / verifier paths — assert llm_calls table has zero rows
    # for any of those task kinds against the seeded sessions.
    session_ids = [e["session_id"] for e in summary.engagements]
    async with acquire() as conn:
        n_llm = await conn.fetchval(
            """
            SELECT COUNT(*) FROM llm_calls
             WHERE session_id::text = ANY($1::text[])
               AND task_kind IN ('writer', 'analyst', 'critic', 'verifier')
            """,
            session_ids,
        )
    assert n_llm == 0, (
        f"expected 0 pipeline llm_calls for sample-workspace sessions, got {n_llm}"
    )


# ---------------------------------------------------------------------------
# Test 5 — growth engagement carries populated Porter's Five Forces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_growth_engagement_has_porters() -> None:
    """W14/D1 closed the writer-truncation symptom; the schema-
    enforcement gap is deferred to Phase 4. The sample workspace
    ships a hand-curated growth-engagement fixture that demonstrates
    the end-state — Porter's populated end-to-end.
    """
    summary = await _run_seeder(reset=True, skip_artifacts=True)

    growth_eng = next(
        e for e in summary.engagements if e["mode"] == "growth_strategy"
    )
    session_id = growth_eng["session_id"]

    from db.connection import acquire

    async with acquire() as conn:
        cp = await conn.fetchval(
            "SELECT consulting_payload FROM reports WHERE session_id = $1::uuid",
            session_id,
        )
    payload = json.loads(cp) if isinstance(cp, str) else (cp or {})

    fw = payload.get("frameworks") or {}
    pf = fw.get("porters_five_forces") or {}
    assert pf, "growth engagement frameworks.porters_five_forces missing"

    # All five forces must be populated with intensity + rationale.
    for force in ("rivalry", "supplier_power", "buyer_power",
                  "substitute_threat", "new_entrant_threat"):
        block = pf.get(force) or {}
        assert block.get("intensity") in ("low", "moderate", "high"), (
            f"force {force} missing intensity"
        )
        assert (block.get("rationale") or "").strip(), (
            f"force {force} missing rationale"
        )
        drivers = block.get("key_drivers") or []
        assert len(drivers) >= 2, f"force {force} has fewer than 2 key_drivers"

    # Overall attractiveness + rationale present.
    assert pf.get("overall_attractiveness") in ("low", "moderate", "high")
    assert (pf.get("overall_rationale") or "").strip()
