"""Metrics query + Prometheus export — Phase 5 / Week 20 / Day 2.

Two endpoints, both gated on admin:

  - ``GET /api/admin/metrics`` — time-windowed aggregate query.
    Firm-admins (``default_firm_role == 'admin'``) get their firm
    only — the ``firm_id`` filter is **forced** on the DB query
    regardless of any query-param value the caller tries to send.
    System-admins (``user.role == 'admin'``) get cross-firm
    visibility; they can pass ``?firm_id=<uuid>`` to scope.
  - ``GET /api/admin/metrics/prometheus`` — current aggregates
    rendered in Prometheus exposition format. Firm-scoped the
    same way. This is the **seam** for the future ops scrape —
    no Prometheus dependency is added; we just emit the text.

Hard rule: a firm-admin **cannot** read another firm's metrics
even by URL manipulation. The auth-resolution helper
:func:`_scope_firm_id` is the only path through which a non-None
firm_id reaches the DB — it always returns the firm-admin's
own ``default_firm_id`` and never accepts a caller-supplied
override for that role.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from auth.dependencies import get_current_user
from core.observability.metrics import (
    list_metric_names,
    query_window,
    render_prometheus,
)

router = APIRouter()


def _is_system_admin(user: dict) -> bool:
    """A platform-level admin (``users.role == 'admin'``) sees
    every firm's metrics. Distinct from a firm-scope admin who
    only sees their own."""
    return user.get("role") == "admin"


def _is_firm_admin(user: dict) -> bool:
    """A firm-scope admin (``firm_memberships.role == 'admin'``)
    sees only their default firm's metrics."""
    return user.get("default_firm_role") == "admin"


def _scope_firm_id(user: dict, requested: str | None) -> str | None:
    """Resolve the firm_id filter to apply on every metrics
    query. Returns ``None`` only when the caller is a system
    admin AND they explicitly didn't ask for a firm filter.

    Forces the firm-admin's own firm regardless of any
    caller-supplied ``firm_id`` query param — that's the
    cross-firm leak prevention. Anyone who isn't an admin at
    all is rejected upstream by the route handler.
    """
    if _is_system_admin(user):
        # System admin: honour an explicit ?firm_id, else cross-firm view.
        return requested or None
    # Firm admin: forced to their own firm, ignoring the query param.
    return user.get("default_firm_id")


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # ``fromisoformat`` accepts the W3C ISO 8601 forms our UI uses.
        # Trailing ``Z`` is converted to ``+00:00`` for the parser.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"invalid ISO timestamp: {s!r}",
        )


@router.get("/metrics")
async def get_metrics(
    metric: str = Query(..., description="metric name, e.g. llm.call"),
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    group_by: str | None = Query(
        None, description="label name to group by, e.g. provider",
    ),
    firm_id: str | None = Query(
        None, description="(system-admin only) restrict to one firm",
    ),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Aggregate ``metric_events`` rows over a window, optionally
    grouped by one label dimension. Default window is the last 24
    hours when neither ``from`` nor ``to`` is supplied.
    """
    if not (_is_system_admin(user) or _is_firm_admin(user)):
        raise HTTPException(
            status_code=403, detail="Admin role required",
        )
    scoped_firm = _scope_firm_id(user, firm_id)
    f = _parse_iso(from_ts)
    t = _parse_iso(to_ts)
    if f is None and t is None:
        # Default window: last 24h ending now (so a dashboard
        # request that omits the range still answers usefully).
        t = datetime.now(tz=timezone.utc)
        f = t - timedelta(hours=24)

    rows = await query_window(
        metric,
        from_ts=f, to_ts=t,
        firm_id=scoped_firm,
        group_by=group_by,
    )
    return {
        "metric": metric,
        "from": f.isoformat() if f else None,
        "to": t.isoformat() if t else None,
        "group_by": group_by,
        "firm_scoped_to": scoped_firm,
        "rows": rows,
    }


@router.get("/metrics/prometheus")
async def get_metrics_prometheus(
    firm_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
) -> Response:
    """Render every metric as Prometheus exposition-format text.
    Same firm-scoping rule as the JSON endpoint; firm-admins
    cannot reach another firm's exposure.
    """
    if not (_is_system_admin(user) or _is_firm_admin(user)):
        raise HTTPException(
            status_code=403, detail="Admin role required",
        )
    scoped_firm = _scope_firm_id(user, firm_id)
    text = await render_prometheus(firm_id=scoped_firm)
    return Response(
        content=text,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/metrics/names")
async def get_metric_names(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """List the metric names that have at least one event in
    scope. Cheap discovery surface for a UI dashboard."""
    if not (_is_system_admin(user) or _is_firm_admin(user)):
        raise HTTPException(
            status_code=403, detail="Admin role required",
        )
    scoped_firm = _scope_firm_id(user, None)
    names = await list_metric_names(firm_id=scoped_firm)
    return {"firm_scoped_to": scoped_firm, "metric_names": names}


__all__ = ["router"]
