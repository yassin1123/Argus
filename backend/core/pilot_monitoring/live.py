"""Live-pilot watch view — Phase 5 / Week 25 / Day 2.

The active-pilot dashboard payload: what's running right now, what just
failed, live cost burn, the alerts that are firing, and the feedback as
it lands. Firm-scoped. Short-poll friendly (cheap reads only).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from db.connection import acquire

logger = logging.getLogger(__name__)


async def _verification_distribution(
    firm_id: str, from_ts: datetime, to_ts: datetime,
) -> dict[str, Any]:
    """Verification verdict mix over the window (same buckets as the
    W20 dashboard)."""
    from core.observability.metrics import query_window
    rows = await query_window(
        "verification.verdict", from_ts=from_ts, to_ts=to_ts,
        firm_id=firm_id, group_by="outcome",
    )
    dist = {str(r["group"]): int(r["sum"]) for r in rows if r["group"]}
    total = sum(dist.values())
    supported = dist.get("supported_high", 0) + dist.get("supported_low", 0)
    partial = dist.get("weak", 0)
    insufficient = dist.get("contradicted", 0) + dist.get("unknown", 0)
    return {
        "verdicts": dist,
        "total": total,
        "supported_pct": (supported / total * 100.0) if total else 0.0,
        "partial_pct": (partial / total * 100.0) if total else 0.0,
        "insufficient_pct": (insufficient / total * 100.0) if total else 0.0,
    }


async def _active_engagements(firm_id: str) -> list[dict[str, Any]]:
    """In-flight engagements (status='processing') + the most recent
    finished ones, with live cost-so-far."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.title, s.status, s.pipeline_state,
                   s.report_mode, s.updated_at,
                   COALESCE((SELECT SUM(cost_usd) FROM cost_ledger c
                             WHERE c.session_id = s.id), 0)::float AS cost_usd
              FROM sessions s
             WHERE s.firm_id = $1::uuid
               AND (s.status = 'processing'
                    OR s.updated_at > NOW() - INTERVAL '2 hours')
             ORDER BY (s.status = 'processing') DESC, s.updated_at DESC
             LIMIT 25
            """,
            firm_id,
        )
    return [
        {
            "session_id": str(r["id"]),
            "title": r["title"],
            "status": r["status"],
            "pipeline_state": r["pipeline_state"],
            "report_mode": r["report_mode"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "cost_usd": round(float(r["cost_usd"]), 4),
            "active": r["status"] == "processing",
        }
        for r in rows
    ]


async def _recent_feedback(firm_id: str, limit: int = 10) -> dict[str, Any]:
    async with acquire() as conn:
        claims = await conn.fetch(
            """
            SELECT consultant_assessment, created_at
              FROM claim_feedback WHERE firm_id = $1::uuid
             ORDER BY created_at DESC LIMIT $2
            """,
            firm_id, limit,
        )
        ratings = await conn.fetch(
            """
            SELECT rating, artifact_type, created_at
              FROM artifact_ratings WHERE firm_id = $1::uuid
             ORDER BY created_at DESC LIMIT $2
            """,
            firm_id, limit,
        )
    return {
        "recent_claim_feedback": [
            {"assessment": c["consultant_assessment"],
             "at": c["created_at"].isoformat() if c["created_at"] else None}
            for c in claims
        ],
        "recent_artifact_ratings": [
            {"rating": int(r["rating"]), "artifact_type": r["artifact_type"],
             "at": r["created_at"].isoformat() if r["created_at"] else None}
            for r in ratings
        ],
    }


async def _cost_burn(firm_id: str, now: datetime) -> dict[str, Any]:
    from core.cost_governance import compute_budget_status
    status = await compute_budget_status(firm_id, now=now)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with acquire() as conn:
        today = await conn.fetchval(
            "SELECT COALESCE(SUM(cost_usd),0)::float FROM cost_ledger "
            "WHERE firm_id = $1::uuid AND recorded_at >= $2",
            firm_id, day_start,
        )
    return {
        "month_to_date_usd": status.month_to_date_usd,
        "today_usd": round(float(today or 0), 4),
        "monthly_budget_usd": status.monthly_budget_usd,
        "used_pct": status.used_pct,
        "blocks_new_engagements": status.blocks_new_engagements,
    }


async def live_pilot_view(
    firm_id: str | UUID,
    *,
    now: datetime | None = None,
    window_minutes: int = 30,
) -> dict[str, Any]:
    """The active-pilot watch payload for ``firm_id``. Evaluates alerts
    but does NOT dispatch them (the poll surfaces them; dispatch is a
    separate, deduplicated action)."""
    from .alerts import evaluate_pilot_alerts

    now = now or datetime.now(tz=timezone.utc)
    fid = str(firm_id)
    window_start = now - timedelta(minutes=window_minutes)

    dist = await _verification_distribution(fid, window_start, now)
    alerts = await evaluate_pilot_alerts(
        fid, now=now, window_minutes=window_minutes,
        verification_distribution=dist,
    )
    return {
        "firm_id": fid,
        "generated_at": now.isoformat(),
        "window_minutes": window_minutes,
        "active_engagements": await _active_engagements(fid),
        "verification_distribution": dist,
        "cost_burn": await _cost_burn(fid, now),
        "feedback": await _recent_feedback(fid),
        "alerts": [a.to_dict() for a in alerts],
        "alert_count": len(alerts),
        "has_critical": any(a.severity == "critical" for a in alerts),
    }


__all__ = ["live_pilot_view"]
