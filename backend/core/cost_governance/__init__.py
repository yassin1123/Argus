"""Cost governance — Phase 5 / Week 23 / Day 3.

Two surfaces:

  - :mod:`budgets` — per-firm monthly_budget_usd + per-session
    session_cost_ceiling_usd. The budget reads from the W20/D3
    cost_ledger; the session ceiling is the per-engagement
    backstop. Coexist by design — the ceiling is the
    per-engagement safety net; the budget is the monthly
    aggregate control.
  - :mod:`rate_limits` — per-firm engagement-creation rate limit
    + per-firm API rate limit for expensive endpoints. Returns
    429 with retry-after; emits a rate_limit.exceeded metric.

Both surfaces are firm-scoped + observability-wired. Budget
threshold crossings notify firm_admins (W18). Rate-limit hits
emit metrics (W20/D2) so an operator can see abuse patterns.

The W23/D3 hard rules baked in:
  - Budget stop is SOFT. New engagements blocked at 100%; in-
    flight engagements finish. A half-finished M&A memo is
    worse than a small overage.
  - A firm must always be able to see the budget status BEFORE
    a stop hits. The dashboard panel + the 80% notification
    are both visibility surfaces.
  - The session ceiling stays. Budget is a higher-level gate;
    the ceiling is the per-engagement backstop.
"""

from .budgets import (
    BudgetStatus,
    DEFAULT_SESSION_CEILING_USD,
    check_engagement_blocked,
    check_session_ceiling,
    compute_budget_status,
    maybe_notify_threshold_crossing,
)
from .rate_limits import (
    RateLimitDecision,
    check_engagement_creation_limit,
    check_expensive_endpoint_limit,
    DEFAULT_ENGAGEMENT_RATE_PER_HOUR,
    DEFAULT_EXPENSIVE_RATE_PER_MINUTE,
)

__all__ = [
    "BudgetStatus",
    "DEFAULT_ENGAGEMENT_RATE_PER_HOUR",
    "DEFAULT_EXPENSIVE_RATE_PER_MINUTE",
    "DEFAULT_SESSION_CEILING_USD",
    "RateLimitDecision",
    "check_engagement_blocked",
    "check_engagement_creation_limit",
    "check_expensive_endpoint_limit",
    "check_session_ceiling",
    "compute_budget_status",
    "maybe_notify_threshold_crossing",
]
