"""Live pilot signal aggregation — Phase 5 / Week 25 / Day 3.

The signals that tell you whether the product is USEFUL (not just
correct), computed from real pilot usage. All firm-scoped (W23). All
read-only over the W24/W25 telemetry + feedback tables — no prose ever
leaves (W20 privacy line).

  - :func:`edit_rate_summary` — per-engagement "approved with N% edited"
    + the firm's distribution. The killer product-market-fit signal.
  - :func:`edit_rate_by_section` — WHICH sections get edited most (where
    the drafts fall short).
  - :func:`claim_feedback_agreement` — how often consultants agreed with
    the verifier (the production calibration signal; future labeled data).
  - :func:`artifact_quality_signal` — which deliverables rate highest /
    lowest (targeted improvement signal).
"""

from __future__ import annotations

import json
from statistics import median
from typing import Any
from uuid import UUID

from db.connection import acquire

# Interpretation bands for the edit rate (W25/D3 spec).
EDIT_RATE_USABLE_CEILING = 0.20      # < 20% : usable drafts; the wedge holds
EDIT_RATE_REWRITE_FLOOR = 0.50       # > 50% : a starting point, not a deliverable


def _interpret_edit_rate(avg: float) -> str:
    if avg < EDIT_RATE_USABLE_CEILING:
        return (
            "usable_drafts — consultants keep most of the output; the "
            "leverage wedge holds"
        )
    if avg > EDIT_RATE_REWRITE_FLOOR:
        return (
            "heavy_rewrite — consultants rewrite most of it; the output is "
            "a starting point, not a deliverable (a real product-fit finding)"
        )
    return (
        "moderate_edit — useful first draft that needs real editing; watch "
        "the trend"
    )


async def edit_rate_summary(firm_id: UUID | str) -> dict[str, Any]:
    """Per-engagement edit rates + the firm's distribution. ``engagements``
    is small enough to return whole during a pilot."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT session_id, edit_fraction, words_baseline,
                   words_added, words_removed, created_at
              FROM engagement_edit_telemetry
             WHERE firm_id = $1::uuid
             ORDER BY created_at DESC
            """,
            str(firm_id),
        )
    fractions = [float(r["edit_fraction"]) for r in rows]
    n = len(fractions)
    buckets = {"usable_lt20": 0, "moderate_20_50": 0, "heavy_gt50": 0}
    for f in fractions:
        if f < EDIT_RATE_USABLE_CEILING:
            buckets["usable_lt20"] += 1
        elif f > EDIT_RATE_REWRITE_FLOOR:
            buckets["heavy_gt50"] += 1
        else:
            buckets["moderate_20_50"] += 1
    avg = sum(fractions) / n if n else 0.0
    return {
        "engagement_count": n,
        "average_edit_fraction": round(avg, 4),
        "average_edit_pct": round(100.0 * avg, 1),
        "median_edit_pct": round(100.0 * median(fractions), 1) if n else 0.0,
        "distribution": buckets,
        "interpretation": _interpret_edit_rate(avg) if n else "no_data_yet",
        # Honest small-sample flag — the signal only firms up over weeks.
        "low_sample": n < 3,
        "per_engagement": [
            {
                "session_id": str(r["session_id"]),
                "edit_pct": round(100.0 * float(r["edit_fraction"]), 1),
                "words_baseline": int(r["words_baseline"]),
            }
            for r in rows
        ],
    }


async def edit_rate_by_section(firm_id: UUID | str) -> dict[str, Any]:
    """Aggregate the per-section edit churn across the firm's engagements:
    which sections get edited most. Each section's mean edit_fraction +
    how many engagements touched it."""
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT section_edits FROM engagement_edit_telemetry "
            "WHERE firm_id = $1::uuid",
            str(firm_id),
        )
    agg: dict[str, dict[str, float]] = {}
    for r in rows:
        se = r["section_edits"]
        if isinstance(se, str):
            try: se = json.loads(se)
            except Exception: se = {}
        if not isinstance(se, dict):
            continue
        for path, info in se.items():
            if not isinstance(info, dict):
                continue
            slot = agg.setdefault(path, {"sum_frac": 0.0, "n": 0})
            slot["sum_frac"] += float(info.get("edit_fraction") or 0.0)
            slot["n"] += 1
    sections = sorted(
        (
            {
                "section_path": path,
                "engagements_edited": int(v["n"]),
                "mean_edit_pct": round(100.0 * v["sum_frac"] / v["n"], 1)
                if v["n"] else 0.0,
            }
            for path, v in agg.items()
        ),
        key=lambda s: (s["engagements_edited"], s["mean_edit_pct"]),
        reverse=True,
    )
    return {
        "sections": sections,
        "most_edited": sections[0]["section_path"] if sections else None,
    }


async def claim_feedback_agreement(firm_id: UUID | str) -> dict[str, Any]:
    """How often consultants AGREED with the verifier's verdict. Agreement
    = a 'correct' assessment; disagreement = wrong_supported (a missed
    false positive — the dangerous one) or wrong_flagged (over-caution).
    'unsure' is excluded from the rate but counted. This is the production
    calibration signal + future labeled data (Phase 6)."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT consultant_assessment, COUNT(*)::int AS n
              FROM claim_feedback WHERE firm_id = $1::uuid
             GROUP BY consultant_assessment
            """,
            str(firm_id),
        )
    counts = {r["consultant_assessment"]: int(r["n"]) for r in rows}
    correct = counts.get("correct", 0)
    wrong_supported = counts.get("wrong_supported", 0)
    wrong_flagged = counts.get("wrong_flagged", 0)
    unsure = counts.get("unsure", 0)
    decided = correct + wrong_supported + wrong_flagged
    total = decided + unsure
    return {
        "total_feedback": total,
        "decided": decided,
        "counts": {
            "correct": correct, "wrong_supported": wrong_supported,
            "wrong_flagged": wrong_flagged, "unsure": unsure,
        },
        "agreement_rate_pct": round(100.0 * correct / decided, 1) if decided else None,
        # The dangerous-disagreement rate — a missed false positive.
        "wrong_supported_pct": round(100.0 * wrong_supported / decided, 1)
        if decided else None,
        "low_sample": decided < 5,
        "note": (
            "Production calibration signal — real consultants, real claims. "
            "This stream is human-judged labeled data that could improve the "
            "verifier (Phase 6). wrong_supported is the escalation class; "
            "wrong_flagged is expected safe-side over-caution (W24/D1)."
        ),
    }


async def artifact_quality_signal(firm_id: UUID | str) -> dict[str, Any]:
    """Per-artifact-type average rating + which rate highest / lowest —
    a targeted improvement signal (e.g. deck poor but memo good)."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT artifact_type,
                   COALESCE(AVG(rating), 0)::float AS avg_rating,
                   COUNT(*)::int AS n
              FROM artifact_ratings WHERE firm_id = $1::uuid
             GROUP BY artifact_type
            """,
            str(firm_id),
        )
    by_type = [
        {
            "artifact_type": r["artifact_type"],
            "average_rating": round(float(r["avg_rating"]), 2),
            "count": int(r["n"]),
        }
        for r in rows
    ]
    rated = [t for t in by_type if t["count"] > 0]
    ranked = sorted(rated, key=lambda t: t["average_rating"])
    return {
        "by_type": sorted(by_type, key=lambda t: t["average_rating"], reverse=True),
        "highest": ranked[-1] if ranked else None,
        "lowest": ranked[0] if ranked else None,
        "low_sample": sum(t["count"] for t in rated) < 5,
    }


__all__ = [
    "EDIT_RATE_REWRITE_FLOOR",
    "EDIT_RATE_USABLE_CEILING",
    "artifact_quality_signal",
    "claim_feedback_agreement",
    "edit_rate_by_section",
    "edit_rate_summary",
]
