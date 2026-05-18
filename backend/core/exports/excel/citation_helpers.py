"""Citation helpers for the Excel exporter — W12/D1.

Excel surfaces "where did this number come from" via cell comments:
hover the cell, see the source breadcrumb. We attach a Comment to
the cell carrying a single ``ClaimCitation`` so the partner can
defend any number.

Public surface:
  - :func:`add_citation_comment(cell, claim_id, citation_text, author)`
    attaches a Comment to ``cell`` with the source breadcrumb.
  - :func:`breadcrumb_for_citation(c)` formats a ``ClaimCitation``
    consistently with the deck + PDF citation rendering.
"""

from __future__ import annotations

from typing import Any

from openpyxl.comments import Comment


_COMMENT_WIDTH = 300
_COMMENT_HEIGHT = 80
_DEFAULT_AUTHOR = "Argus"


def breadcrumb_for_citation(c: Any) -> str:
    """Human-readable source breadcrumb for a ClaimCitation. Mirrors
    the deck DeckBuilder's breadcrumb format so the same chip number
    reads the same across PDF, PPTX, and XLSX."""
    source_type = (getattr(c, "source_type", "") or "").strip()
    title = (getattr(c, "source_title", "") or "").strip()
    cid = (getattr(c, "claim_id", "") or "").strip()
    parts: list[str] = []
    if source_type:
        parts.append(source_type.replace("_", " "))
    if title:
        parts.append(title)
    if cid:
        parts.append(cid)
    return " · ".join(parts) or cid


def add_citation_comment(
    cell: Any,
    *,
    claim_id: str,
    citation_text: str,
    author: str = _DEFAULT_AUTHOR,
) -> None:
    """Attach an Excel Comment to ``cell`` with the source breadcrumb.

    The comment text leads with the chip-style ``claim_id`` so a
    consultant pasting the cell into a tracker / email gets the
    identifier; the breadcrumb follows.
    """
    if not claim_id:
        return
    text = f"[{claim_id}] {citation_text}".strip()
    comment = Comment(text, author)
    comment.width = _COMMENT_WIDTH
    comment.height = _COMMENT_HEIGHT
    cell.comment = comment


__all__ = ["add_citation_comment", "breadcrumb_for_citation"]
