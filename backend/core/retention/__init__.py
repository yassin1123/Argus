"""Data retention + hard-deletion — Phase 5 / Week 23 / Day 2.

Two surfaces:

  - :mod:`deletion` — ``purge_engagement(session_id, actor)``
    permanently removes an engagement + every associated row +
    every artifact file. Writes ONE row to ``purge_audit_log``
    carrying counts + actor + reason, with zero client content.
  - :mod:`policy` — per-firm retention windows + the sweep that
    flags expired engagements, notifies the firm_admin, waits
    out the grace period, then triggers a purge.

Hard rules (W23/D2 spec):
  - Purge means purge — verified zero residual rows AND files.
  - Nothing vanishes silently — flag + notify + grace period.
  - The deletion audit row has no client content.
  - Purge is firm-admin-only, confirmed, firm-scoped.
"""

from .deletion import PurgeReport, purge_engagement
from .policy import (
    DEFAULT_RETENTION_GRACE_DAYS,
    RetentionDecision,
    decide_retention_action,
    list_expired_sessions,
    set_firm_retention_days,
)

__all__ = [
    "DEFAULT_RETENTION_GRACE_DAYS",
    "PurgeReport",
    "RetentionDecision",
    "decide_retention_action",
    "list_expired_sessions",
    "purge_engagement",
    "set_firm_retention_days",
]
