"""Section-deepening service — Phase 2 / Week 9 / Day 1.

Takes ``(session_id, section_path, depth_directive)`` and returns a
deeper rewrite of just that section. The original session payload is
NOT modified in place — the deepened section is persisted as a
separate row in ``section_deepening_runs``. The consultant decides
later whether to merge it back into the parent report (W9/D3 work).

Public surface:

- :func:`deepen_section` — async service entry point.
- :class:`DeepeningRequest` / :class:`DeepeningResult` — shapes the
  API layer trades in.
- :func:`get_section` / :func:`set_section` — dotted-path addressing
  helpers usable independently.
- :class:`SectionNotFoundError` — raised when ``section_path`` doesn't
  exist on the source payload.
"""

from .addressing import SectionNotFoundError, get_section, set_section  # noqa: F401
from .service import deepen_section  # noqa: F401
from .types import DeepeningRequest, DeepeningResult  # noqa: F401
