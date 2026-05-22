"""Comments module — Phase 4 / Week 16.

Public surface:

  - :class:`AnchorType` / :func:`validate_anchor` /
    :class:`AnchorValidationResult` — anchor-shape validation (W16/D1).
  - :func:`is_text_range_orphaned` — text_range drift flag (W16/D1).
  - :class:`CommentResult` + CRUD + resolve helpers from
    :mod:`service` — W16/D1 CRUD layer.
"""

from .anchors import AnchorType, AnchorValidationResult, validate_anchor
from .orphan import is_text_range_orphaned
from .service import (
    CommentResult,
    create_comment,
    delete_comment,
    edit_comment,
    reply_to_comment,
    resolve_thread,
    unresolve_thread,
)

__all__ = [
    "AnchorType",
    "AnchorValidationResult",
    "CommentResult",
    "create_comment",
    "delete_comment",
    "edit_comment",
    "is_text_range_orphaned",
    "reply_to_comment",
    "resolve_thread",
    "unresolve_thread",
    "validate_anchor",
]
