"""Comments module — Phase 4 / Week 16.

Public surface:

  - :class:`AnchorType` / :func:`validate_anchor` /
    :class:`AnchorValidationResult` — anchor-shape validation (W16/D1).
  - :func:`is_text_range_orphaned` — text_range drift flag (W16/D1).
  - :class:`CommentResult` + CRUD + resolve helpers from
    :mod:`service` — W16/D1 CRUD layer.
  - :class:`CommentThread` + :func:`get_threads_for_session` /
    :func:`get_threads_for_anchor` /
    :func:`count_threads_by_anchor` /
    :func:`count_unresolved_for_session` — W16/D2 thread assembly.
  - :func:`parse_mentions` / :func:`slug_for_user` /
    :func:`emit_mention_events` — W16/D2 mention parsing.
"""

from .anchors import AnchorType, AnchorValidationResult, validate_anchor
from .mentions import (
    build_slug_index,
    emit_mention_events,
    parse_mentions,
    slug_for_user,
)
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
from .threads import (
    CommentThread,
    count_threads_by_anchor,
    count_unresolved_for_session,
    get_threads_for_anchor,
    get_threads_for_session,
)

__all__ = [
    "AnchorType",
    "AnchorValidationResult",
    "CommentResult",
    "CommentThread",
    "build_slug_index",
    "count_threads_by_anchor",
    "count_unresolved_for_session",
    "create_comment",
    "delete_comment",
    "edit_comment",
    "emit_mention_events",
    "get_threads_for_anchor",
    "get_threads_for_session",
    "is_text_range_orphaned",
    "parse_mentions",
    "reply_to_comment",
    "resolve_thread",
    "slug_for_user",
    "unresolve_thread",
    "validate_anchor",
]
