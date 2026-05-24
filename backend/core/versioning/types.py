"""Payload-version change types — Phase 4 / Week 19 / Day 1.

Five-value enum covering every meaningful change point Argus knows
about today:

  - INITIAL           — first generation (writer pipeline output)
  - SECTION_DEEPENING — W9 accept of a deepened section
  - MANUAL_EDIT       — consultant directly edited the memo
                        (UI is W19/D2's scope; the change_type is
                        defined now so W19/D2's wiring is a small
                        wiring tweak, not a schema change)
  - REVIEW_REVERT     — W15 auto-revert on edit-after-approval
  - RESTORE           — restored a prior version (W19/D2)
"""

from __future__ import annotations

from enum import Enum


class ChangeType(str, Enum):
    INITIAL = "initial"
    SECTION_DEEPENING = "section_deepening"
    MANUAL_EDIT = "manual_edit"
    REVIEW_REVERT = "review_revert"
    RESTORE = "restore"


__all__ = ["ChangeType"]
