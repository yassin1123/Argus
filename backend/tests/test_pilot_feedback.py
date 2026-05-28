"""Pilot feedback instrumentation tests — Phase 5 / Week 24 / Day 3.

Live-DB integration tests (per-test UUIDs, cleanup after). Pin the six
contracts:

  1. claim feedback recorded + aggregated into a distribution
  2. artifact rating recorded + averaged
  3. edit telemetry computes a diff percentage from baseline → approved
  4. weekly check-in persists (and upserts within the same week)
  5. pilot dashboard aggregates all four signals correctly
  6. all feedback is firm-scoped — one firm's data never leaks to another
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from core.pilot_feedback import (
    artifact_rating_summary,
    claim_feedback_distribution,
    compute_and_record_edit_telemetry,
    compute_edit_telemetry,
    pilot_health_panel,
    record_artifact_rating,
    record_claim_feedback,
    submit_checkin,
)


@pytest.fixture(autouse=True)
async def _db_pool():
    from db.connection import close_db, init_db

    await init_db()
    try:
        yield
    finally:
        await close_db()


async def _make_firm(suffix: str) -> tuple[str, str, str]:
    """Create a firm + one user + one session. Returns (firm_id,
    user_id, session_id)."""
    from db.connection import acquire

    firm_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO firms (id, name, slug) VALUES ($1::uuid, $2, $3)",
            firm_id, f"PF Test {suffix}", f"pf-test-{suffix}",
        )
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, full_name, role, default_firm_id) "
            "VALUES ($1::uuid, $2, 'x', 'PF User', 'member', $3::uuid)",
            user_id, f"pf-{suffix}@test.invalid", firm_id,
        )
        await conn.execute(
            "INSERT INTO firm_memberships (firm_id, user_id, role) "
            "VALUES ($1::uuid, $2::uuid, 'admin')",
            firm_id, user_id,
        )
        await conn.execute(
            "INSERT INTO sessions (id, firm_id, title, query, status, created_by_user_id) "
            "VALUES ($1::uuid, $2::uuid, 'PF Session', 'q', 'ready', $3::uuid)",
            session_id, firm_id, user_id,
        )
    return firm_id, user_id, session_id


async def _cleanup(firm_id: str, user_id: str) -> None:
    from db.connection import acquire

    async with acquire() as conn:
        for tbl in (
            "claim_feedback", "artifact_ratings",
            "engagement_edit_telemetry", "pilot_checkins",
        ):
            await conn.execute(
                f"DELETE FROM {tbl} WHERE firm_id = $1::uuid", firm_id,
            )
        await conn.execute("DELETE FROM payload_versions WHERE firm_id = $1::uuid", firm_id)
        await conn.execute("DELETE FROM reports WHERE session_id IN "
                           "(SELECT id FROM sessions WHERE firm_id = $1::uuid)", firm_id)
        await conn.execute("DELETE FROM sessions WHERE firm_id = $1::uuid", firm_id)
        await conn.execute("DELETE FROM firm_memberships WHERE firm_id = $1::uuid", firm_id)
        await conn.execute("DELETE FROM users WHERE id = $1::uuid", user_id)
        await conn.execute("DELETE FROM firms WHERE id = $1::uuid", firm_id)


# ---------------------------------------------------------------------------
# 1. Claim feedback recorded + aggregated
# ---------------------------------------------------------------------------


async def test_claim_feedback_recorded_and_aggregated() -> None:
    s = uuid.uuid4().hex[:8]
    firm_id, user_id, session_id = await _make_firm(s)
    try:
        for assessment in ("correct", "correct", "wrong_supported", "wrong_flagged", "unsure"):
            await record_claim_feedback(
                session_id=session_id, firm_id=firm_id,
                claim_id=f"claim_{uuid.uuid4().hex[:6]}",
                consultant_assessment=assessment, user_id=user_id,
                verdict_at_feedback="supported",
            )
        dist = await claim_feedback_distribution(firm_id)
        assert dist["total"] == 5
        assert dist["counts"]["correct"] == 2
        assert dist["counts"]["wrong_supported"] == 1
        assert dist["counts"]["wrong_flagged"] == 1
        assert dist["counts"]["unsure"] == 1
        assert dist["pct"]["correct"] == 40.0
        # Invalid assessment rejected.
        with pytest.raises(ValueError):
            await record_claim_feedback(
                session_id=session_id, firm_id=firm_id, claim_id="x",
                consultant_assessment="bogus", user_id=user_id,
            )
    finally:
        await _cleanup(firm_id, user_id)


# ---------------------------------------------------------------------------
# 2. Artifact rating recorded
# ---------------------------------------------------------------------------


async def test_artifact_rating_recorded() -> None:
    s = uuid.uuid4().hex[:8]
    firm_id, user_id, session_id = await _make_firm(s)
    try:
        await record_artifact_rating(
            session_id=session_id, firm_id=firm_id, rating=5,
            user_id=user_id, artifact_type="deck",
            comment="structure good, 2x2 axes felt off",
        )
        await record_artifact_rating(
            session_id=session_id, firm_id=firm_id, rating=3,
            user_id=user_id, artifact_type="memo",
        )
        summary = await artifact_rating_summary(firm_id)
        assert summary["rating_count"] == 2
        assert summary["average_rating"] == 4.0
        types = {r["artifact_type"]: r for r in summary["by_type"]}
        assert types["deck"]["average_rating"] == 5.0
        # Out-of-range rating rejected.
        with pytest.raises(ValueError):
            await record_artifact_rating(
                session_id=session_id, firm_id=firm_id, rating=7,
                user_id=user_id,
            )
    finally:
        await _cleanup(firm_id, user_id)


# ---------------------------------------------------------------------------
# 3. Edit telemetry computes diff percentage
# ---------------------------------------------------------------------------


async def test_edit_telemetry_computes_diff_percentage() -> None:
    from db.connection import acquire

    s = uuid.uuid4().hex[:8]
    firm_id, user_id, session_id = await _make_firm(s)
    try:
        baseline = {
            "summary": "The target shows strong recurring revenue and durable margins.",
            "recommendation": "Proceed to a binding offer at the indicated range.",
        }
        # Edited final: ~half the summary rewritten, recommendation kept.
        final = {
            "summary": "The target shows weak recurring revenue and volatile promotional margins.",
            "recommendation": "Proceed to a binding offer at the indicated range.",
        }
        async with acquire() as conn:
            # Baseline auto-generated draft as version 1.
            await conn.execute(
                """
                INSERT INTO payload_versions
                    (session_id, firm_id, version_number, payload_snapshot,
                     change_type, changed_section_paths, created_by)
                VALUES ($1::uuid, $2::uuid, 1, $3::jsonb, 'initial', '[]'::jsonb, $4::uuid)
                """,
                session_id, firm_id, json.dumps(baseline), user_id,
            )
            # Live (approved) payload in reports.consulting_payload.
            await conn.execute(
                """
                INSERT INTO reports
                    (session_id, recommendation, confidence_level, summary,
                     key_reasons, risks, counterarguments, next_steps, sources,
                     consulting_payload)
                VALUES ($1::uuid, $2, 'medium', $3,
                        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                        $4::jsonb)
                """,
                session_id, final["recommendation"], final["summary"],
                json.dumps(final),
            )

        t = await compute_edit_telemetry(session_id, firm_id)
        # Some churn, but not a full rewrite — the recommendation is identical.
        assert 0.0 < t.edit_fraction < 1.0
        assert t.words_added > 0
        assert t.words_removed > 0
        assert t.words_same > 0

        # Persisting upserts a single row.
        rec = await compute_and_record_edit_telemetry(session_id, firm_id, approved_by=user_id)
        assert rec.edit_fraction == t.edit_fraction
        async with acquire() as conn:
            n = await conn.fetchval(
                "SELECT COUNT(*)::int FROM engagement_edit_telemetry WHERE session_id = $1::uuid",
                session_id,
            )
            assert n == 1
        # Re-running refreshes, doesn't duplicate.
        await compute_and_record_edit_telemetry(session_id, firm_id, approved_by=user_id)
        async with acquire() as conn:
            n2 = await conn.fetchval(
                "SELECT COUNT(*)::int FROM engagement_edit_telemetry WHERE session_id = $1::uuid",
                session_id,
            )
            assert n2 == 1
    finally:
        await _cleanup(firm_id, user_id)


# ---------------------------------------------------------------------------
# 4. Weekly check-in persists
# ---------------------------------------------------------------------------


async def test_weekly_check_in_form_persists() -> None:
    s = uuid.uuid4().hex[:8]
    firm_id, user_id, session_id = await _make_firm(s)
    try:
        r1 = await submit_checkin(
            firm_id=firm_id, user_id=user_id,
            responses={"what_worked": "the deck", "trust_rating": 4,
                       "would_keep_using": "yes"},
            week_bucket="2026-W22",
        )
        assert r1["week_bucket"] == "2026-W22"
        assert r1["responses"]["trust_rating"] == 4
        # Re-submitting the same week updates, doesn't duplicate.
        r2 = await submit_checkin(
            firm_id=firm_id, user_id=user_id,
            responses={"what_worked": "the memo too", "trust_rating": 5},
            week_bucket="2026-W22",
        )
        assert r2["id"] == r1["id"]
        assert r2["responses"]["trust_rating"] == 5

        from db.connection import acquire
        async with acquire() as conn:
            n = await conn.fetchval(
                "SELECT COUNT(*)::int FROM pilot_checkins WHERE firm_id = $1::uuid",
                firm_id,
            )
            assert n == 1
    finally:
        await _cleanup(firm_id, user_id)


# ---------------------------------------------------------------------------
# 5. Pilot dashboard aggregates correctly
# ---------------------------------------------------------------------------


async def test_pilot_dashboard_aggregates_correctly() -> None:
    s = uuid.uuid4().hex[:8]
    firm_id, user_id, session_id = await _make_firm(s)
    try:
        await record_claim_feedback(
            session_id=session_id, firm_id=firm_id, claim_id="c1",
            consultant_assessment="correct", user_id=user_id,
        )
        await record_claim_feedback(
            session_id=session_id, firm_id=firm_id, claim_id="c2",
            consultant_assessment="wrong_flagged", user_id=user_id,
        )
        await record_artifact_rating(
            session_id=session_id, firm_id=firm_id, rating=4,
            user_id=user_id, artifact_type="memo",
        )
        await submit_checkin(
            firm_id=firm_id, user_id=user_id,
            responses={"would_keep_using": "yes"}, week_bucket="2026-W20",
        )

        panel = await pilot_health_panel(firm_id)
        assert panel["firm_id"] == firm_id
        assert panel["claim_feedback"]["total"] == 2
        assert panel["claim_feedback"]["counts"]["correct"] == 1
        assert panel["artifact_ratings"]["average_rating"] == 4.0
        assert panel["artifact_ratings"]["rating_count"] == 1
        assert "average_edit_pct" in panel["edit_rate"]
        assert len(panel["checkin_trend"]) == 1
        assert panel["checkin_trend"][0]["week_bucket"] == "2026-W20"
    finally:
        await _cleanup(firm_id, user_id)


# ---------------------------------------------------------------------------
# 6. Feedback firm-scoped — no cross-firm leakage
# ---------------------------------------------------------------------------


async def test_feedback_firm_scoped() -> None:
    sa = uuid.uuid4().hex[:8]
    sb = uuid.uuid4().hex[:8]
    firm_a, user_a, sess_a = await _make_firm(sa)
    firm_b, user_b, sess_b = await _make_firm(sb)
    try:
        # Firm A records feedback; Firm B records none.
        for _ in range(3):
            await record_claim_feedback(
                session_id=sess_a, firm_id=firm_a,
                claim_id=f"a_{uuid.uuid4().hex[:6]}",
                consultant_assessment="correct", user_id=user_a,
            )
        await record_artifact_rating(
            session_id=sess_a, firm_id=firm_a, rating=5,
            user_id=user_a, artifact_type="deck",
        )
        await submit_checkin(
            firm_id=firm_a, user_id=user_a,
            responses={"x": 1}, week_bucket="2026-W21",
        )

        # Firm B's aggregates must be empty — A's data never crosses.
        b_dist = await claim_feedback_distribution(firm_b)
        assert b_dist["total"] == 0
        b_ratings = await artifact_rating_summary(firm_b)
        assert b_ratings["rating_count"] == 0
        b_panel = await pilot_health_panel(firm_b)
        assert b_panel["claim_feedback"]["total"] == 0
        assert b_panel["artifact_ratings"]["rating_count"] == 0
        assert b_panel["checkin_trend"] == []

        # Firm A still sees its own.
        a_panel = await pilot_health_panel(firm_a)
        assert a_panel["claim_feedback"]["total"] == 3
        assert a_panel["artifact_ratings"]["rating_count"] == 1
    finally:
        await _cleanup(firm_a, user_a)
        await _cleanup(firm_b, user_b)
