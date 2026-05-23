"""Section work-status enum — Phase 4 / Week 17 / Day 2.

Four states with one canonical forward direction:

  NOT_STARTED  → IN_PROGRESS  → NEEDS_REVIEW  → DONE

Backwards transitions are allowed too (e.g. owner re-opens a
``DONE`` section after a comment surfaces a problem) — the service
doesn't gate by state machine, only by authorisation (owner / lead /
firm admin). The order above is the workflow direction for the
auto-derived "ready to submit" surface in
:mod:`core.collaboration.coverage`.

Distinct from :class:`core.review.state_machine.ReviewState`. Per
W17/D2 hard rule "Don't conflate section status with engagement
review_state": section status is granular work tracking; review
state is the formal engagement-level gate. The two are tested
explicitly together (``test_section_status_distinct_from_engagement_review_state``).
"""

from __future__ import annotations

from enum import Enum


class SectionStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    NEEDS_REVIEW = "needs_review"  # owner thinks it's ready — distinct from engagement review
    DONE = "done"


# Stable iteration order for the coverage map + UI columns.
SECTION_STATUS_ORDER = [
    SectionStatus.NOT_STARTED,
    SectionStatus.IN_PROGRESS,
    SectionStatus.NEEDS_REVIEW,
    SectionStatus.DONE,
]


# ---------------------------------------------------------------------------
# Trackable section enumeration
# ---------------------------------------------------------------------------
#
# Mirrors the frontend's ``DEEPENABLE_PATHS`` in
# ``frontend/lib/api/sectionDeepening.ts``. Reused here for the
# W17/D2 coverage map's "list every trackable section" surface so a
# section that has never been edited still shows up as "unassigned"
# in the lead's view.
#
# We deliberately don't include the recommendation — it's the
# top-down conclusion, not a delegable work item. Same exclusion
# the W9 deepening surface uses.

TRACKABLE_SECTION_PATHS: frozenset[str] = frozenset({
    # Base structured-payload sections.
    "summary",
    "key_reasons",
    "risks",
    "counterarguments",
    "next_steps",
    # M&A mode-specific.
    "target_overview",
    "financial_profile",
    "synergy_estimate",
    "risks_and_mitigations",
    "integration_plan",
    "valuation_range",
    "deal_structure_implications",
    # Frameworks (W8/D3).
    "frameworks.two_by_two",
    "frameworks.porters_five_forces",
    "frameworks.value_chain",
})


def is_trackable(section_path: str) -> bool:
    """True if ``section_path`` is one a work-item owner can be
    assigned to. The coverage map filters the payload's actual
    keys against this set so mode-specific sections that don't
    exist for a given engagement aren't surfaced as ghost
    "unassigned" rows."""
    return section_path in TRACKABLE_SECTION_PATHS


__all__ = [
    "SECTION_STATUS_ORDER",
    "SectionStatus",
    "TRACKABLE_SECTION_PATHS",
    "is_trackable",
]
