"""Per-firm rate limits — Phase 5 / Week 23 / Day 3.

Two limits:

  - **Engagement creation:** ``DEFAULT_ENGAGEMENT_RATE_PER_HOUR``
    new engagements per firm per rolling hour. Prevents
    runaway loops and abuse without hitting legitimate use.
  - **Expensive endpoints:** ``DEFAULT_EXPENSIVE_RATE_PER_MINUTE``
    per firm per rolling minute. Applies to the LLM-heavy
    routes (engagement run, section_deepening, export
    generation) that map cleanly onto a per-firm spend.

Implementation: windowed counter over ``sessions.created_at``
(for engagement-creation rate) and over the W20/D2
``metric_events`` rows for expensive-endpoint counts (the same
counter the dashboard reads).

Hard rule (W23/D3): the limit returns 429 with a clear
retry_after + emits a ``rate_limit.exceeded`` metric. The
dashboard surfaces the rate-limit status so an operator can see
the throttle coming.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from db.connection import acquire

logger = logging.getLogger(__name__)


DEFAULT_ENGAGEMENT_RATE_PER_HOUR = 60
# 60 / hour ≈ one per minute. A boutique firm running 5-10
# engagements/day stays well under; a runaway loop trips it
# within seconds.
DEFAULT_EXPENSIVE_RATE_PER_MINUTE = 30
# 30 / minute ≈ one expensive call every 2s. Generous for a
# real user; tight enough to catch automated abuse.


# ---------------------------------------------------------------------------
# Decision shape
# ---------------------------------------------------------------------------


@dataclass
class RateLimitDecision:
    """The result of a rate-limit check. The HTTP layer maps
    ``blocked=True`` to a 429 with the ``retry_after_seconds``
    header."""

    blocked: bool
    limit_name: str
    current_count: int
    limit: int
    window_seconds: int
    retry_after_seconds: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Engagement-creation rate limit (windowed against sessions.created_at)
# ---------------------------------------------------------------------------


async def check_engagement_creation_limit(
    firm_id: str | UUID,
    *,
    limit_per_hour: int = DEFAULT_ENGAGEMENT_RATE_PER_HOUR,
    now: datetime | None = None,
) -> RateLimitDecision:
    """Has the firm created more than ``limit_per_hour`` sessions
    in the rolling last 60 minutes?"""
    now = now or datetime.now(tz=timezone.utc)
    window_start = now - timedelta(hours=1)
    count = 0
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS n FROM sessions
                 WHERE firm_id = $1::uuid AND created_at >= $2
                """,
                str(firm_id), window_start,
            )
        count = int(row["n"]) if row else 0
    except Exception as e:  # noqa: BLE001
        logger.debug("engagement rate-limit read failed: %s", e)
        count = 0

    blocked = count >= limit_per_hour
    decision = RateLimitDecision(
        blocked=blocked,
        limit_name="engagement_creation",
        current_count=count,
        limit=limit_per_hour,
        window_seconds=3600,
        retry_after_seconds=3600 if blocked else 0,
        reason=(
            f"Firm has created {count} engagements in the last "
            f"hour; limit is {limit_per_hour}/hour. "
            "Wait until the rolling window clears."
            if blocked else
            f"{count}/{limit_per_hour} engagements created in "
            "the rolling hour"
        ),
    )
    if blocked:
        await _emit_rate_limit_metric("engagement_creation", firm_id)
    return decision


# ---------------------------------------------------------------------------
# Expensive-endpoint rate limit (windowed against metric_events)
# ---------------------------------------------------------------------------


_EXPENSIVE_METRIC_NAMES = (
    "llm.call",
    "engagement.started",
    "pipeline.stage_latency_ms",
)


async def check_expensive_endpoint_limit(
    firm_id: str | UUID,
    *,
    limit_per_minute: int = DEFAULT_EXPENSIVE_RATE_PER_MINUTE,
    now: datetime | None = None,
) -> RateLimitDecision:
    """Count ``llm.call`` events for this firm in the rolling last
    minute. Crosses the limit → 429 + metric."""
    now = now or datetime.now(tz=timezone.utc)
    window_start = now - timedelta(minutes=1)
    count = 0
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS n FROM metric_events
                 WHERE firm_id = $1::uuid
                   AND metric_name = 'llm.call'
                   AND recorded_at >= $2
                """,
                str(firm_id), window_start,
            )
        count = int(row["n"]) if row else 0
    except Exception as e:  # noqa: BLE001
        logger.debug("expensive rate-limit read failed: %s", e)
        count = 0

    blocked = count >= limit_per_minute
    decision = RateLimitDecision(
        blocked=blocked,
        limit_name="expensive_endpoint",
        current_count=count,
        limit=limit_per_minute,
        window_seconds=60,
        retry_after_seconds=60 if blocked else 0,
        reason=(
            f"Firm has made {count} LLM calls in the last minute; "
            f"limit is {limit_per_minute}/minute. Retry after the "
            "rolling window clears."
            if blocked else
            f"{count}/{limit_per_minute} LLM calls in the rolling minute"
        ),
    )
    if blocked:
        await _emit_rate_limit_metric("expensive_endpoint", firm_id)
    return decision


# ---------------------------------------------------------------------------
# Metric emission (W20/D2)
# ---------------------------------------------------------------------------


async def _emit_rate_limit_metric(
    limit_name: str, firm_id: str | UUID,
) -> None:
    """Emit a ``rate_limit.exceeded`` counter labelled by limit
    name. Best-effort — a metric outage cannot block the
    user-facing rate-limit response."""
    try:
        from core.observability.metrics import increment

        await increment(
            "rate_limit.exceeded",
            {"limit_name": limit_name, "firm_id": str(firm_id)},
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("rate_limit metric emit skipped: %s", e)


__all__ = [
    "DEFAULT_ENGAGEMENT_RATE_PER_HOUR",
    "DEFAULT_EXPENSIVE_RATE_PER_MINUTE",
    "RateLimitDecision",
    "check_engagement_creation_limit",
    "check_expensive_endpoint_limit",
]
