"""Walker that finds MECE-annotated fields in a writer payload — W8/D2.

Two annotations are recognised:

- ``mece_check: True`` on a ``list[str]`` field — compare items in the
  list directly. Example: ``WriterReportBase.key_reasons``.
- ``mece_check_within_parent_list: True`` on a ``str`` field of a
  nested model — when the parent type is contained in a list, compare
  the values of this field across that list's elements. Example:
  ``RiskAssessment.description`` inside
  ``MAndADiligenceReportPayload.risks_and_mitigations``.

The walker returns a list of ``(field_path, items)`` tuples; the
checker turns each tuple into a similarity pass.

Recursion bounds: only walk into fields whose value is a Pydantic
``BaseModel``, a list of ``BaseModel``s, or the top-level payload
itself. ``dict[str, Any]`` / ``list[Any]`` are deliberately skipped
— they're free-form bags that don't carry annotations.
"""

from __future__ import annotations

from typing import Any, Iterator

from pydantic import BaseModel
from pydantic.fields import FieldInfo


def _is_mece_check(info: FieldInfo) -> bool:
    extra = info.json_schema_extra
    return isinstance(extra, dict) and bool(extra.get("mece_check"))


def _is_mece_within_parent(info: FieldInfo) -> bool:
    extra = info.json_schema_extra
    return isinstance(extra, dict) and bool(extra.get("mece_check_within_parent_list"))


def _model_fields(obj: Any) -> dict[str, FieldInfo]:
    return getattr(type(obj), "model_fields", {}) or {}


def _walk(obj: Any, prefix: str) -> Iterator[tuple[str, list[str]]]:
    if not isinstance(obj, BaseModel):
        return

    for name, info in _model_fields(obj).items():
        path = f"{prefix}.{name}" if prefix else name
        value = getattr(obj, name, None)

        # Case 1: mece_check on a list[str] (or list[Any] that contains strings).
        if _is_mece_check(info) and isinstance(value, list):
            items = [str(x).strip() for x in value if isinstance(x, str) and x.strip()]
            if items:
                yield (path, items)
            continue

        # Case 2: list[BaseModel] — descend, AND if any of the inner
        # model's fields are ``mece_check_within_parent_list``, collect
        # values for that inner field across the list.
        if isinstance(value, list) and value and isinstance(value[0], BaseModel):
            inner_cls = type(value[0])
            inner_fields = getattr(inner_cls, "model_fields", {}) or {}
            for inner_name, inner_info in inner_fields.items():
                if _is_mece_within_parent(inner_info):
                    items: list[str] = []
                    for child in value:
                        attr = getattr(child, inner_name, None)
                        if isinstance(attr, str) and attr.strip():
                            items.append(attr.strip())
                    if items:
                        yield (f"{path}[].{inner_name}", items)
            # Also recurse INTO each element to pick up nested mece_check
            # annotations one level deeper (e.g. an inner model that
            # itself contains an annotated list).
            for i, child in enumerate(value):
                yield from _walk(child, f"{path}.{i}")
            continue

        # Case 3: single nested model — recurse.
        if isinstance(value, BaseModel):
            yield from _walk(value, path)


def find_mece_check_targets(payload: BaseModel) -> list[tuple[str, list[str]]]:
    """Walk ``payload``, return ``(field_path, items)`` tuples for every
    MECE-annotated list the checker should examine.

    The returned ``items`` lists are already filtered to non-blank
    strings — but NOT yet filtered by min-word-count (the similarity
    engine handles that with awareness of why an item was skipped).
    """
    return list(_walk(payload, ""))
