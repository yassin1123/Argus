"""Orphan detection for text_range comments — Phase 4 / Week 16 / Day 1.

A text_range comment stores the quoted substring at create-time.
When the underlying section is later deepened or rewritten (W9
deepening accept, W15/D2 auto-revert + edit, future memo edits)
the quoted text may no longer appear in the section. We don't
re-anchor — that's pixel-perfect text matching territory we
explicitly punted on per the W16/D1 hard rule. Instead the
comment is flagged ``orphaned=True`` so the workspace UI can
render it with a "the text this refers to has changed" badge,
and the consultant decides whether to resolve, edit, or delete it.

Section + claim anchors don't orphan via this path — they're keyed
on stable identifiers, and the workspace UI surfaces them as
"section removed" only when the whole section/claim disappears
from the payload. That check lives on the read endpoint when it
hydrates a comment thread; this module is text_range only.

Public surface: :func:`is_text_range_orphaned(comment, payload)`.

The match is intentionally loose: we strip whitespace + collapse
internal whitespace + casefold both sides before checking
``quoted_text in section_text``. That tolerates the cosmetic
diffs the W9 deepening introduces (markdown reflow, sentence
re-ordering within a paragraph) without flagging false positives
on benign edits.
"""

from __future__ import annotations

import re
from typing import Any

from core.section_deepening.addressing import SectionNotFoundError, get_section

from .anchors import AnchorType


_WS_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return _WS_RE.sub(" ", text).strip().casefold()


def _stringify(value: Any) -> str:
    """Reduce an arbitrary payload-section value to its text content.

    Dict → join all string leaves; list → join recursively. Used so a
    quote that originally lived in ``synergy_estimate.revenue_synergies[0].rationale``
    still resolves when we pass ``synergy_estimate`` as the section
    being checked (the orphan check is over the whole subtree,
    keeping the quote-survives-the-section question honest).
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_stringify(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_stringify(v) for v in value)
    return ""


def is_text_range_orphaned(comment: dict[str, Any], payload: Any) -> bool:
    """True when:

      - The comment's anchor_type is ``text_range`` AND
      - The section_path no longer resolves, OR
      - The (normalised) quoted_text no longer appears in the
        section's text content.

    For any other anchor_type, returns False — orphan detection is
    text_range-specific. The caller (workspace read endpoint, W16/D2)
    runs this per comment when hydrating a thread.
    """
    anchor_type = str(comment.get("anchor_type") or "")
    if anchor_type != AnchorType.TEXT_RANGE.value:
        return False
    anchor_ref = comment.get("anchor_ref") or {}
    if not isinstance(anchor_ref, dict):
        return True  # malformed ref counts as orphaned
    section_path = str(anchor_ref.get("section_path") or "").strip()
    quoted_text = str(anchor_ref.get("quoted_text") or "")
    if not section_path or not quoted_text:
        return True

    try:
        section_value = get_section(payload, section_path)
    except SectionNotFoundError:
        return True

    section_text = _stringify(section_value)
    needle = _normalise(quoted_text)
    haystack = _normalise(section_text)
    if not needle:
        return True
    return needle not in haystack


__all__ = ["is_text_range_orphaned"]
