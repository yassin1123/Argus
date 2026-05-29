"""Claim feedback, artifact rating, check-ins + the pilot-health
aggregate — Phase 5 / Week 24 / Day 3.

Every read here is firm-scoped: a query filters by ``firm_id`` and
never crosses firms (W23 rule). Recording is one-click + optional —
no field is required beyond the minimal judgment, because friction
kills response rate.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from db.connection import acquire

# The per-claim assessment vocabulary. Every consultant judgment is a
# future training/labelling pair.
CLAIM_ASSESSMENTS = ("correct", "wrong_supported", "wrong_flagged", "unsure")

# The weekly check-in form — 5-7 questions. The frontend renders these;
# the responses land in pilot_checkins.responses keyed by `id`.
CHECKIN_QUESTIONS = [
    {"id": "what_worked", "type": "text",
     "prompt": "What worked well this week?"},
    {"id": "what_didnt", "type": "text",
     "prompt": "What didn't work, or produced output you couldn't use?"},
    {"id": "top_friction", "type": "text",
     "prompt": "What was the single biggest point of friction?"},
    {"id": "trust_rating", "type": "scale_1_5",
     "prompt": "How much did you trust the verification this week? (1-5)"},
    {"id": "time_saved", "type": "scale_1_5",
     "prompt": "How much time did Argus save vs doing it yourself? (1-5)"},
    {"id": "would_keep_using", "type": "yes_no",
     "prompt": "Would you keep using Argus next week?"},
    {"id": "anything_else", "type": "text",
     "prompt": "Anything else we should know?"},
]


# ---------------------------------------------------------------------------
# Per-claim verification feedback
# ---------------------------------------------------------------------------


async def record_claim_feedback(
    *,
    session_id: UUID | str,
    firm_id: UUID | str,
    claim_id: str,
    consultant_assessment: str,
    user_id: UUID | str,
    verdict_at_feedback: str | None = None,
    note: str | None = None,
) -> str:
    """Record one consultant's judgment of a claim's verification.
    Returns the new row id."""
    if consultant_assessment not in CLAIM_ASSESSMENTS:
        raise ValueError(
            f"consultant_assessment must be one of {CLAIM_ASSESSMENTS}; "
            f"got {consultant_assessment!r}"
        )
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO claim_feedback
                (session_id, firm_id, claim_id, verdict_at_feedback,
                 consultant_assessment, note, user_id)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7::uuid)
            RETURNING id
            """,
            str(session_id), str(firm_id), claim_id,
            verdict_at_feedback, consultant_assessment, note,
            str(user_id),
        )
    return str(row["id"])


async def claim_feedback_distribution(
    firm_id: UUID | str,
) -> dict[str, Any]:
    """Firm-scoped distribution of consultant assessments. The pilot's
    core quality signal: of every claim a consultant judged, what
    fraction did they call correct vs wrong-supported (a missed false
    positive — the dangerous one) vs wrong-flagged (over-caution)."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT consultant_assessment, COUNT(*)::int AS n
              FROM claim_feedback
             WHERE firm_id = $1::uuid
             GROUP BY consultant_assessment
            """,
            str(firm_id),
        )
    counts = {a: 0 for a in CLAIM_ASSESSMENTS}
    for r in rows:
        counts[r["consultant_assessment"]] = int(r["n"])
    total = sum(counts.values())
    pct = {
        a: round(100.0 * counts[a] / total, 1) if total else 0.0
        for a in CLAIM_ASSESSMENTS
    }
    return {"total": total, "counts": counts, "pct": pct}


# ---------------------------------------------------------------------------
# Per-artifact quality rating
# ---------------------------------------------------------------------------


async def record_artifact_rating(
    *,
    session_id: UUID | str,
    firm_id: UUID | str,
    rating: int,
    user_id: UUID | str,
    artifact_id: UUID | str | None = None,
    artifact_type: str | None = None,
    comment: str | None = None,
) -> str:
    """Record a 1-5 quality rating for a deliverable. Returns the row
    id. Optional comment; nothing else required."""
    if not isinstance(rating, int) or not (1 <= rating <= 5):
        raise ValueError(f"rating must be an int 1-5; got {rating!r}")
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO artifact_ratings
                (session_id, firm_id, artifact_id, artifact_type,
                 rating, comment, user_id)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7::uuid)
            RETURNING id
            """,
            str(session_id), str(firm_id),
            str(artifact_id) if artifact_id else None,
            artifact_type, rating, comment, str(user_id),
        )
    return str(row["id"])


async def artifact_rating_summary(firm_id: UUID | str) -> dict[str, Any]:
    """Firm-scoped average rating + count + per-type breakdown."""
    async with acquire() as conn:
        overall = await conn.fetchrow(
            """
            SELECT COALESCE(AVG(rating), 0)::float AS avg_rating,
                   COUNT(*)::int AS n
              FROM artifact_ratings WHERE firm_id = $1::uuid
            """,
            str(firm_id),
        )
        by_type = await conn.fetch(
            """
            SELECT artifact_type,
                   COALESCE(AVG(rating), 0)::float AS avg_rating,
                   COUNT(*)::int AS n
              FROM artifact_ratings WHERE firm_id = $1::uuid
             GROUP BY artifact_type
            """,
            str(firm_id),
        )
    return {
        "average_rating": round(float(overall["avg_rating"]), 2),
        "rating_count": int(overall["n"]),
        "by_type": [
            {
                "artifact_type": r["artifact_type"],
                "average_rating": round(float(r["avg_rating"]), 2),
                "count": int(r["n"]),
            }
            for r in by_type
        ],
    }


# ---------------------------------------------------------------------------
# Weekly check-in
# ---------------------------------------------------------------------------


def _week_bucket(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(tz=timezone.utc)
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


async def submit_checkin(
    *,
    firm_id: UUID | str,
    user_id: UUID | str,
    responses: dict[str, Any],
    week_bucket: str | None = None,
) -> dict[str, Any]:
    """Upsert the firm's check-in for the current ISO week. Re-submitting
    in the same week updates the row. Returns the persisted row."""
    bucket = week_bucket or _week_bucket()
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO pilot_checkins
                (firm_id, user_id, week_bucket, responses)
            VALUES ($1::uuid, $2::uuid, $3, $4::jsonb)
            ON CONFLICT (firm_id, week_bucket) DO UPDATE SET
                responses = EXCLUDED.responses,
                user_id = EXCLUDED.user_id,
                updated_at = NOW()
            RETURNING id, week_bucket, responses, created_at, updated_at
            """,
            str(firm_id), str(user_id), bucket, json.dumps(responses),
        )
    resp = row["responses"]
    if isinstance(resp, str):
        try: resp = json.loads(resp)
        except Exception: resp = {}
    return {
        "id": str(row["id"]),
        "week_bucket": row["week_bucket"],
        "responses": resp,
    }


async def checkin_trend(firm_id: UUID | str, limit: int = 12) -> list[dict[str, Any]]:
    """Firm-scoped weekly check-in history, most recent first."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT week_bucket, responses, updated_at
              FROM pilot_checkins
             WHERE firm_id = $1::uuid
             ORDER BY week_bucket DESC
             LIMIT $2
            """,
            str(firm_id), int(limit),
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        resp = r["responses"]
        if isinstance(resp, str):
            try: resp = json.loads(resp)
            except Exception: resp = {}
        out.append({
            "week_bucket": r["week_bucket"],
            "responses": resp,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        })
    return out


# ---------------------------------------------------------------------------
# Pilot-health aggregate (the operator's daily-driver panel)
# ---------------------------------------------------------------------------


async def _edit_rate_summary(firm_id: UUID | str) -> dict[str, Any]:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(AVG(edit_fraction), 0)::float AS avg_edit,
                   COUNT(*)::int AS n
              FROM engagement_edit_telemetry WHERE firm_id = $1::uuid
            """,
            str(firm_id),
        )
    return {
        "average_edit_fraction": round(float(row["avg_edit"]), 4),
        "average_edit_pct": round(100.0 * float(row["avg_edit"]), 1),
        "engagement_count": int(row["n"]),
    }


async def pilot_health_panel(firm_id: UUID | str) -> dict[str, Any]:
    """The pilot dashboard panel — everything firm-scoped to ``firm_id``.
    The operator's (and the pilot firm_admin's) daily-driver view.

    W25/D3 enriches it with the live product-fit signals: the edit-rate
    distribution + which sections get edited most, the claim-feedback
    agreement rate, and the artifact quality (highest/lowest) signal."""
    from .aggregates import (
        artifact_quality_signal, claim_feedback_agreement,
        edit_rate_by_section, edit_rate_summary,
    )
    return {
        "firm_id": str(firm_id),
        "claim_feedback": await claim_feedback_distribution(firm_id),
        "claim_feedback_agreement": await claim_feedback_agreement(firm_id),
        "artifact_ratings": await artifact_rating_summary(firm_id),
        "artifact_quality": await artifact_quality_signal(firm_id),
        "edit_rate": await _edit_rate_summary(firm_id),
        "edit_rate_summary": await edit_rate_summary(firm_id),
        "edit_rate_by_section": await edit_rate_by_section(firm_id),
        "checkin_trend": await checkin_trend(firm_id),
    }


__all__ = [
    "CHECKIN_QUESTIONS",
    "CLAIM_ASSESSMENTS",
    "artifact_rating_summary",
    "checkin_trend",
    "claim_feedback_distribution",
    "pilot_health_panel",
    "record_artifact_rating",
    "record_claim_feedback",
    "submit_checkin",
]
