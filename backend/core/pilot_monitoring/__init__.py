"""Live-pilot monitoring + operator alerting — Phase 5 / Week 25 / Day 2.

The pilot is live. This package makes the operator (Yassin) find out
about a problem in minutes, not at the weekly check-in:

  - :func:`live_pilot_view` — the active-pilot watch view: what's running,
    what's failing, live cost burn, alerts, feedback as it arrives.
  - :func:`evaluate_pilot_alerts` — the conditions that matter during a
    live pilot (engagement failure, error-rate spike, budget 80/100,
    anomalous verification distribution).
  - :func:`dispatch_pilot_alert` — deliver an alert to the operator
    (W18 notification to system-admins + optional ops webhook).
  - :func:`detect_verification_anomaly` — flag when the verification mix
    suddenly skews (e.g. everything coming back insufficient — a signal
    something's wrong with retrieval or the firm's content).
"""

from .alerts import (
    PilotAlert,
    detect_verification_anomaly,
    dispatch_pilot_alert,
    evaluate_pilot_alerts,
)
from .live import live_pilot_view

__all__ = [
    "PilotAlert",
    "detect_verification_anomaly",
    "dispatch_pilot_alert",
    "evaluate_pilot_alerts",
    "live_pilot_view",
]
