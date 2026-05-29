"""Edit-rate + live feedback aggregation tests — Phase 5 / Week 25 / Day 3.

Live-DB integration tests (per-test UUIDs + cleanup). Pin five contracts:

  1. edit rate computed per engagement (baseline vs approved payload),
  2. edit rate aggregated across the firm (distribution),
  3. edit rate broken down by section (which sections get edited most),
  4. claim-feedback agreement rate computed from real assessments,
  5. artifact ratings aggregated (highest / lowest).
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
    artifact_quality_signal,
    claim_feedback_agreement,
    compute_and_record_edit_telemetry,
    edit_rate_by_section,
    edit_rate_summary,
    record_artifact_rating,
    record_claim_feedback,
)


@pytest.fixture(autouse=True)
async def _db_pool():
    from db.connection import close_db, init_db

    await init_db()
    try:
        yield
    finally:
        await close_db()


async def _make_firm(suffix: str) -> tuple[str, str]:
    """Returns (firm_id, user_id)."""
    from db.connection import acquire
    firm_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO firms (id, name, slug) VALUES ($1::uuid, $2, $3)",
            firm_id, f"EditRate {suffix}", f"editrate-{suffix}",
        )
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, full_name, role, default_firm_id) "
            "VALUES ($1::uuid, $2, 'x', 'U', 'member', $3::uuid)",
            user_id, f"er-{suffix}@test.invalid", firm_id,
        )
    return firm_id, user_id


async def _engagement_with_edits(
    firm_id: str, user_id: str, baseline: dict, final: dict,
) -> str:
    """Seed a session + v1 (baseline) payload_version + a reports row
    (live/approved payload), then record edit telemetry. Returns sid."""
    from db.connection import acquire
    sid = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (id, firm_id, title, query, status, created_by_user_id) "
            "VALUES ($1::uuid, $2::uuid, 'eng', 'q', 'complete', $3::uuid)",
            sid, firm_id, user_id,
        )
        await conn.execute(
            """
            INSERT INTO payload_versions
                (session_id, firm_id, version_number, payload_snapshot,
                 change_type, changed_section_paths, created_by)
            VALUES ($1::uuid, $2::uuid, 1, $3::jsonb, 'initial', '[]'::jsonb, $4::uuid)
            """,
            sid, firm_id, json.dumps(baseline), user_id,
        )
        await conn.execute(
            """
            INSERT INTO reports
                (session_id, recommendation, confidence_level, summary,
                 key_reasons, risks, counterarguments, next_steps, sources,
                 consulting_payload)
            VALUES ($1::uuid, $2, 'medium', $3, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, $4::jsonb)
            """,
            sid, str(final.get("recommendation", "")),
            str(final.get("summary", "")), json.dumps(final),
        )
    await compute_and_record_edit_telemetry(sid, firm_id, approved_by=user_id)
    return sid


async def _cleanup(firm_id: str, user_id: str) -> None:
    from db.connection import acquire
    async with acquire() as conn:
        for tbl in ("engagement_edit_telemetry", "claim_feedback", "artifact_ratings"):
            await conn.execute(f"DELETE FROM {tbl} WHERE firm_id = $1::uuid", firm_id)
        await conn.execute("DELETE FROM payload_versions WHERE firm_id = $1::uuid", firm_id)
        await conn.execute(
            "DELETE FROM reports WHERE session_id IN "
            "(SELECT id FROM sessions WHERE firm_id = $1::uuid)", firm_id,
        )
        await conn.execute("DELETE FROM sessions WHERE firm_id = $1::uuid", firm_id)
        await conn.execute("DELETE FROM users WHERE id = $1::uuid", user_id)
        await conn.execute("DELETE FROM firms WHERE id = $1::uuid", firm_id)


# ---------------------------------------------------------------------------
# 1. per-engagement edit rate
# ---------------------------------------------------------------------------


async def test_edit_rate_computed_per_engagement() -> None:
    firm_id, user_id = await _make_firm(uuid.uuid4().hex[:8])
    try:
        baseline = {"summary": "alpha beta gamma delta", "recommendation": "Proceed."}
        final = {"summary": "alpha beta REWRITTEN entirely now", "recommendation": "Proceed."}
        await _engagement_with_edits(firm_id, user_id, baseline, final)
        summ = await edit_rate_summary(firm_id)
        assert summ["engagement_count"] == 1
        assert 0.0 < summ["average_edit_fraction"] < 1.0
        assert summ["per_engagement"][0]["edit_pct"] > 0
        assert summ["low_sample"] is True  # 1 < 3
    finally:
        await _cleanup(firm_id, user_id)


# ---------------------------------------------------------------------------
# 2. aggregated distribution across firm
# ---------------------------------------------------------------------------


async def test_edit_rate_aggregated_across_firm() -> None:
    firm_id, user_id = await _make_firm(uuid.uuid4().hex[:8])
    try:
        # One barely-edited, one heavily-rewritten.
        await _engagement_with_edits(
            firm_id, user_id,
            {"summary": "one two three four five six seven eight nine ten"},
            {"summary": "one two three four five six seven eight nine ten changed"},
        )
        await _engagement_with_edits(
            firm_id, user_id,
            {"summary": "completely different original text here now"},
            {"summary": "totally rewritten replacement words everywhere instead"},
        )
        summ = await edit_rate_summary(firm_id)
        assert summ["engagement_count"] == 2
        dist = summ["distribution"]
        assert dist["usable_lt20"] + dist["moderate_20_50"] + dist["heavy_gt50"] == 2
        # The heavily-rewritten one should land in heavy.
        assert dist["heavy_gt50"] >= 1
        assert summ["interpretation"]  # non-empty interpretation string
    finally:
        await _cleanup(firm_id, user_id)


# ---------------------------------------------------------------------------
# 3. broken down by section
# ---------------------------------------------------------------------------


async def test_edit_rate_broken_down_by_section() -> None:
    firm_id, user_id = await _make_firm(uuid.uuid4().hex[:8])
    try:
        # Matched scaffolding (mirrors what _load_live_payload reconstructs
        # from the reports columns) so ONLY 'summary' differs;
        # 'recommendation' + 'confidence_level' are identical.
        base = {
            "recommendation": "Proceed to a binding offer at the indicated range.",
            "confidence_level": "medium",
        }
        baseline = {**base, "summary": "the original synergy estimate was conservative and modest"}
        final = {**base, "summary": "the revised synergy estimate is aggressive and optimistic indeed"}
        await _engagement_with_edits(firm_id, user_id, baseline, final)
        by_sec = await edit_rate_by_section(firm_id)
        paths = {s["section_path"] for s in by_sec["sections"]}
        assert "summary" in paths
        assert "recommendation" not in paths  # untouched → not recorded
        assert by_sec["most_edited"] == "summary"
    finally:
        await _cleanup(firm_id, user_id)


# ---------------------------------------------------------------------------
# 4. claim-feedback agreement rate
# ---------------------------------------------------------------------------


async def test_claim_feedback_agreement_rate_computed() -> None:
    firm_id, user_id = await _make_firm(uuid.uuid4().hex[:8])
    from db.connection import acquire
    sid = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (id, firm_id, title, query, status, created_by_user_id) "
            "VALUES ($1::uuid, $2::uuid, 'eng', 'q', 'complete', $3::uuid)",
            sid, firm_id, user_id,
        )
    try:
        # 3 correct, 1 wrong_supported, 1 wrong_flagged, 1 unsure.
        for a in ("correct", "correct", "correct", "wrong_supported",
                  "wrong_flagged", "unsure"):
            await record_claim_feedback(
                session_id=sid, firm_id=firm_id,
                claim_id=f"c_{uuid.uuid4().hex[:6]}",
                consultant_assessment=a, user_id=user_id,
            )
        agg = await claim_feedback_agreement(firm_id)
        assert agg["total_feedback"] == 6
        assert agg["decided"] == 5            # unsure excluded from rate
        assert agg["agreement_rate_pct"] == 60.0   # 3/5
        assert agg["wrong_supported_pct"] == 20.0  # 1/5
        assert agg["counts"]["unsure"] == 1
    finally:
        await _cleanup(firm_id, user_id)


# ---------------------------------------------------------------------------
# 5. artifact ratings aggregated (highest / lowest)
# ---------------------------------------------------------------------------


async def test_artifact_rating_aggregated() -> None:
    firm_id, user_id = await _make_firm(uuid.uuid4().hex[:8])
    from db.connection import acquire
    sid = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (id, firm_id, title, query, status, created_by_user_id) "
            "VALUES ($1::uuid, $2::uuid, 'eng', 'q', 'complete', $3::uuid)",
            sid, firm_id, user_id,
        )
    try:
        # Memo rates well, deck rates poorly — the targeted signal.
        await record_artifact_rating(session_id=sid, firm_id=firm_id, rating=5,
                                     user_id=user_id, artifact_type="memo")
        await record_artifact_rating(session_id=sid, firm_id=firm_id, rating=5,
                                     user_id=user_id, artifact_type="memo")
        await record_artifact_rating(session_id=sid, firm_id=firm_id, rating=2,
                                     user_id=user_id, artifact_type="deck")
        sig = await artifact_quality_signal(firm_id)
        assert sig["highest"]["artifact_type"] == "memo"
        assert sig["highest"]["average_rating"] == 5.0
        assert sig["lowest"]["artifact_type"] == "deck"
        assert sig["lowest"]["average_rating"] == 2.0
    finally:
        await _cleanup(firm_id, user_id)
