"""Cost ledger writer — Phase 5 / Week 20 / Day 3.

One write per LLM call, attributing cost to ``(firm_id,
session_id, agent, provider, model)``. The cost value itself is
**not** recomputed here — it's whatever the existing
:func:`core.inference.litellm_client.estimate_cost` produced for
that call (token counts × LiteLLM's pricing table). This module
just persists the value with full attribution so the rollups
have a single source of truth.

Why a separate module from :mod:`metrics`: cost data has a
different durability bar than metrics. Metric drops are tolerable
(the dashboard shows fewer samples); cost drops cost the firm
money. We log loudly on every write failure so an operator
investigating "the bill doesn't match" can find the gaps.

Best-effort writes still — a ledger outage cannot fail an
engagement run. But we WARN, not DEBUG.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from db.connection import acquire

from .trace import get_trace_context

logger = logging.getLogger(__name__)


def _coerce_uuid(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    s = str(value)
    if len(s) == 36 and s.count("-") == 4:
        return s
    return None


async def _resolve_firm_id(session_id: str | None) -> str | None:
    """Look up the firm_id for a session. Used when the caller
    didn't pass firm_id explicitly (the common case — record_llm_call
    only has session_id today). Falls through to the trace context
    when DB lookup fails."""
    if session_id:
        try:
            async with acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT firm_id FROM sessions WHERE id = $1::uuid",
                    session_id,
                )
            if row and row["firm_id"]:
                return _coerce_uuid(row["firm_id"])
        except Exception as e:  # noqa: BLE001
            logger.debug("firm_id lookup skipped: %s", e)
    return _coerce_uuid(get_trace_context().firm_id)


async def record_cost(
    *,
    trace_id: str | None,
    session_id: str | None,
    firm_id: str | None,
    agent: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    """Persist one row to ``cost_ledger``.

    Hard-rule compliance:
      - never recomputes ``cost_usd`` — the value is whatever the
        caller passed (from the existing LiteLLM pricing helper)
      - best-effort: a DB failure is logged at WARNING (not
        DEBUG) but never raised — the pipeline must not couple
        to the ledger
      - skips the write when no firm_id can be resolved (the
        ledger schema forces NOT NULL on firm_id; orphan rows
        would just fail the insert + log noise). We log INFO
        in that case so the gap is visible.

    Returns ``None``. Callers don't need the row id — the
    rollups query by (session_id, firm_id), not by ledger id.
    """
    if cost_usd is None or float(cost_usd) <= 0:
        # Free / zero-cost calls (cache hits, mocked tests, tiny
        # gemini-flash invocations) don't need a ledger row. The
        # metric layer still records the call count + latency.
        return

    resolved_firm = _coerce_uuid(firm_id) or await _resolve_firm_id(session_id)
    if resolved_firm is None:
        logger.info(
            "cost ledger: skipping row — no firm_id resolved "
            "(session=%s agent=%s model=%s)",
            session_id, agent, model,
        )
        return

    resolved_trace = _coerce_uuid(trace_id) or _coerce_uuid(get_trace_context().trace_id)
    resolved_session = _coerce_uuid(session_id)

    try:
        async with acquire() as conn:
            await conn.execute(
                """
                INSERT INTO cost_ledger
                    (trace_id, session_id, firm_id, agent,
                     provider, model,
                     prompt_tokens, completion_tokens, cost_usd)
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4,
                        $5, $6,
                        $7, $8, $9)
                """,
                resolved_trace,
                resolved_session,
                resolved_firm,
                str(agent or "unknown"),
                str(provider or "unknown"),
                str(model or "unknown"),
                int(prompt_tokens or 0),
                int(completion_tokens or 0),
                float(cost_usd),
            )
    except Exception as e:  # noqa: BLE001
        # Loudly — cost data matters. Operator can see this in
        # the log + the metrics layer's error.count counter.
        logger.warning(
            "cost_ledger insert FAILED: %s "
            "(session=%s firm=%s agent=%s model=%s cost=$%.6f)",
            e, session_id, resolved_firm, agent, model, cost_usd,
        )


__all__ = ["record_cost"]
