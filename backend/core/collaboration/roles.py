"""Engagement role enum — Phase 4 / Week 17 / Day 1.

Four roles, one always-required (lead), one cap-at-one (lead),
two allow-many (contributor, observer), one aligned-with-W15
(reviewer):

  - LEAD        — owns the engagement, can assign / remove others,
                  change roles. Exactly one per engagement (W17/D1
                  invariant; the service enforces it).
  - CONTRIBUTOR — works on sections; read + write capability
                  (mapped through :mod:`auth.permissions`).
  - REVIEWER    — the designated reviewer for the W15 workflow.
                  Assigning role=reviewer wires
                  ``sessions.review_assigned_to`` to this user
                  whenever the alignment isn't already in conflict.
  - OBSERVER    — read-only visibility.

Distinct from firm role (W5): a firm_member can be an engagement
lead; a firm_admin might be only an observer on a specific
engagement. Two distinct layers, never conflated.
"""

from __future__ import annotations

from enum import Enum


class EngagementRole(str, Enum):
    LEAD = "lead"
    CONTRIBUTOR = "contributor"
    REVIEWER = "reviewer"
    OBSERVER = "observer"


# Capability map — mirrors the legacy auth.permissions mapping
# extended with the W17 vocabulary. Surfaced here so the
# collaboration layer is the single source of truth for what a role
# can do; auth.permissions imports from here.
ROLE_CAPABILITIES: dict[EngagementRole, set[str]] = {
    EngagementRole.LEAD:        {"read", "write", "admin"},
    EngagementRole.CONTRIBUTOR: {"read", "write"},
    # Reviewer needs read + write so they can leave review-feedback
    # notes via the W15 surface. The W15 authorisation layer further
    # restricts the actual review actions (approve / request_changes
    # require admin OR explicit assignment).
    EngagementRole.REVIEWER:    {"read", "write"},
    EngagementRole.OBSERVER:    {"read"},
}


def role_has_capability(role: str | EngagementRole, capability: str) -> bool:
    """Return True when ``role`` includes ``capability``.

    Tolerates the pre-W17 legacy values ``member`` / ``viewer`` so
    callers that haven't migrated yet still get sensible answers.
    The migration 040 already rewrote stored rows; this is a safety
    net for in-flight code that may still be reading older snapshots.
    """
    if isinstance(role, EngagementRole):
        return capability in ROLE_CAPABILITIES[role]
    legacy_alias = {"member": EngagementRole.CONTRIBUTOR,
                    "viewer": EngagementRole.OBSERVER}
    try:
        enum = EngagementRole(role)
    except ValueError:
        enum = legacy_alias.get(role)
        if enum is None:
            return False
    return capability in ROLE_CAPABILITIES[enum]


__all__ = ["EngagementRole", "ROLE_CAPABILITIES", "role_has_capability"]
