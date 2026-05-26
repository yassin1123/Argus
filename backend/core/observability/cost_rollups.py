"""Cost rollups — Phase 5 / Week 20 / Day 3.

Three roll-up shapes, plus the canonical session-total helper
that any per-engagement cost-cap gate should call.

  - :func:`session_cost_total` — single float, the sum of every
    ledger row attributed to a session. The "how much has this
    engagement cost" question, source-of-truth.
  - :func:`engagement_cost` — total + breakdown by agent and by
    model. What the per-engagement cost panel reads.
  - :func:`firm_cost` — windowed total + per-engagement +
    per-model breakdowns. What the firm-admin dashboard reads.
  - :func:`cost_by_model` — system-wide model cost distribution
    over a window. What the system-admin uses to spot a runaway
    provider.

The rollups never recompute cost — they SUM ``cost_ledger.cost_usd``.
Same data, same value, no drift between the ledger and what the
API surfaces.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from db.connection import acquire

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


@dataclass
class CostBreakdownRow:
    """One row in an ``EngagementCost.by_agent`` / ``by_model``
    breakdown."""

    label: str
    count: int
    cost_usd: float
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EngagementCost:
    """Engagement-cost panel shape."""

    session_id: str
    total_usd: float = 0.0
    call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    by_agent: list[CostBreakdownRow] = field(default_factory=list)
    by_model: list[CostBreakdownRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "total_usd": self.total_usd,
            "call_count": self.call_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "by_agent": [r.to_dict() for r in self.by_agent],
            "by_model": [r.to_dict() for r in self.by_model],
        }


@dataclass
class FirmCost:
    """Firm-admin dashboard shape."""

    firm_id: str
    from_ts: str | None = None
    to_ts: str | None = None
    total_usd: float = 0.0
    call_count: int = 0
    engagement_count: int = 0
    by_engagement: list[CostBreakdownRow] = field(default_factory=list)
    by_model: list[CostBreakdownRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "firm_id": self.firm_id,
            "from": self.from_ts, "to": self.to_ts,
            "total_usd": self.total_usd,
            "call_count": self.call_count,
            "engagement_count": self.engagement_count,
            "by_engagement": [r.to_dict() for r in self.by_engagement],
            "by_model": [r.to_dict() for r in self.by_model],
        }


# ---------------------------------------------------------------------------
# Canonical session-total — used by cost-cap gates
# ---------------------------------------------------------------------------


async def session_cost_total(session_id: str) -> float:
    """Sum every ledger row for ``session_id``. The authoritative
    "how much has this engagement cost so far" — every per-run
    cost-cap gate should call this rather than maintain its own
    accumulator. One source of truth.

    Returns 0.0 on any DB failure so a transient ledger outage
    can't artificially trip a cost-cap gate. The :mod:`cost`
    recorder logs ledger-write failures loudly, so an operator
    can see if rows are being lost.
    """
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(cost_usd), 0)::float AS total "
                "FROM cost_ledger WHERE session_id = $1::uuid",
                session_id,
            )
        return float(row["total"]) if row else 0.0
    except Exception as e:  # noqa: BLE001
        logger.warning("session_cost_total query failed: %s", e)
        return 0.0


# ---------------------------------------------------------------------------
# Engagement breakdown
# ---------------------------------------------------------------------------


async def engagement_cost(session_id: str) -> EngagementCost:
    """Return total + per-agent + per-model breakdown for one
    engagement. Read by the workspace cost panel."""
    out = EngagementCost(session_id=session_id)
    try:
        async with acquire() as conn:
            total_row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(cost_usd), 0)::float    AS total,
                    COUNT(*)                              AS call_count,
                    COALESCE(SUM(prompt_tokens), 0)::int     AS pt,
                    COALESCE(SUM(completion_tokens), 0)::int AS ct
                FROM cost_ledger WHERE session_id = $1::uuid
                """,
                session_id,
            )
            by_agent_rows = await conn.fetch(
                """
                SELECT agent AS label,
                       COUNT(*)                              AS count,
                       COALESCE(SUM(cost_usd), 0)::float    AS cost_usd,
                       COALESCE(SUM(prompt_tokens), 0)::int     AS pt,
                       COALESCE(SUM(completion_tokens), 0)::int AS ct
                FROM cost_ledger WHERE session_id = $1::uuid
                GROUP BY agent ORDER BY cost_usd DESC
                """,
                session_id,
            )
            by_model_rows = await conn.fetch(
                """
                SELECT model AS label,
                       COUNT(*)                              AS count,
                       COALESCE(SUM(cost_usd), 0)::float    AS cost_usd,
                       COALESCE(SUM(prompt_tokens), 0)::int     AS pt,
                       COALESCE(SUM(completion_tokens), 0)::int AS ct
                FROM cost_ledger WHERE session_id = $1::uuid
                GROUP BY model ORDER BY cost_usd DESC
                """,
                session_id,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("engagement_cost query failed: %s", e)
        return out

    if total_row:
        out.total_usd = float(total_row["total"] or 0.0)
        out.call_count = int(total_row["call_count"] or 0)
        out.prompt_tokens = int(total_row["pt"] or 0)
        out.completion_tokens = int(total_row["ct"] or 0)
    out.by_agent = [
        CostBreakdownRow(
            label=r["label"], count=int(r["count"]),
            cost_usd=float(r["cost_usd"]),
            prompt_tokens=int(r["pt"]),
            completion_tokens=int(r["ct"]),
        )
        for r in by_agent_rows
    ]
    out.by_model = [
        CostBreakdownRow(
            label=r["label"], count=int(r["count"]),
            cost_usd=float(r["cost_usd"]),
            prompt_tokens=int(r["pt"]),
            completion_tokens=int(r["ct"]),
        )
        for r in by_model_rows
    ]
    return out


# ---------------------------------------------------------------------------
# Firm rollup
# ---------------------------------------------------------------------------


async def firm_cost(
    firm_id: str,
    *,
    from_ts: Any | None = None,
    to_ts: Any | None = None,
) -> FirmCost:
    """Windowed firm-level cost rollup.

    The endpoint caller is responsible for the auth check
    (firm_admin for own firm, system_admin for any firm) —
    this layer just executes the filter.
    """
    out = FirmCost(
        firm_id=firm_id,
        from_ts=from_ts.isoformat() if from_ts else None,
        to_ts=to_ts.isoformat() if to_ts else None,
    )
    where_clauses = ["firm_id = $1::uuid"]
    params: list[Any] = [firm_id]
    if from_ts is not None:
        params.append(from_ts)
        where_clauses.append(f"recorded_at >= ${len(params)}")
    if to_ts is not None:
        params.append(to_ts)
        where_clauses.append(f"recorded_at < ${len(params)}")
    where = " AND ".join(where_clauses)

    try:
        async with acquire() as conn:
            total = await conn.fetchrow(
                f"""
                SELECT
                    COALESCE(SUM(cost_usd), 0)::float       AS total,
                    COUNT(*)                                  AS call_count,
                    COUNT(DISTINCT session_id)                AS engagement_count
                FROM cost_ledger WHERE {where}
                """,
                *params,
            )
            by_eng = await conn.fetch(
                f"""
                SELECT COALESCE(session_id::text, 'unattributed') AS label,
                       COUNT(*)                              AS count,
                       COALESCE(SUM(cost_usd), 0)::float    AS cost_usd,
                       COALESCE(SUM(prompt_tokens), 0)::int     AS pt,
                       COALESCE(SUM(completion_tokens), 0)::int AS ct
                FROM cost_ledger WHERE {where}
                GROUP BY session_id ORDER BY cost_usd DESC LIMIT 100
                """,
                *params,
            )
            by_model = await conn.fetch(
                f"""
                SELECT model AS label,
                       COUNT(*)                              AS count,
                       COALESCE(SUM(cost_usd), 0)::float    AS cost_usd,
                       COALESCE(SUM(prompt_tokens), 0)::int     AS pt,
                       COALESCE(SUM(completion_tokens), 0)::int AS ct
                FROM cost_ledger WHERE {where}
                GROUP BY model ORDER BY cost_usd DESC
                """,
                *params,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("firm_cost query failed: %s", e)
        return out

    if total:
        out.total_usd = float(total["total"] or 0.0)
        out.call_count = int(total["call_count"] or 0)
        out.engagement_count = int(total["engagement_count"] or 0)
    out.by_engagement = [
        CostBreakdownRow(
            label=r["label"], count=int(r["count"]),
            cost_usd=float(r["cost_usd"]),
            prompt_tokens=int(r["pt"]),
            completion_tokens=int(r["ct"]),
        )
        for r in by_eng
    ]
    out.by_model = [
        CostBreakdownRow(
            label=r["label"], count=int(r["count"]),
            cost_usd=float(r["cost_usd"]),
            prompt_tokens=int(r["pt"]),
            completion_tokens=int(r["ct"]),
        )
        for r in by_model
    ]
    return out


# ---------------------------------------------------------------------------
# System-wide by-model
# ---------------------------------------------------------------------------


async def cost_by_model(
    *,
    from_ts: Any | None = None,
    to_ts: Any | None = None,
) -> list[dict[str, Any]]:
    """System-wide cost distribution by model over a window.
    System-admin only — the API layer enforces the role check.
    """
    where_clauses: list[str] = []
    params: list[Any] = []
    if from_ts is not None:
        params.append(from_ts)
        where_clauses.append(f"recorded_at >= ${len(params)}")
    if to_ts is not None:
        params.append(to_ts)
        where_clauses.append(f"recorded_at < ${len(params)}")
    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT model, provider,
                       COUNT(*)                              AS call_count,
                       COALESCE(SUM(cost_usd), 0)::float    AS total_usd,
                       COALESCE(SUM(prompt_tokens), 0)::int     AS prompt_tokens,
                       COALESCE(SUM(completion_tokens), 0)::int AS completion_tokens
                FROM cost_ledger {where}
                GROUP BY model, provider ORDER BY total_usd DESC
                """,
                *params,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("cost_by_model query failed: %s", e)
        return []
    return [
        {
            "model": r["model"], "provider": r["provider"],
            "call_count": int(r["call_count"]),
            "total_usd": float(r["total_usd"]),
            "prompt_tokens": int(r["prompt_tokens"]),
            "completion_tokens": int(r["completion_tokens"]),
        }
        for r in rows
    ]


__all__ = [
    "CostBreakdownRow",
    "EngagementCost",
    "FirmCost",
    "cost_by_model",
    "engagement_cost",
    "firm_cost",
    "session_cost_total",
]
