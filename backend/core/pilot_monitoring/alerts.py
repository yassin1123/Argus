"""Pilot alert evaluation + operator delivery — Phase 5 / Week 25 / Day 2.

Lightweight, firm-scoped. The conditions are deliberately few — the
point of a live-pilot alert is signal, not noise.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from db.connection import acquire

logger = logging.getLogger(__name__)


# --- thresholds (tuned for a small, closely-watched pilot) ------------------
ERROR_RATE_SPIKE_PCT = 50.0        # >=50% of finished engagements failed
ERROR_RATE_MIN_FINISHED = 3        # ...over at least this many finished
VERIFICATION_MIN_TOTAL = 8         # need a meaningful sample to call anomaly
VERIFICATION_INSUFFICIENT_CEILING = 70.0   # >=70% insufficient is anomalous
VERIFICATION_SUPPORTED_FLOOR = 5.0         # <5% supported (with volume) too


@dataclass
class PilotAlert:
    kind: str            # engagement_failure | error_rate_spike |
                         # budget_threshold | verification_anomaly
    severity: str        # warn | critical
    firm_id: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Verification-distribution anomaly (pure function — easy to unit test)
# ---------------------------------------------------------------------------


def detect_verification_anomaly(dist: dict[str, Any]) -> tuple[bool, str]:
    """Flag a verification distribution that's gone sideways. ``dist`` is
    the ``_verification_distribution`` shape (total + *_pct). Below the
    minimum sample we never flag (too little signal)."""
    total = int(dist.get("total") or 0)
    if total < VERIFICATION_MIN_TOTAL:
        return False, f"sample too small ({total} < {VERIFICATION_MIN_TOTAL})"
    insufficient_pct = float(dist.get("insufficient_pct") or 0.0)
    supported_pct = float(dist.get("supported_pct") or 0.0)
    if insufficient_pct >= VERIFICATION_INSUFFICIENT_CEILING:
        return True, (
            f"{insufficient_pct:.0f}% of {total} claims came back "
            f"insufficient (>= {VERIFICATION_INSUFFICIENT_CEILING:.0f}%) — "
            "likely a retrieval / firm-content issue, not the verifier"
        )
    if supported_pct < VERIFICATION_SUPPORTED_FLOOR:
        return True, (
            f"only {supported_pct:.0f}% of {total} claims supported "
            f"(< {VERIFICATION_SUPPORTED_FLOOR:.0f}%) — verification mix "
            "is abnormally low; check the firm's evidence"
        )
    return False, "distribution within normal range"


# ---------------------------------------------------------------------------
# Alert evaluation
# ---------------------------------------------------------------------------


async def evaluate_pilot_alerts(
    firm_id: str | UUID,
    *,
    now: datetime | None = None,
    window_minutes: int = 30,
    verification_distribution: dict[str, Any] | None = None,
) -> list[PilotAlert]:
    """Evaluate every live-pilot alert condition for ``firm_id`` over the
    recent window. Pure-ish: reads DB + budget; never dispatches."""
    now = now or datetime.now(tz=timezone.utc)
    fid = str(firm_id)
    window_start = now - timedelta(minutes=window_minutes)
    alerts: list[PilotAlert] = []

    # --- engagement failures + error-rate spike (over the window) ---
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT status, COUNT(*)::int AS n
              FROM sessions
             WHERE firm_id = $1::uuid AND updated_at >= $2
             GROUP BY status
            """,
            fid, window_start,
        )
    by_status = {r["status"]: int(r["n"]) for r in rows}
    failed = by_status.get("failed", 0)
    completed = by_status.get("complete", 0)
    insufficient = by_status.get("insufficient", 0)
    finished = failed + completed + insufficient

    if failed > 0:
        alerts.append(PilotAlert(
            kind="engagement_failure", severity="critical", firm_id=fid,
            detail=(
                f"{failed} engagement(s) failed in the last "
                f"{window_minutes} min — pull the trace (W20) to find the "
                "failed stage"
            ),
            data={"failed": failed, "window_minutes": window_minutes},
        ))

    if finished >= ERROR_RATE_MIN_FINISHED:
        err_rate = 100.0 * failed / finished
        if err_rate >= ERROR_RATE_SPIKE_PCT:
            alerts.append(PilotAlert(
                kind="error_rate_spike", severity="critical", firm_id=fid,
                detail=(
                    f"{err_rate:.0f}% error rate "
                    f"({failed}/{finished} finished engagements failed)"
                ),
                data={"error_rate_pct": round(err_rate, 1),
                      "failed": failed, "finished": finished},
            ))

    # --- budget thresholds (reuse W23 budget status) ---
    try:
        from core.cost_governance import compute_budget_status
        status = await compute_budget_status(fid, now=now)
        if status.used_pct is not None:
            if status.used_pct >= 100.0:
                alerts.append(PilotAlert(
                    kind="budget_threshold", severity="critical", firm_id=fid,
                    detail=(
                        f"budget {status.used_pct:.0f}% used "
                        f"(${status.month_to_date_usd:.2f} / "
                        f"${status.monthly_budget_usd:.2f}) — new engagements "
                        "soft-stopped"
                    ),
                    data=status.to_dict(),
                ))
            elif status.used_pct >= 80.0:
                alerts.append(PilotAlert(
                    kind="budget_threshold", severity="warn", firm_id=fid,
                    detail=(
                        f"budget {status.used_pct:.0f}% used — approaching "
                        "the cap"
                    ),
                    data=status.to_dict(),
                ))
    except Exception as e:  # noqa: BLE001
        logger.debug("budget alert eval skipped: %s", e)

    # --- anomalous verification distribution ---
    if verification_distribution is not None:
        anomalous, reason = detect_verification_anomaly(verification_distribution)
        if anomalous:
            alerts.append(PilotAlert(
                kind="verification_anomaly", severity="warn", firm_id=fid,
                detail=reason,
                data={"distribution": verification_distribution},
            ))

    return alerts


# ---------------------------------------------------------------------------
# Operator delivery
# ---------------------------------------------------------------------------


async def _post_webhook(alert: PilotAlert) -> bool:
    """Best-effort POST to ARGUS_OPS_WEBHOOK_URL (Slack-style). Never
    raises; returns True on a 2xx."""
    url = os.getenv("ARGUS_OPS_WEBHOOK_URL")
    if not url:
        return False
    payload = {
        "text": f"[Argus pilot] {alert.severity.upper()} {alert.kind}: "
                f"{alert.detail}",
        "alert": alert.to_dict(),
    }
    try:
        import urllib.request
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        # Run the blocking call off the event loop.
        import asyncio
        def _send() -> int:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status
        status = await asyncio.to_thread(_send)
        return 200 <= status < 300
    except Exception as e:  # noqa: BLE001
        logger.warning("ops webhook post failed: %s", e)
        return False


async def dispatch_pilot_alert(alert: PilotAlert) -> dict[str, Any]:
    """Deliver an alert to the operator. Two channels, both best-effort:
      1. a W18 in-app notification to every system-admin (role='admin'),
      2. an optional ops webhook (ARGUS_OPS_WEBHOOK_URL).
    Returns ``{notified: <n>, webhook: <bool>}``. Idempotency is the
    caller's job (don't re-evaluate + re-dispatch the same alert every
    poll); see :func:`live.live_pilot_view` which evaluates but does not
    auto-dispatch."""
    notified = 0
    summary = f"[{alert.severity.upper()}] {alert.kind}: {alert.detail}"[:500]
    try:
        async with acquire() as conn:
            admins = await conn.fetch(
                "SELECT id FROM users WHERE role = 'admin'",
            )
            for a in admins:
                try:
                    await conn.execute(
                        """
                        INSERT INTO notifications
                            (recipient_id, firm_id, notification_type,
                             source_ref, actor_id, summary, read, email_status)
                        VALUES ($1::uuid, $2::uuid, 'pilot_alert',
                                $3::jsonb, NULL, $4, FALSE, 'skipped')
                        """,
                        a["id"], alert.firm_id,
                        json.dumps(alert.to_dict()), summary,
                    )
                    notified += 1
                except Exception as e:  # noqa: BLE001
                    logger.debug("pilot alert notify skipped for %s: %s",
                                 a["id"], e)
    except Exception as e:  # noqa: BLE001
        logger.warning("pilot alert dispatch failed: %s", e)

    webhook_ok = await _post_webhook(alert)
    return {"notified": notified, "webhook": webhook_ok}


__all__ = [
    "ERROR_RATE_SPIKE_PCT",
    "PilotAlert",
    "detect_verification_anomaly",
    "dispatch_pilot_alert",
    "evaluate_pilot_alerts",
]
