"""Operator cost-burn alerts — Phase 5 / Week 24 / Day 4.

Surfaces firms APPROACHING their monthly budget before the W23 soft-
stop fires at 100%, so the operator never gets a surprise mid-pilot
stop. Cheap: :func:`scan_cost_alerts` upserts one row per
(firm, month, level) into ``ops_cost_alerts``; the dashboard reads
:func:`active_cost_alerts` (an indexed read).

Levels:
  - ``warn``     — used_pct in [WARN_THRESHOLD, 100): approaching the cap.
  - ``critical`` — used_pct >= 100: the soft-stop is active.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from db.connection import acquire

logger = logging.getLogger(__name__)

# Warn the operator at 75% — comfortably ahead of the 80% firm-admin
# notification and the 100% soft-stop.
WARN_THRESHOLD_PCT = 75.0


def _month_bucket(now: datetime) -> str:
    return now.strftime("%Y-%m")


async def scan_cost_alerts(
    *, now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Scan every firm with a monthly budget, compute its current-month
    spend, and upsert an alert row for any firm at/over the warn
    threshold. Firms that fall back below the threshold (budget raised
    / month reset) have their stale alerts resolved.

    Returns the list of currently-active alerts. Pilot-scale (a handful
    of firms) makes the full scan cheap; the dashboard reads the cached
    rows rather than re-scanning."""
    from core.cost_governance.budgets import compute_budget_status

    now = now or datetime.now(tz=timezone.utc)
    bucket = _month_bucket(now)

    async with acquire() as conn:
        firms = await conn.fetch(
            "SELECT id FROM firms WHERE monthly_budget_usd IS NOT NULL",
        )

    for f in firms:
        firm_id = str(f["id"])
        status = await compute_budget_status(firm_id, now=now)
        if status.used_pct is None:
            continue
        level: str | None = None
        if status.used_pct >= 100.0:
            level = "critical"
        elif status.used_pct >= WARN_THRESHOLD_PCT:
            level = "warn"

        async with acquire() as conn:
            if level is None:
                # Below threshold — resolve any open alerts this month.
                await conn.execute(
                    """
                    UPDATE ops_cost_alerts SET resolved_at = NOW()
                     WHERE firm_id = $1::uuid AND month_bucket = $2
                       AND resolved_at IS NULL
                    """,
                    firm_id, bucket,
                )
                continue
            # Upsert the active level; resolve the OTHER level if present
            # (a firm that crossed 100 shouldn't keep a stale 'warn').
            other = "warn" if level == "critical" else "critical"
            await conn.execute(
                """
                UPDATE ops_cost_alerts SET resolved_at = NOW()
                 WHERE firm_id = $1::uuid AND month_bucket = $2
                   AND alert_level = $3 AND resolved_at IS NULL
                """,
                firm_id, bucket, other,
            )
            await conn.execute(
                """
                INSERT INTO ops_cost_alerts
                    (firm_id, alert_level, used_pct, month_to_date_usd,
                     monthly_budget_usd, month_bucket)
                VALUES ($1::uuid, $2, $3, $4, $5, $6)
                ON CONFLICT (firm_id, month_bucket, alert_level)
                DO UPDATE SET
                    used_pct = EXCLUDED.used_pct,
                    month_to_date_usd = EXCLUDED.month_to_date_usd,
                    monthly_budget_usd = EXCLUDED.monthly_budget_usd,
                    resolved_at = NULL,
                    updated_at = NOW()
                """,
                firm_id, level, round(status.used_pct, 2),
                status.month_to_date_usd, status.monthly_budget_usd, bucket,
            )

    return await active_cost_alerts(now=now)


async def active_cost_alerts(
    firm_id: str | UUID | None = None, *, now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Read unresolved alerts for the current month. ``firm_id``
    restricts to one firm (the firm-admin view); omit for the operator's
    cross-firm view."""
    now = now or datetime.now(tz=timezone.utc)
    bucket = _month_bucket(now)
    clauses = ["month_bucket = $1", "resolved_at IS NULL"]
    params: list[Any] = [bucket]
    if firm_id is not None:
        params.append(str(firm_id))
        clauses.append(f"firm_id = ${len(params)}::uuid")
    where = " AND ".join(clauses)
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT firm_id, alert_level, used_pct, month_to_date_usd,
                       monthly_budget_usd, month_bucket, updated_at
                  FROM ops_cost_alerts
                 WHERE {where}
                 ORDER BY used_pct DESC
                """,
                *params,
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("active_cost_alerts read failed: %s", e)
        return []
    return [
        {
            "firm_id": str(r["firm_id"]),
            "alert_level": r["alert_level"],
            "used_pct": float(r["used_pct"]),
            "month_to_date_usd": float(r["month_to_date_usd"]),
            "monthly_budget_usd": float(r["monthly_budget_usd"]),
            "month_bucket": r["month_bucket"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


__all__ = [
    "WARN_THRESHOLD_PCT",
    "active_cost_alerts",
    "scan_cost_alerts",
]
