"""Centralized firm-scope guard — Phase 5 / Week 23 / Day 1.

Single chokepoint every API path that exposes firm-scoped data
should route through. Two goals:

  1. Make tenant isolation impossible to forget when a new
     feature lands. A route that fetches a resource calls
     :func:`assert_firm_access` with the requesting user + the
     resource's firm_id; the helper raises a 404 on a mismatch
     so cross-firm attempts can't probe for existence
     (anti-enumeration — never reveal that an ID exists in
     another firm).
  2. Emit a uniform observability signal on every denial. The
     W20/D2 metrics + W20/D1 structured-event stacks already
     run; we send ``security.cross_firm_denied`` events through
     them so attempts are visible.

Hard-rule discipline (from the W23/D1 spec):

  - Cross-firm access returns 404, not 403. Surfacing a 403
    reveals that the resource exists in some other firm.
  - The metric label carries IDs + the attempted resource type,
    NEVER any leaked content. This matches the W20/D1 privacy
    rule — log that a denial happened, not what was almost
    exposed.
  - System-admins (users.role == "admin") bypass the guard
    intentionally for cross-firm operations (admin dashboard,
    cost rollups, etc.). The guard surfaces this in the metric
    label so a system-admin's cross-firm read is visible in the
    audit trail without being denied.

The companion :func:`get_session_firm_id` is a small DB helper
every route that scopes by session can reuse — keeps the JOIN
to ``sessions.firm_id`` consistent and easy to mock in tests.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status

from db.connection import acquire

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public guard
# ---------------------------------------------------------------------------


_NOT_FOUND_MESSAGE = "Not Found"
# Sentinel message — always the same string regardless of why the
# guard fired, so a probing client can't differentiate "resource
# doesn't exist" from "resource exists in another firm."


async def assert_firm_access(
    *,
    user: dict[str, Any],
    resource_firm_id: str | None,
    resource_kind: str,
    resource_id: str | None = None,
    allow_system_admin: bool = True,
) -> None:
    """Raise HTTP 404 if ``user`` cannot read a resource that
    lives in ``resource_firm_id``.

    Parameters
    ----------
    user:
        The auth-resolved user dict (``user_id``, ``role``,
        ``default_firm_id``, ``default_firm_role``).
    resource_firm_id:
        The ``firm_id`` of the resource being accessed. ``None``
        means the lookup failed (resource doesn't exist OR caller
        passed a bogus id); in either case we return 404 because
        the caller has no business knowing the difference.
    resource_kind:
        Short string naming the resource class for the
        observability label, e.g. ``"session"``, ``"comment"``,
        ``"artifact"``, ``"engagement_membership"``,
        ``"payload_version"``. ``["a-z_]+]`` only — no free text.
    resource_id:
        Optional id of the resource being accessed, recorded on
        the metric for incident triage. Never any content.
    allow_system_admin:
        When ``True`` (the default), users with
        ``role == "admin"`` may read cross-firm. We still emit a
        ``cross_firm_system_admin_read`` metric so the access is
        visible in the audit trail; we just don't deny it.

    Raises ``HTTPException(404)`` on a deny. Returns ``None`` on
    a grant.
    """
    # No resource → no leak possible; the route's own 404 path
    # handles this. Emit nothing.
    if resource_firm_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_FOUND_MESSAGE,
        )

    user_firm = (user or {}).get("default_firm_id")
    is_system_admin = (user or {}).get("role") == "admin"

    if str(user_firm or "") == str(resource_firm_id):
        return  # ordinary same-firm access; no metric

    if is_system_admin and allow_system_admin:
        # Allowed but visible. The dashboard + audit log surface
        # these.
        await _emit_cross_firm_event(
            event="cross_firm_system_admin_read",
            user=user,
            resource_firm_id=resource_firm_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            outcome="allowed",
        )
        return

    await _emit_cross_firm_event(
        event="cross_firm_denied",
        user=user,
        resource_firm_id=resource_firm_id,
        resource_kind=resource_kind,
        resource_id=resource_id,
        outcome="denied",
    )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_NOT_FOUND_MESSAGE,
    )


# ---------------------------------------------------------------------------
# Session-firm lookup helper
# ---------------------------------------------------------------------------


async def get_session_firm_id(session_id: str | None) -> str | None:
    """Look up the firm_id for a session. Used by every route
    that scopes by session — keeps the SQL in one place + makes
    the test fakes simple."""
    if not session_id:
        return None
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT firm_id FROM sessions WHERE id = $1::uuid",
                session_id,
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("get_session_firm_id failed: %s", e)
        return None
    return str(row["firm_id"]) if row and row["firm_id"] else None


# ---------------------------------------------------------------------------
# Observability emission
# ---------------------------------------------------------------------------


async def _emit_cross_firm_event(
    *,
    event: str,
    user: dict[str, Any] | None,
    resource_firm_id: str,
    resource_kind: str,
    resource_id: str | None,
    outcome: str,
) -> None:
    """Emit a structured log + metric for the cross-firm access.

    No claim text, evidence text, or resource content leaves this
    function — only IDs + the resource kind + the outcome. The
    W20/D1 redact rule + the W20/D2 label sanitiser already
    enforce this; we keep the call sites narrow as a second line
    of defence.
    """
    user_id = (user or {}).get("user_id")
    user_firm = (user or {}).get("default_firm_id")

    # Structured log (W20/D1)
    try:
        from core.observability.logging import emit_event

        emit_event(
            f"security.{event}",
            level=logging.WARNING if outcome == "denied" else logging.INFO,
            resource_kind=resource_kind,
            resource_id=resource_id,
            resource_firm_id=resource_firm_id,
            user_id=str(user_id) if user_id else None,
            user_firm_id=str(user_firm) if user_firm else None,
            outcome=outcome,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("emit_event(security) skipped: %s", e)

    # Metric (W20/D2)
    try:
        from core.observability.metrics import increment

        await increment(
            f"security.{event}",
            {
                "resource_kind": resource_kind,
                "outcome": outcome,
                "user_firm_id": user_firm,
                "resource_firm_id": resource_firm_id,
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("metric increment(security) skipped: %s", e)


__all__ = [
    "assert_firm_access",
    "get_session_firm_id",
]
