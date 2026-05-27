"""Health endpoints — Phase 5 / Week 23 / Day 4.

Two endpoints:

  - ``GET /health``           — minimal liveness + degraded flag.
    Always public (no auth). Returns 200 even when degraded so
    a load balancer can route traffic; the body surfaces the
    degraded state for the operator dashboard.
  - ``GET /health/detailed``  — full :class:`ConfigReport` plus
    runtime info. Includes per-check status. Public OK for an
    internal pilot deploy; lock down behind admin auth later if
    needed.

Hard rule (W23/D4): the response NEVER carries secret values.
Each check's ``detail`` field is a state description ("present"
/ "MISSING — …") — never the key itself.
"""

from __future__ import annotations

from fastapi import APIRouter

from core.config import get_boot_report, get_mode, validate_at_boot

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Minimal liveness probe. 200 OK even when degraded — the
    server is up; the orchestrator's strict-mode guard fires
    later when an engagement is requested. Body surfaces the
    degraded flag for the load balancer's structured logger."""
    report = get_boot_report() or validate_at_boot()
    return {
        "status": "ok",
        "mode": report.mode,
        "strict": report.strict,
        "can_run_real_verifier": report.can_run_real_verifier,
        "degraded": report.degraded,
    }


@router.get("/health/detailed")
async def health_detailed() -> dict:
    """Full boot-time check report. Every critical-config check's
    state, plus the mode + strict flag + the can_run_real_verifier
    summary. Detail strings carry only state descriptions —
    never any secret values."""
    report = get_boot_report() or validate_at_boot()
    return report.to_dict()


__all__ = ["router"]
