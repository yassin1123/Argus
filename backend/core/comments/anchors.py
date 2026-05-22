"""Comment anchoring — Phase 4 / Week 16 / Day 1.

Five anchor types. Three stable (section / claim / artifact), one
loose (text_range — best-effort + orphan-flagged on drift), one
trivial (engagement — no target).

  - ``engagement`` — generic comment on the engagement as a whole.
    ``anchor_ref`` is ignored / empty.
  - ``section`` — comment attached to a writer-payload section
    identified by a W9 dotted path. ``anchor_ref = {section_path: str}``.
    Validation uses :func:`core.section_deepening.addressing.get_section`
    so the same paths the W9 deepening + W15/D3 review-feedback
    use also work here.
  - ``claim`` — comment attached to a specific claim_id surfaced by
    the W7 writer payload's ``claim_citations`` / ``key_claims``
    registry. ``anchor_ref = {claim_id: str}``.
  - ``text_range`` — comment attached to a quoted substring within a
    section. Best-effort: stores the quote so the W16/D1
    :mod:`orphan` detector can flag the comment when the underlying
    text has been deepened away. ``anchor_ref = {section_path: str,
    start: int, end: int, quoted_text: str}``. The offsets are
    advisory; validation only requires section_path resolves and
    quoted_text is non-empty.
  - ``artifact`` — comment attached to a generated artifact
    (``export_artifacts`` row). ``anchor_ref = {artifact_id: str}``.
    Validation requires the artifact belongs to the session.

The validator returns :class:`AnchorValidationResult(ok, reason)` so
callers can surface "anchor invalid" as a clean 400 without
inventing a parallel exception hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AnchorType(str, Enum):
    """The five comment-anchor kinds. ``str`` mixin so the value
    serialises directly into the ``comments.anchor_type`` TEXT
    column."""

    ENGAGEMENT = "engagement"
    SECTION = "section"
    CLAIM = "claim"
    TEXT_RANGE = "text_range"
    ARTIFACT = "artifact"


@dataclass(frozen=True)
class AnchorValidationResult:
    """Result of :func:`validate_anchor`. ``reason`` is empty when
    ``ok`` is True; surfaceable as a 400 body when False."""

    ok: bool
    reason: str = ""


def _coerce_anchor_type(anchor_type: AnchorType | str) -> AnchorType:
    if isinstance(anchor_type, AnchorType):
        return anchor_type
    try:
        return AnchorType(str(anchor_type))
    except ValueError as e:
        raise ValueError(
            f"unknown anchor_type {anchor_type!r}. "
            f"Allowed: {[a.value for a in AnchorType]}"
        ) from e


def _str_field(anchor_ref: Any, key: str) -> str:
    if not isinstance(anchor_ref, dict):
        return ""
    v = anchor_ref.get(key)
    if isinstance(v, str):
        return v.strip()
    return ""


def validate_anchor(
    anchor_type: AnchorType | str,
    anchor_ref: dict[str, Any] | None,
    *,
    payload: Any | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> AnchorValidationResult:
    """Validate the ``anchor_ref`` against the live engagement state.

    ``payload`` should be the writer payload (``reports`` row +
    ``consulting_payload`` merged); ``artifacts`` is the list of
    ``export_artifacts`` rows belonging to the session.

    Per W16/D1 hard rule: section + claim anchors validate
    strictly (anchor must resolve at create-time); ``text_range``
    is permissive (only the section_path is required to resolve —
    quoted_text is stored for the orphan detector to use later);
    ``engagement`` is always valid.
    """
    try:
        a = _coerce_anchor_type(anchor_type)
    except ValueError as e:
        return AnchorValidationResult(False, str(e))
    ref: dict[str, Any] = anchor_ref if isinstance(anchor_ref, dict) else {}

    if a == AnchorType.ENGAGEMENT:
        # Trivial — no target.
        return AnchorValidationResult(True)

    if a == AnchorType.SECTION:
        section_path = _str_field(ref, "section_path")
        if not section_path:
            return AnchorValidationResult(
                False, "section anchor requires anchor_ref.section_path",
            )
        if payload is None:
            return AnchorValidationResult(
                False, "section anchor needs a payload to validate against",
            )
        from core.section_deepening.addressing import (  # noqa: WPS433
            SectionNotFoundError,
            get_section,
        )
        try:
            get_section(payload, section_path)
        except SectionNotFoundError as e:
            return AnchorValidationResult(False, str(e))
        return AnchorValidationResult(True)

    if a == AnchorType.CLAIM:
        claim_id = _str_field(ref, "claim_id")
        if not claim_id:
            return AnchorValidationResult(
                False, "claim anchor requires anchor_ref.claim_id",
            )
        if payload is None:
            return AnchorValidationResult(
                False, "claim anchor needs a payload to validate against",
            )
        if not _claim_id_in_payload(payload, claim_id):
            return AnchorValidationResult(
                False, f"claim_id {claim_id!r} not found in this engagement's claim registry",
            )
        return AnchorValidationResult(True)

    if a == AnchorType.TEXT_RANGE:
        section_path = _str_field(ref, "section_path")
        quoted_text = _str_field(ref, "quoted_text")
        if not section_path:
            return AnchorValidationResult(
                False, "text_range anchor requires anchor_ref.section_path",
            )
        if not quoted_text:
            return AnchorValidationResult(
                False,
                "text_range anchor requires anchor_ref.quoted_text "
                "(stored for orphan detection; no defaultable fallback)",
            )
        if payload is None:
            return AnchorValidationResult(
                False, "text_range anchor needs a payload to validate the section_path",
            )
        from core.section_deepening.addressing import (  # noqa: WPS433
            SectionNotFoundError,
            get_section,
        )
        try:
            get_section(payload, section_path)
        except SectionNotFoundError as e:
            return AnchorValidationResult(False, str(e))
        # offsets (start/end) are advisory — don't require them to
        # be coherent. Storing whatever was supplied is fine; the
        # orphan detector only needs ``quoted_text``.
        return AnchorValidationResult(True)

    if a == AnchorType.ARTIFACT:
        artifact_id = _str_field(ref, "artifact_id")
        if not artifact_id:
            return AnchorValidationResult(
                False, "artifact anchor requires anchor_ref.artifact_id",
            )
        if artifacts is None:
            return AnchorValidationResult(
                False, "artifact anchor needs the session's artifact list to validate",
            )
        ids = {str(a.get("id") or a.get("artifact_id") or "") for a in artifacts}
        if artifact_id not in ids:
            return AnchorValidationResult(
                False,
                f"artifact_id {artifact_id!r} not found on this session. "
                "Comment must reference an artifact that belongs to the engagement.",
            )
        return AnchorValidationResult(True)

    return AnchorValidationResult(False, f"unhandled anchor type {a.value!r}")


def _claim_id_in_payload(payload: Any, claim_id: str) -> bool:
    """Walk the payload looking for a matching claim_id. The W7+
    writer schemas surface claim_ids in several places — the
    canonical registry is ``key_claims[*].claim_id`` (or
    ``claim_citations[*].claim_id``), but for safety we also accept
    ``recommendation_claim_ids[]`` + any per-row ``source_citation``
    string equal to ``claim_id``."""
    if not isinstance(payload, dict):
        return False

    # Direct registries first.
    for key in ("key_claims", "claim_citations", "claims"):
        rows = payload.get(key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and str(row.get("claim_id") or "") == claim_id:
                    return True

    # Flat-list registries.
    flat = payload.get("recommendation_claim_ids")
    if isinstance(flat, list) and claim_id in (str(x) for x in flat):
        return True

    # Walk source_citation fields scattered through the payload (a
    # cheap recursive scan — payloads are bounded in size).
    def _walk(node: Any) -> bool:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "source_citation" and isinstance(v, str) and v.strip() == claim_id:
                    return True
                if k == "basis_citations" and isinstance(v, list) and claim_id in (str(x) for x in v):
                    return True
                if _walk(v):
                    return True
        elif isinstance(node, list):
            for item in node:
                if _walk(item):
                    return True
        return False

    return _walk(payload)


__all__ = ["AnchorType", "AnchorValidationResult", "validate_anchor"]
