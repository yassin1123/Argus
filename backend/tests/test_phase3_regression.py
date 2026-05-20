"""Phase 3 / Week 14 / Day 4 — full six-artifact regression tests.

Six tests per spec:
  1. All artifact-format combinations generate for the M&A engagement.
  2. All artifact-format combinations generate for the growth engagement.
  3. Growth Porter's renders real content (not the W11/D5 fallback)
     on the deck + 1-pager.
  4. The recommendation extracted from every artifact normalises to
     the same canonical verdict token.
  5. No cross-mode contamination — M&A artifacts don't carry
     ``frameworks.porters_five_forces``; growth artifacts don't
     carry ``valuation_range``.
  6. The Excel citation audit returns empty ``missing`` for both
     engagements' XLSX models.

These tests are integration-tier — they run the seeder (cached,
$0.00) and then regenerate the artifact bundle through the live
export pipeline against a live Postgres. PDFs are tolerated as
``skipped_no_weasyprint`` on Windows dev hosts; every other format
must land ``ready`` on every supported environment.
"""

from __future__ import annotations

import importlib
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


def _postgres_reachable() -> bool:
    """Quick TCP probe at the DATABASE_URL host:port. Returns False when
    the env var is unset OR the socket connect fails inside ~1 second
    — the integration tests are skipped cleanly in either case.

    Without this probe, CI with DATABASE_URL set but no Postgres
    listening erros every test at the fixture layer instead of skipping
    cleanly.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return False
    try:
        parsed = urlparse(db_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 5432
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect((host, port))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="phase 3 regression tests need a reachable Postgres at DATABASE_URL",
)


# ---------------------------------------------------------------------------
# Shared fixture — seed once per module, regenerate bundle per test isn't
# necessary because the regression runner is also per-module and idempotent.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
async def _db_pool():
    from db.connection import close_db, init_db
    await init_db()
    try:
        yield
    finally:
        await close_db()


@pytest.fixture(scope="module")
async def regression_summary():
    """Seed + run the regression once; return the summary dict."""
    seeder = importlib.import_module("tools.seed_sample_workspace")
    runner = importlib.import_module("tools.run_phase3_regression")
    # Cached seed; do regenerate the bundle so the regression sees
    # the freshly-rendered artifacts.
    await seeder.seed(reset=True, skip_artifacts=False)

    # Fire the regression in-process via a minimal Namespace.
    import argparse
    ns = argparse.Namespace(summary_only=False, force_regenerate=False)
    # ``main_async`` opens + closes its own pool — re-open ours after.
    # We bypass the CLI wrapper and call the inner pieces directly.
    engagements = await runner._load_meridian_engagements()
    has_wp = runner._weasyprint_available()
    from tools.check_artifact_consistency import check_engagement_consistency
    records = []
    for eng in engagements:
        for atype, fmt in runner.ARTIFACT_TARGETS:
            rec = await runner._fire_one(eng, atype, fmt, has_wp)
            runner._inspect_artifact_content(rec, eng)
            records.append(rec)
    consistency = {
        eng["session_id"]: check_engagement_consistency(
            [r for r in records if r["engagement_id"] == eng["session_id"]],
            source_recommendation=eng["recommendation"],
        )
        for eng in engagements
    }
    headline = runner._headline_assertions(records, engagements, consistency)
    yield {
        "engagements": engagements,
        "records": records,
        "consistency": consistency,
        "headline": headline,
    }


# ---------------------------------------------------------------------------
# Test 1 — M&A engagement: all 10 artifact-formats generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_artifacts_generate_for_m_and_a(regression_summary) -> None:
    m_and_a_id = next(
        e["session_id"] for e in regression_summary["engagements"]
        if e["mode"] == "m_and_a_diligence"
    )
    artifacts = [r for r in regression_summary["records"] if r["engagement_id"] == m_and_a_id]
    assert len(artifacts) == 10, f"expected 10 (type, format) targets, got {len(artifacts)}"
    statuses = {(r["artifact_type"], r["format"]): r["status"] for r in artifacts}
    for (atype, fmt), status in statuses.items():
        if fmt == "pdf":
            assert status in ("ready", "skipped_no_weasyprint"), (
                f"M&A {atype}/{fmt} in unexpected state: {status}"
            )
        else:
            assert status == "ready", f"M&A {atype}/{fmt} not ready: {status}"


# ---------------------------------------------------------------------------
# Test 2 — growth engagement: all 10 artifact-formats generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_artifacts_generate_for_growth(regression_summary) -> None:
    growth_id = next(
        e["session_id"] for e in regression_summary["engagements"]
        if e["mode"] == "growth_strategy"
    )
    artifacts = [r for r in regression_summary["records"] if r["engagement_id"] == growth_id]
    assert len(artifacts) == 10
    for r in artifacts:
        if r["format"] == "pdf":
            assert r["status"] in ("ready", "skipped_no_weasyprint")
        else:
            assert r["status"] == "ready", f"growth {r['artifact_type']}/{r['format']} not ready"


# ---------------------------------------------------------------------------
# Test 3 — growth Porter's renders real content (not fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_growth_porters_real_not_fallback(regression_summary) -> None:
    detail = regression_summary["headline"]["growth_porters_detail"]
    # detail is keyed by session_id → per-engagement dict.
    assert detail, "no growth engagement seen in regression"
    for sid, d in detail.items():
        assert d.get("deck_force_keywords_found", 0) >= 4, (
            f"deck for growth session {sid} carries only "
            f"{d.get('deck_force_keywords_found')} of 5 Porter's force keywords"
        )
        assert not d.get("deck_has_fallback_marker"), (
            f"deck for growth session {sid} rendered the W11/D5 fallback marker"
        )
        assert d.get("one_pager_fallback_rendered") is False, (
            f"1-pager for growth session {sid} rendered the fallback row"
        )


# ---------------------------------------------------------------------------
# Test 4 — cross-artifact recommendation consistency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendation_consistent_across_artifacts(regression_summary) -> None:
    consistency = regression_summary["consistency"]
    assert consistency, "no per-engagement consistency results"
    for sid, c in consistency.items():
        # At least 2 artifacts must have produced a normalised verdict
        # for the comparison to be meaningful.
        non_empty = [
            e for e in c["per_artifact"]
            if e["normalised"] and not e["skip_reason"]
        ]
        assert len(non_empty) >= 2, (
            f"session {sid}: only {len(non_empty)} artifact(s) produced a "
            "verdict — consistency check is degenerate"
        )
        assert c["consistent"], (
            f"session {sid}: distinct verdicts = "
            f"{c['distinct_normalisations']}"
        )


# ---------------------------------------------------------------------------
# Test 5 — no cross-mode contamination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_cross_mode_contamination(regression_summary) -> None:
    """M&A engagements should not contain Porter's content; growth
    engagements should not contain ``valuation_range`` content. We
    check both the consulting_payload structurally AND the rendered
    artifact bodies via the regression inspection."""
    contamination = regression_summary["headline"]["mode_aware_detail"]
    for title, det in contamination.items():
        assert det["missing_consulting_payload_keys"] == [], (
            f"{title}: missing expected mode keys: {det['missing_consulting_payload_keys']}"
        )
        assert det["leaked_text_markers"] == [], (
            f"{title}: cross-mode markers leaked into rendered artifacts: "
            f"{det['leaked_text_markers']}"
        )


# ---------------------------------------------------------------------------
# Test 6 — Excel citation audit clean for both modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_excel_citation_audit_empty_both_modes(regression_summary) -> None:
    audit_detail = regression_summary["headline"]["excel_audit_detail"]
    assert audit_detail, "no Excel artifacts seen in regression"
    for title, missing in audit_detail.items():
        assert missing == [], (
            f"{title}: Excel citation audit reports missing rows: {missing}"
        )
