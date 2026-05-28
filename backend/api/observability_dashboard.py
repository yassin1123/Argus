"""Admin observability dashboard API — Phase 5 / Week 20 / Day 5.

One endpoint that returns the at-a-glance system-health view by
joining the four W20 components: metrics (D2), cost ledger (D3),
trace assembler (D4), structured logs (D1, indirectly via metrics).

W21/D5 extends the response with the verification-quality
panel: FP-rate-on-supported + recall-on-insufficient (from the
committed W21/D2 baseline.json) + red-team catch rate (from the
W21/D4 escapes.json). The trust number is now monitored on the
dashboard, not just measured once.

Firm-scoping rule matches the rest of W20: firm_admins see only
their own firm; system-admins see cross-firm. The endpoint never
recomputes anything — it reads from the layers we already built
+ assembles one response shape the React dashboard renders.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.dependencies import get_current_user
from core.observability.cost_rollups import cost_by_model, firm_cost
from core.observability.metrics import query_window
from core.observability.trace_view import recent_traces
from db.connection import acquire

logger = logging.getLogger(__name__)

# Paths to the committed quality reports. The dashboard reads
# them at request time so a re-run of the W21/D2 calibration or
# W21/D4 red-team updates the dashboard automatically.
_BACKEND = Path(__file__).resolve().parents[1]
_QUALITY_BASELINE_PATH = (
    _BACKEND / "eval_runs" / "week21_calibration" / "baseline.json"
)
_RED_TEAM_PATH = (
    _BACKEND / "eval_runs" / "week21_red_team" / "escapes.json"
)


def _load_quality_panel() -> dict[str, Any]:
    """Read the W21/D2 baseline + W21/D4 escapes JSON into the
    quality panel shape the dashboard renders. Both files are
    optional — when missing, the panel is marked unmeasured."""
    panel: dict[str, Any] = {
        "measured": False,
        "fp_rate_on_supported": None,
        "recall_on_insufficient": None,
        "accuracy": None,
        "red_team_catch_rate": None,
        "red_team_escapes": None,
        "verifier_source": None,
        "as_of": None,
    }
    try:
        if _QUALITY_BASELINE_PATH.exists():
            doc = json.loads(_QUALITY_BASELINE_PATH.read_text())
            h = doc.get("headline") or {}
            panel["fp_rate_on_supported"] = h.get("fp_rate_on_supported")
            panel["recall_on_insufficient"] = h.get("recall_on_insufficient")
            panel["accuracy"] = h.get("accuracy")
            panel["verifier_source"] = doc.get("verifier_source")
            panel["as_of"] = doc.get("generated_at")
            panel["measured"] = True
    except Exception as e:  # noqa: BLE001
        logger.debug("dashboard: baseline.json read skipped: %s", e)
    try:
        if _RED_TEAM_PATH.exists():
            rt = json.loads(_RED_TEAM_PATH.read_text())
            s = rt.get("summary") or {}
            panel["red_team_catch_rate"] = s.get("catch_rate")
            panel["red_team_escapes"] = s.get("escapes")
            panel["measured"] = True
    except Exception as e:  # noqa: BLE001
        logger.debug("dashboard: escapes.json read skipped: %s", e)
    return panel


router = APIRouter()


def _is_system_admin(user: dict) -> bool:
    return user.get("role") == "admin"


def _is_firm_admin(user: dict) -> bool:
    return user.get("default_firm_role") == "admin"


def _scope_firm_id(user: dict, requested: str | None) -> str | None:
    """Same gate as the W20/D2 metrics + W20/D3 cost endpoints —
    firm-admin forced to their default firm regardless of any
    ``?firm_id`` query-param override."""
    if _is_system_admin(user):
        return requested or None
    return user.get("default_firm_id")


async def _verification_distribution(
    firm_id: str | None, from_ts: datetime, to_ts: datetime,
) -> dict[str, Any]:
    """Roll up the verification.verdict counter into the quality
    signal Week 21 will tune NLI thresholds against."""
    rows = await query_window(
        "verification.verdict",
        from_ts=from_ts, to_ts=to_ts,
        firm_id=firm_id, group_by="outcome",
    )
    dist = {str(r["group"]): int(r["sum"]) for r in rows if r["group"]}
    total = sum(dist.values())
    # Supported = supported_high + supported_low; partial = weak;
    # insufficient = contradicted + unknown. Mirrors how the verifier
    # buckets verdicts in claim_state.
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


async def _engagement_volume(
    firm_id: str | None, from_ts: datetime, to_ts: datetime,
) -> dict[str, Any]:
    """Engagement counts + by-mode + success rate over the window."""
    started_rows = await query_window(
        "engagement.started", from_ts=from_ts, to_ts=to_ts,
        firm_id=firm_id, group_by="mode",
    )
    completed_rows = await query_window(
        "engagement.completed", from_ts=from_ts, to_ts=to_ts,
        firm_id=firm_id, group_by="mode",
    )
    failed_rows = await query_window(
        "engagement.failed", from_ts=from_ts, to_ts=to_ts,
        firm_id=firm_id, group_by="mode",
    )
    started = int(sum(r["sum"] for r in started_rows))
    completed = int(sum(r["sum"] for r in completed_rows))
    failed = int(sum(r["sum"] for r in failed_rows))
    finished = completed + failed
    return {
        "started": started,
        "completed": completed,
        "failed": failed,
        "in_flight": max(0, started - finished),
        "success_rate_pct": (completed / finished * 100.0) if finished else 0.0,
        "by_mode": {
            str(r["group"]): {
                "count": int(r["sum"]),
            }
            for r in started_rows if r["group"]
        },
    }


async def _artifact_count(
    firm_id: str | None, from_ts: datetime, to_ts: datetime,
) -> int:
    rows = await query_window(
        "artifact.generated", from_ts=from_ts, to_ts=to_ts,
        firm_id=firm_id, group_by=None,
    )
    return int(rows[0]["sum"]) if rows else 0


@router.get("/observability/dashboard")
async def get_dashboard(
    hours: int = Query(24, ge=1, le=720),
    firm_id: str | None = Query(
        None, description="(system-admin only) scope to one firm",
    ),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """System-health snapshot. Returns the bundle the React
    dashboard renders: volume, success rate, cost trend, verdict
    distribution, recent failures.
    """
    if not (_is_system_admin(user) or _is_firm_admin(user)):
        raise HTTPException(status_code=403, detail="Admin role required")

    scoped_firm = _scope_firm_id(user, firm_id)
    now = datetime.now(tz=timezone.utc)
    from_ts = now - timedelta(hours=int(hours))

    volume = await _engagement_volume(scoped_firm, from_ts, now)
    verdicts = await _verification_distribution(scoped_firm, from_ts, now)
    artifacts = await _artifact_count(scoped_firm, from_ts, now)

    # Cost: firm rollup for the scoped firm; cross-firm by-model
    # for system admins. firm_cost handles the firm_id=None case
    # by returning an empty FirmCost, so we branch on the scope.
    cost_panel: dict[str, Any]
    if scoped_firm is not None:
        fc = await firm_cost(scoped_firm, from_ts=from_ts, to_ts=now)
        cost_panel = {
            "scope": "firm",
            "firm_id": scoped_firm,
            "total_usd": fc.total_usd,
            "call_count": fc.call_count,
            "engagement_count": fc.engagement_count,
            "by_model": [r.to_dict() for r in fc.by_model],
        }
    else:
        rows = await cost_by_model(from_ts=from_ts, to_ts=now)
        cost_panel = {
            "scope": "system",
            "firm_id": None,
            "total_usd": float(sum(r["total_usd"] for r in rows)),
            "by_model": rows,
        }

    # Recent failures with cost burned + failed_stage so an operator
    # can click straight into the W20/D4 trace.
    failures = await recent_traces(
        status="failed", firm_id=scoped_firm,
        hours=int(hours), limit=10,
    )

    # W21/D5: the verification-quality panel. System-wide signal
    # — the same numbers everyone sees regardless of firm scope,
    # because the calibration was run against a shared golden set.
    quality = _load_quality_panel()

    # W23/D3: firm budget + rate-limit panel. Only meaningful for
    # firm-scoped requests (the cap is per-firm); the system-wide
    # view skips it.
    budget_panel: dict[str, Any] | None = None
    rate_limit_panel: dict[str, Any] | None = None
    if scoped_firm is not None:
        try:
            from core.cost_governance import (
                check_engagement_creation_limit,
                check_expensive_endpoint_limit,
                compute_budget_status,
            )
            budget = await compute_budget_status(scoped_firm)
            budget_panel = budget.to_dict()
            eng_limit = await check_engagement_creation_limit(scoped_firm)
            exp_limit = await check_expensive_endpoint_limit(scoped_firm)
            rate_limit_panel = {
                "engagement_creation": eng_limit.to_dict(),
                "expensive_endpoint": exp_limit.to_dict(),
            }
        except Exception as e:  # noqa: BLE001
            logger.debug("dashboard: budget/rate panel skipped: %s", e)

    # W24/D3: pilot-health panel. Firm-scoped only (the pilot is a
    # per-firm engagement); the system-wide view skips it. Visible to
    # the operator (system_admin scoping to the firm) + the pilot
    # firm_admin (forced to their own firm by _scope_firm_id).
    pilot_panel: dict[str, Any] | None = None
    if scoped_firm is not None:
        try:
            from core.pilot_feedback import pilot_health_panel
            pilot_panel = await pilot_health_panel(scoped_firm)
        except Exception as e:  # noqa: BLE001
            logger.debug("dashboard: pilot-health panel skipped: %s", e)

    return {
        "hours": int(hours),
        "from": from_ts.isoformat(),
        "to": now.isoformat(),
        "firm_scoped_to": scoped_firm,
        "volume": volume,
        "artifacts_generated": artifacts,
        "verification": verdicts,
        "verification_quality": quality,
        "cost": cost_panel,
        "budget": budget_panel,
        "rate_limits": rate_limit_panel,
        "pilot_health": pilot_panel,
        "recent_failures": failures,
    }


__all__ = ["router"]
