"""Firm-level cost budgets — Phase 5 / Week 23 / Day 3.

Two coexisting gates:

  - ``firms.monthly_budget_usd`` — the firm-wide monthly aggregate.
    Reads spend from the W20/D3 ``cost_ledger`` for the current
    calendar month. Threshold crossings notify firm_admins;
    100%+ soft-stops *new* engagements.
  - ``firms.session_cost_ceiling_usd`` — the per-engagement
    backstop. The W9/D4 deepening cap + the "$5 ceiling" the
    W20/D3 spec called out. Applies to every engagement,
    independent of the monthly budget. Default $5.00.

Hard rule (W23/D3): the budget stop is SOFT. ``check_engagement_blocked``
returns True when a NEW engagement should be refused. ``check_session_ceiling``
returns True when a SPECIFIC engagement has already burned through
its per-session cap. The orchestrator's mid-pipeline cap logic is
the caller's responsibility — a budget should never kill an
in-flight engagement.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from db.connection import acquire

logger = logging.getLogger(__name__)


# Default fallback when the firm hasn't set a session cost ceiling
# yet. Matches migration 048's column default.
DEFAULT_SESSION_CEILING_USD = 5.00

# Threshold percentages at which firm_admins are notified. The
# 80% / 100% choice matches the W23/D3 spec's "no surprise stops"
# rule: the 80% notification lands well before the 100% block.
BUDGET_NOTIFY_THRESHOLDS = (80, 100)


# ---------------------------------------------------------------------------
# BudgetStatus — the panel surfaced on the dashboard + API
# ---------------------------------------------------------------------------


@dataclass
class BudgetStatus:
    """Firm-level spend + budget snapshot for the current month."""

    firm_id: str
    month_bucket: str                      # "YYYY-MM"
    monthly_budget_usd: float | None       # None = no cap configured
    month_to_date_usd: float
    used_pct: float | None                 # 0..100+; None if no cap
    blocks_new_engagements: bool
    next_notification_threshold: int | None  # 80 / 100 / None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _month_bucket(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


async def _read_firm_row(firm_id: str) -> dict[str, Any] | None:
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, monthly_budget_usd, session_cost_ceiling_usd
                  FROM firms WHERE id = $1::uuid
                """,
                firm_id,
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("firm budget read failed: %s", e)
        return None
    return dict(row) if row else None


async def _month_to_date_spend(
    firm_id: str, now: datetime,
) -> float:
    """Sum cost_ledger for the firm's current calendar month."""
    month_start = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(cost_usd), 0)::float AS total
                  FROM cost_ledger
                 WHERE firm_id = $1::uuid
                   AND recorded_at >= $2
                """,
                firm_id, month_start,
            )
        return float(row["total"]) if row else 0.0
    except Exception as e:  # noqa: BLE001
        logger.debug("month_to_date spend read failed: %s", e)
        return 0.0


async def compute_budget_status(
    firm_id: str | UUID, *, now: datetime | None = None,
) -> BudgetStatus:
    """Snapshot the firm's current-month spend + budget. Reads:
      - ``firms.monthly_budget_usd`` (cap)
      - ``cost_ledger`` (month-to-date spend)
      - ``firm_budget_notifications`` (which thresholds already fired)
    """
    now = now or datetime.now(tz=timezone.utc)
    firm_id_str = str(firm_id)
    bucket = _month_bucket(now)
    firm = await _read_firm_row(firm_id_str)
    cap = (firm or {}).get("monthly_budget_usd")
    spend = await _month_to_date_spend(firm_id_str, now)

    if cap is None:
        return BudgetStatus(
            firm_id=firm_id_str,
            month_bucket=bucket,
            monthly_budget_usd=None,
            month_to_date_usd=round(spend, 4),
            used_pct=None,
            blocks_new_engagements=False,
            next_notification_threshold=None,
        )

    cap_f = float(cap)
    pct = (spend / cap_f * 100.0) if cap_f > 0 else 0.0
    blocks = pct >= 100.0

    # Find the next un-fired threshold for the dashboard panel.
    next_threshold: int | None = None
    try:
        async with acquire() as conn:
            fired_rows = await conn.fetch(
                """
                SELECT threshold_pct FROM firm_budget_notifications
                 WHERE firm_id = $1::uuid AND month_bucket = $2
                """,
                firm_id_str, bucket,
            )
        fired = {int(r["threshold_pct"]) for r in fired_rows}
        for t in BUDGET_NOTIFY_THRESHOLDS:
            if t not in fired and pct < t:
                next_threshold = t
                break
    except Exception as e:  # noqa: BLE001
        logger.debug("budget threshold lookup failed: %s", e)

    return BudgetStatus(
        firm_id=firm_id_str,
        month_bucket=bucket,
        monthly_budget_usd=cap_f,
        month_to_date_usd=round(spend, 4),
        used_pct=round(pct, 2),
        blocks_new_engagements=blocks,
        next_notification_threshold=next_threshold,
    )


# ---------------------------------------------------------------------------
# Engagement-creation gate (soft stop at 100%)
# ---------------------------------------------------------------------------


async def check_engagement_blocked(
    firm_id: str | UUID, *, now: datetime | None = None,
) -> tuple[bool, str]:
    """Return ``(blocked, reason)``. Called by the engagement-
    creation route BEFORE allocating a new session. ``blocked=True``
    surfaces as HTTP 402 (Payment Required) with the reason string.

    Hard rule: only blocks NEW engagements. In-flight engagements
    finish — the orchestrator does not consult this function.
    """
    status = await compute_budget_status(firm_id, now=now)
    if status.blocks_new_engagements:
        return True, (
            f"Firm month-to-date spend "
            f"${status.month_to_date_usd:.2f} has reached "
            f"{status.used_pct:.1f}% of the "
            f"${status.monthly_budget_usd:.2f} monthly budget. "
            "New engagements are blocked until the admin raises "
            "the budget or the month resets. In-flight engagements "
            "continue to completion."
        )
    return False, ""


# ---------------------------------------------------------------------------
# Per-session ceiling — the W9/D4 + W20/D3 backstop
# ---------------------------------------------------------------------------


async def check_session_ceiling(
    session_id: str | UUID,
    firm_id: str | UUID | None = None,
) -> tuple[bool, float, float]:
    """Return ``(over_ceiling, current_spend, ceiling_usd)``.

    ``over_ceiling=True`` means the engagement has burned past
    its firm's session_cost_ceiling_usd. The orchestrator
    consults this between pipeline stages — when it trips, the
    in-flight engagement stops gracefully (the W20/D3 ceiling
    semantics), it is NOT cancelled by an external budget pass.
    """
    from core.observability.cost_rollups import session_cost_total
    spend = await session_cost_total(str(session_id))
    # Resolve firm if the caller didn't supply it.
    if firm_id is None:
        try:
            async with acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT firm_id FROM sessions WHERE id = $1::uuid",
                    str(session_id),
                )
            firm_id = row["firm_id"] if row else None
        except Exception:  # noqa: BLE001
            firm_id = None
    ceiling = DEFAULT_SESSION_CEILING_USD
    if firm_id:
        firm = await _read_firm_row(str(firm_id))
        if firm and firm.get("session_cost_ceiling_usd") is not None:
            ceiling = float(firm["session_cost_ceiling_usd"])
    return (spend > ceiling, spend, ceiling)


# ---------------------------------------------------------------------------
# Threshold notification (W18 notifications + dedup)
# ---------------------------------------------------------------------------


async def maybe_notify_threshold_crossing(
    firm_id: str | UUID, *, now: datetime | None = None,
) -> list[int]:
    """If the firm's used_pct has crossed an un-fired threshold
    THIS MONTH, insert a notification for every firm_admin and
    record the firing in ``firm_budget_notifications`` so the
    next call doesn't re-notify.

    Returns the list of thresholds that fired on this call
    (typically 0 or 1 entries).
    """
    now = now or datetime.now(tz=timezone.utc)
    status = await compute_budget_status(firm_id, now=now)
    if status.used_pct is None:
        return []

    bucket = status.month_bucket
    fired: list[int] = []
    try:
        async with acquire() as conn:
            existing = await conn.fetch(
                """
                SELECT threshold_pct FROM firm_budget_notifications
                 WHERE firm_id = $1::uuid AND month_bucket = $2
                """,
                str(firm_id), bucket,
            )
            already = {int(r["threshold_pct"]) for r in existing}
            for t in BUDGET_NOTIFY_THRESHOLDS:
                if t in already:
                    continue
                if status.used_pct < t:
                    continue
                # Threshold crossed AND not yet notified this month.
                await _insert_threshold_notification(
                    conn, str(firm_id), status, t,
                )
                await conn.execute(
                    """
                    INSERT INTO firm_budget_notifications
                        (firm_id, threshold_pct, month_bucket)
                    VALUES ($1::uuid, $2, $3)
                    ON CONFLICT DO NOTHING
                    """,
                    str(firm_id), t, bucket,
                )
                fired.append(t)
    except Exception as e:  # noqa: BLE001
        logger.warning("budget notification skipped: %s", e)
    return fired


async def _insert_threshold_notification(
    conn, firm_id: str, status: BudgetStatus, threshold: int,
) -> int:
    """Direct insert into ``notifications`` for every firm_admin.
    Uses the W23/D2 retention-notification pattern (system event,
    not user-triggered, so we bypass the W18 dispatcher's
    actor-required path)."""
    import json as _json
    delivered = 0
    rows = await conn.fetch(
        """
        SELECT user_id FROM firm_memberships
         WHERE firm_id = $1::uuid AND role = 'admin'
        """,
        firm_id,
    )
    summary = (
        f"Firm budget {threshold}% used: "
        f"${status.month_to_date_usd:.2f} of "
        f"${status.monthly_budget_usd:.2f} for {status.month_bucket}"
        + (" — new engagements blocked" if threshold >= 100 else "")
    )
    for r in rows:
        try:
            await conn.execute(
                """
                INSERT INTO notifications
                    (recipient_id, firm_id, notification_type,
                     session_id, source_ref, actor_id, summary,
                     read, email_status)
                VALUES
                    ($1::uuid, $2::uuid, $3,
                     NULL, $4::jsonb, NULL, $5,
                     FALSE, 'skipped')
                """,
                r["user_id"], firm_id, "firm_budget_threshold",
                _json.dumps({
                    "threshold_pct": threshold,
                    "month_bucket": status.month_bucket,
                    "month_to_date_usd": status.month_to_date_usd,
                    "monthly_budget_usd": status.monthly_budget_usd,
                }),
                summary,
            )
            delivered += 1
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "budget notif insert skipped for user %s: %s",
                r["user_id"], e,
            )
    return delivered


__all__ = [
    "BUDGET_NOTIFY_THRESHOLDS",
    "BudgetStatus",
    "DEFAULT_SESSION_CEILING_USD",
    "check_engagement_blocked",
    "check_session_ceiling",
    "compute_budget_status",
    "maybe_notify_threshold_crossing",
]
