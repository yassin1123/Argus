"""Dotted-path addressing into writer payloads — W9/D1.

Schema-agnostic. The current ``WriterReportBase`` is flat
(``recommendation``, ``summary``, ``key_reasons``, ...) and the M&A
extension nests deep (``target_overview.segments[2]``,
``synergy_estimate.cost_synergies``). One walker handles both —
plus future schemas — without per-schema special cases.

Path grammar:

    PATH := SEGMENT ( "." SEGMENT )*
    SEGMENT := KEY ( "[" INDEX "]" )*
    KEY := /[A-Za-z_][A-Za-z0-9_]*/
    INDEX := /-?[0-9]+/

Examples:
    ``recommendation``
    ``synergy_estimate.cost_synergies``
    ``target_overview.segments[2]``
    ``risks_and_mitigations[0].description``
    ``frameworks.two_by_two.items[3].rationale``

:func:`set_section` returns a NEW payload (shallow-copy along the
path) with the target value replaced — the original is not mutated,
preserving the hard rule "don't modify the original session payload
in-place."

Spec-vs-current-schema note: the spec uses
``executive_summary`` as a sample path, but the actual base schema
is flat (no ``executive_summary`` wrapper — that's the same
flat-vs-nested mismatch surfaced in W8/D1 + W8/D2). The addressing
walker doesn't care — it walks whatever it's given. A request for
``executive_summary`` on a flat-schema payload will surface as a
:class:`SectionNotFoundError` with a clear message, which is
correct behavior.
"""

from __future__ import annotations

import re
from typing import Any

_SEGMENT_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<indices>(?:\[-?\d+\])*)$"
)
_INDEX_RE = re.compile(r"\[(-?\d+)\]")


class SectionNotFoundError(LookupError):
    """Raised when a dotted path doesn't resolve against the payload.

    The message names the original full path AND the segment that
    failed so consultants and tooling see exactly where the address
    broke.
    """


def _parse_path(path: str) -> list[tuple[str, list[int]]]:
    """Split ``a.b[0][1].c`` into ``[("a", []), ("b", [0, 1]), ("c", [])]``.

    Each segment is ``(key, list-of-indices)``. Indices are applied
    in left-to-right order after the key lookup.
    """
    parts = path.split(".")
    out: list[tuple[str, list[int]]] = []
    for raw in parts:
        m = _SEGMENT_RE.match(raw.strip())
        if not m:
            raise SectionNotFoundError(
                f"section_path {path!r}: malformed segment {raw!r} "
                f"(expected ``key`` or ``key[i]`` or ``key[i][j]``)"
            )
        key = m.group("key")
        indices = [int(x) for x in _INDEX_RE.findall(m.group("indices") or "")]
        out.append((key, indices))
    return out


def get_section(payload: Any, path: str) -> Any:
    """Walk ``payload`` along the dotted ``path`` and return the value.

    Raises :class:`SectionNotFoundError` on:
      - missing dict key
      - list index out of range
      - applying ``[i]`` to a non-list
      - malformed path syntax
    """
    if not isinstance(path, str) or not path.strip():
        raise SectionNotFoundError("section_path must be a non-empty string")
    segments = _parse_path(path)
    cursor: Any = payload
    walked: list[str] = []
    for key, indices in segments:
        walked.append(key + "".join(f"[{i}]" for i in indices))
        if not isinstance(cursor, dict):
            raise SectionNotFoundError(
                f"section_path {path!r}: at {'.'.join(walked[:-1]) or '(root)'}, "
                f"cannot apply key {key!r} to {type(cursor).__name__}"
            )
        if key not in cursor:
            raise SectionNotFoundError(
                f"section_path {path!r}: key {key!r} not found at "
                f"{'.'.join(walked[:-1]) or '(root)'}; available: "
                f"{sorted(cursor.keys())[:20]}"
            )
        cursor = cursor[key]
        for idx in indices:
            if not isinstance(cursor, list):
                raise SectionNotFoundError(
                    f"section_path {path!r}: at {'.'.join(walked)}, "
                    f"cannot apply index [{idx}] to {type(cursor).__name__}"
                )
            try:
                cursor = cursor[idx]
            except IndexError as e:
                raise SectionNotFoundError(
                    f"section_path {path!r}: index [{idx}] out of range "
                    f"at {'.'.join(walked)} (len={len(cursor)})"
                ) from e
    return cursor


def _shallow_copy_container(value: Any) -> Any:
    """One-level copy. Dict → new dict, list → new list, anything
    else returned as-is. Used by :func:`set_section` so we don't
    mutate the input payload."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


def set_section(payload: Any, path: str, value: Any) -> Any:
    """Return a new payload with the value at ``path`` replaced.

    The original payload is not modified. Containers along the path
    are shallow-copied; siblings of the replaced node are
    referenced (not deep-copied) so memory + cost stay bounded.

    Raises :class:`SectionNotFoundError` on the same conditions as
    :func:`get_section`, plus "trying to replace at a path that
    doesn't exist."
    """
    if not isinstance(path, str) or not path.strip():
        raise SectionNotFoundError("section_path must be a non-empty string")
    segments = _parse_path(path)

    # Build the chain of references we'll need to copy on the way back.
    # First, walk the path on the read side and record each container
    # node we touch (so we know it exists and we have a handle to it).
    chain: list[tuple[Any, str, list[int]]] = []  # (container, key, indices)
    cursor: Any = payload
    walked: list[str] = []
    for key, indices in segments:
        walked.append(key + "".join(f"[{i}]" for i in indices))
        if not isinstance(cursor, dict):
            raise SectionNotFoundError(
                f"section_path {path!r}: at {'.'.join(walked[:-1]) or '(root)'}, "
                f"cannot apply key {key!r} to {type(cursor).__name__}"
            )
        if key not in cursor:
            raise SectionNotFoundError(
                f"section_path {path!r}: key {key!r} not found at "
                f"{'.'.join(walked[:-1]) or '(root)'}; available: "
                f"{sorted(cursor.keys())[:20]}"
            )
        chain.append((cursor, key, indices))
        cursor = cursor[key]
        for idx in indices:
            if not isinstance(cursor, list):
                raise SectionNotFoundError(
                    f"section_path {path!r}: at {'.'.join(walked)}, "
                    f"cannot apply index [{idx}] to {type(cursor).__name__}"
                )
            try:
                cursor = cursor[idx]
            except IndexError as e:
                raise SectionNotFoundError(
                    f"section_path {path!r}: index [{idx}] out of range "
                    f"at {'.'.join(walked)} (len={len(cursor)})"
                ) from e

    # Walk back from the leaf, copy each container, and rewire the
    # parent pointer to the new copy.
    new_leaf = value
    for container, key, indices in reversed(chain):
        # Copy the dict that holds ``key``. We also need to copy any
        # list containers between key and the leaf (for indices).
        new_container = dict(container)
        if not indices:
            new_container[key] = new_leaf
        else:
            # Walk into the list chain, copying each list we traverse,
            # and reseat the leaf at the deepest index.
            list_chain: list[list[Any]] = []
            sub: Any = container[key]
            for idx in indices:
                copied_list = list(sub)
                list_chain.append(copied_list)
                sub = sub[idx]
            # Now reseat from the deepest index back up.
            list_chain[-1][indices[-1]] = new_leaf
            for j in range(len(list_chain) - 2, -1, -1):
                list_chain[j][indices[j]] = list_chain[j + 1]
            new_container[key] = list_chain[0]
        new_leaf = new_container

    return new_leaf
