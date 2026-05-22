"""Structured review feedback + section pointers — Phase 4 / Week 15 / Day 3.

When a reviewer fires :class:`ReviewAction.REQUEST_CHANGES`, they land
a :class:`ReviewFeedback` payload that has three parts:

  - ``overall_note`` — the reviewer's verdict in prose. Required.
  - ``section_pointers`` — optional list of lightweight pointers at
    specific payload paths the consultant should look at, each with
    its own short note + severity + resolved-or-not flag.
  - ``severity`` — overall classification (minor / major / blocking).
    Used by the resubmit gate.

Section pointers are NOT full threaded comments — that's W16 work.
They are single-note, single-severity, marked resolved or not. The
consultant marks each one resolved as they address it; resubmission
is gated by the unresolved set per the W15/D3 spec:

  - Minor pointers are advisory; resubmit is not blocked.
  - Major + blocking pointers MUST be resolved before resubmit.

Section addressing reuses :func:`section_deepening.addressing.get_section`
so pointers reference the same paths W9 uses (``synergy_estimate``,
``frameworks.porters_five_forces``, etc.). A pointer at a path that
doesn't resolve is rejected at validation time — surfaces as a 400
when the request-changes endpoint normalises the payload.

The persisted shape on ``review_records.feedback`` is the JSON
serialisation of :class:`ReviewFeedback` after the
``section_pointers`` list has been augmented with per-pointer
``resolved`` / ``resolved_at`` / ``resolved_by`` fields. The
W15/D2 service writes the structure as JSONB; the W15/D3
resolve-pointer endpoint mutates the resolved flags in place via
an UPDATE on ``feedback -> 'section_pointers'``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from core.section_deepening.addressing import SectionNotFoundError, get_section


Severity = Literal["minor", "major", "blocking"]
_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"major", "blocking"})


class SectionPointer(BaseModel):
    """One per-section pointer attached to a request_changes feedback
    record. Lightweight: a path + a note + a severity. Each pointer
    can be marked resolved independently.
    """

    section_path: str = Field(..., min_length=1, max_length=200)
    note: str = Field(..., min_length=1, max_length=2000)
    severity: Severity = Field(
        default="major",
        description="minor → advisory; major / blocking gate resubmission.",
    )
    resolved: bool = False
    resolved_at: str | None = None
    resolved_by: str | None = None

    @field_validator("section_path")
    @classmethod
    def _strip_path(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("section_path cannot be blank")
        return v

    model_config = {"extra": "ignore"}


class ReviewFeedback(BaseModel):
    """The structured payload landed on
    ``review_records.feedback`` for ``request_changes`` transitions.
    """

    overall_note: str = Field(..., min_length=1, max_length=4000)
    section_pointers: list[SectionPointer] = Field(default_factory=list)
    severity: Severity = "major"

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Validation against the live payload
# ---------------------------------------------------------------------------


class FeedbackValidationError(ValueError):
    """One or more pointers reference a section_path that doesn't
    resolve against the live writer payload. The message lists every
    bad path so the consultant + reviewer can see exactly what to
    fix.
    """


def validate_against_payload(feedback: ReviewFeedback, payload: Any) -> None:
    """Walk every pointer's ``section_path`` against ``payload`` via
    the W9 ``get_section`` helper. Raises
    :class:`FeedbackValidationError` listing every bad path.

    No-op when ``section_pointers`` is empty — overall_note-only
    feedback is always valid.
    """
    if not feedback.section_pointers:
        return
    bad: list[tuple[str, str]] = []
    for p in feedback.section_pointers:
        try:
            get_section(payload, p.section_path)
        except SectionNotFoundError as e:
            bad.append((p.section_path, str(e)))
    if bad:
        msgs = [f"  - {path!r}: {reason}" for path, reason in bad]
        raise FeedbackValidationError(
            "section pointer(s) reference paths that don't exist in the "
            "current payload:\n" + "\n".join(msgs)
        )


# ---------------------------------------------------------------------------
# Resolution helpers — used by the resolve-pointer endpoint + the resubmit
# gate.
# ---------------------------------------------------------------------------


def is_resubmit_blocked(records_feedback: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Given the list of feedback dicts from every ``request_changes``
    review_record on a session (most recent last), determine whether
    the consultant can resubmit.

    Rule (per W15/D3 spec hard rule):
      - Look only at the LATEST request_changes round (the consultant
        addressed earlier rounds when they resubmitted before).
      - In that latest round, every pointer with severity in
        {major, blocking} must be marked resolved.
      - Minor pointers don't gate.

    Returns ``(blocked, blocking_paths)``. ``blocked`` is True when
    at least one major/blocking pointer is unresolved; the list of
    unresolved paths is surfaceable in the API's 409 response body.
    """
    if not records_feedback:
        return (False, [])
    latest = records_feedback[-1] or {}
    pointers = latest.get("section_pointers") or []
    blocking: list[str] = []
    for p in pointers:
        if not isinstance(p, dict):
            continue
        sev = str(p.get("severity") or "major").lower()
        if sev not in _BLOCKING_SEVERITIES:
            continue
        if not bool(p.get("resolved")):
            blocking.append(str(p.get("section_path") or "(unknown)"))
    return (bool(blocking), blocking)


def mark_pointer_resolved(
    feedback: dict[str, Any],
    section_path: str,
    *,
    resolved_by: str,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Mutate a single pointer's ``resolved`` flag in a feedback
    dict. Returns ``(new_feedback, changed)`` where ``changed`` is
    True when a pointer was actually flipped. A pointer that's
    already resolved returns ``changed=False`` so callers can
    surface "no-op" cleanly.

    Returns a NEW feedback dict — the input is not mutated, so the
    caller can use it for an UPDATE…SET on ``review_records.feedback``
    without worrying about reference aliasing.
    """
    if not isinstance(feedback, dict):
        raise ValueError("feedback must be a dict")
    pointers = feedback.get("section_pointers") or []
    new_pointers: list[dict[str, Any]] = []
    changed = False
    when = (now or datetime.now(tz=timezone.utc)).isoformat()
    for p in pointers:
        if not isinstance(p, dict):
            new_pointers.append(p)
            continue
        if str(p.get("section_path") or "") == section_path:
            if p.get("resolved"):
                new_pointers.append(dict(p))
                continue
            p_new = dict(p)
            p_new["resolved"] = True
            p_new["resolved_at"] = when
            p_new["resolved_by"] = resolved_by
            new_pointers.append(p_new)
            changed = True
        else:
            new_pointers.append(dict(p))
    out = dict(feedback)
    out["section_pointers"] = new_pointers
    return out, changed


__all__ = [
    "FeedbackValidationError",
    "ReviewFeedback",
    "SectionPointer",
    "Severity",
    "is_resubmit_blocked",
    "mark_pointer_resolved",
    "validate_against_payload",
]
