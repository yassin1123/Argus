"""Pilot feedback instrumentation — Phase 5 / Week 24 / Day 3.

Lightweight, firm-scoped feedback surfaces so the pilot produces
learning, not just a deploy:

  - per-claim verification feedback (:func:`record_claim_feedback`)
  - per-artifact quality rating (:func:`record_artifact_rating`)
  - edit telemetry on approval (:func:`compute_and_record_edit_telemetry`)
  - weekly structured check-ins (:func:`submit_checkin`)
  - the operator's pilot-health aggregate (:func:`pilot_health_panel`)

Every read is firm-scoped (W23 rule). The edit telemetry stores only
the FRACTION of edits + counts, never the prose (W20 privacy line).
"""

from .aggregates import (
    artifact_quality_signal,
    claim_feedback_agreement,
    edit_rate_by_section,
    edit_rate_summary,
)
from .edit_telemetry import (
    EditTelemetry,
    compute_and_record_edit_telemetry,
    compute_edit_telemetry,
)
from .feedback import (
    CHECKIN_QUESTIONS,
    CLAIM_ASSESSMENTS,
    artifact_rating_summary,
    claim_feedback_distribution,
    pilot_health_panel,
    record_artifact_rating,
    record_claim_feedback,
    submit_checkin,
)

__all__ = [
    "CHECKIN_QUESTIONS",
    "CLAIM_ASSESSMENTS",
    "EditTelemetry",
    "artifact_quality_signal",
    "artifact_rating_summary",
    "claim_feedback_agreement",
    "claim_feedback_distribution",
    "compute_and_record_edit_telemetry",
    "compute_edit_telemetry",
    "edit_rate_by_section",
    "edit_rate_summary",
    "pilot_health_panel",
    "record_artifact_rating",
    "record_claim_feedback",
    "submit_checkin",
]
