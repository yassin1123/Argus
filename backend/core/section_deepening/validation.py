"""Schema-subpath validation for deepened sections — W9/D4.

Pydantic v2 doesn't natively offer "validate a sub-tree of a model
against the type at this dotted path." This utility walks the schema
class's field tree following the same dotted-path grammar as
:mod:`addressing` and runs ``TypeAdapter`` validation against the
resolved annotation. Errors come back as a flat list of human-readable
strings the deepening service can persist as ``failure_reason``.

Why subpath validation matters: when the LLM rewrites
``synergy_estimate.cost_synergies``, it returns a ``list[Synergy]``.
We need to validate that list against ``Synergy``'s constraints
(``basis_citations`` non-empty, etc.) even though we're not
re-instantiating the full ``MAndADiligenceReportPayload``. Without
this check the merge step could splice in a structurally-broken
section that only blows up at the next full payload read.

Surface item resolved: the W9/D4 spec called this out as needing a
small utility. Here it is — ~80 lines, no extra deps, walks
``__pydantic_fields__`` + handles ``list[X]`` indexing.
"""

from __future__ import annotations

import re
from typing import Any, get_args, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError

# Re-use the same path grammar as addressing.
_SEGMENT_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<indices>(?:\[-?\d+\])*)$"
)
_INDEX_RE = re.compile(r"\[(-?\d+)\]")


class SchemaPathError(LookupError):
    """Raised when a section_path doesn't resolve against the schema
    class — e.g. asking for ``synergy_estimate`` on a
    ``GeneralReportPayload`` engagement. Distinct from
    ``ValidationError`` (which means "path resolved but value is bad").
    """


def _resolve_annotation(schema_cls: type[BaseModel], section_path: str) -> Any:
    """Walk ``schema_cls.model_fields`` along ``section_path`` and
    return the Python annotation at the leaf.

    Indices (``[0]``) on a path step "look through" a ``list[X]``
    annotation and return ``X``. Multiple indices peel multiple list
    levels. Dict-valued sub-paths require the parent annotation to be
    a Pydantic ``BaseModel`` subclass so we can descend into its
    ``model_fields``.
    """
    parts = section_path.split(".")
    cursor: Any = schema_cls
    walked: list[str] = []
    for raw in parts:
        m = _SEGMENT_RE.match(raw.strip())
        if not m:
            raise SchemaPathError(
                f"section_path {section_path!r}: malformed segment {raw!r}"
            )
        key = m.group("key")
        indices = [int(x) for x in _INDEX_RE.findall(m.group("indices") or "")]
        walked.append(key + "".join(f"[{i}]" for i in indices))

        # cursor is a BaseModel subclass (initially) or an annotation.
        if isinstance(cursor, type) and issubclass(cursor, BaseModel):
            fields = cursor.model_fields
            if key not in fields:
                raise SchemaPathError(
                    f"section_path {section_path!r}: field {key!r} not on "
                    f"{cursor.__name__}; available: {sorted(fields.keys())[:20]}"
                )
            cursor = fields[key].annotation
        else:
            raise SchemaPathError(
                f"section_path {section_path!r}: cannot descend into {key!r} "
                f"at {'.'.join(walked[:-1]) or '(root)'} — non-model annotation"
            )

        # Peel list[X] for each index applied.
        for _ in indices:
            origin = get_origin(cursor)
            args = get_args(cursor)
            if origin is list and args:
                cursor = args[0]
            else:
                raise SchemaPathError(
                    f"section_path {section_path!r}: list index applied to "
                    f"non-list annotation at {'.'.join(walked)}"
                )
    return cursor


def validate_section_against_schema(
    schema_cls: type[BaseModel],
    section_path: str,
    value: Any,
) -> list[str]:
    """Return a list of human-readable error strings.

    Empty list = the value validates cleanly against the type at
    ``section_path``. Non-empty list = each entry is a
    ``"<field path>: <error message>"`` formatted line ready to
    drop into ``failure_reason``.

    Raises :class:`SchemaPathError` only if the PATH itself doesn't
    resolve. A structural problem in ``value`` is reported via the
    return list, not raised — the deepening service handles both as
    "failed", but separating them gives a sharper failure_reason.
    """
    annotation = _resolve_annotation(schema_cls, section_path)
    try:
        TypeAdapter(annotation).validate_python(value)
        return []
    except ValidationError as e:
        out: list[str] = []
        for err in e.errors():
            loc = ".".join(str(p) for p in err.get("loc") or ())
            msg = err.get("msg") or ""
            out.append(f"{loc or '(root)'}: {msg}")
        return out
