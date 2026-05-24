"""Section-level diff helper — Phase 4 / Week 19 / Day 1.

Walks two payloads and returns the list of top-level + nested
section_paths that differ. Used by :func:`create_version` to
populate ``changed_section_paths`` so the history reader can
surface "this version changed synergy_estimate and risks[0]"
without re-diffing on every render.

We compare JSON-serialised shapes (sorted keys) so a key-reorder
in a dict doesn't count as a change. Comparison is shallow per
top-level key + one level into ``frameworks.*`` (the only nested
namespace W9's deepening surface touches today). Anything beyond
that depth shows up as a top-level change — the right granularity
for an inbox-style "what changed" surface.
"""

from __future__ import annotations

import json
from typing import Any


def _canonical(value: Any) -> str:
    """Stable JSON encoding for equality comparison. Sorts dict
    keys so a re-order doesn't read as a change; default=str for
    Decimal / datetime / UUID so the encoder doesn't fall over on
    serialisation-edge values."""
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return repr(value)


def changed_sections(
    old_payload: dict[str, Any] | None,
    new_payload: dict[str, Any] | None,
) -> list[str]:
    """Return section_paths that differ between two payloads.

    ``None``-vs-dict on either side is treated as a full reset: the
    diff returns every top-level key in the dict that is non-None.
    Adding a new key counts as a change; removing one does too.
    """
    old = old_payload or {}
    new = new_payload or {}
    keys = sorted(set(old.keys()) | set(new.keys()))
    out: list[str] = []
    for k in keys:
        if k in ("frameworks",):
            # One level deeper: detect which framework changed.
            old_f = old.get(k) if isinstance(old.get(k), dict) else {}
            new_f = new.get(k) if isinstance(new.get(k), dict) else {}
            sub_keys = sorted(set(old_f.keys()) | set(new_f.keys()))
            for sk in sub_keys:
                if _canonical(old_f.get(sk)) != _canonical(new_f.get(sk)):
                    out.append(f"{k}.{sk}")
            continue
        if _canonical(old.get(k)) != _canonical(new.get(k)):
            out.append(k)
    return out


__all__ = ["changed_sections"]
