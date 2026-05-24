"""Section-level diff helper — Phase 4 / Week 19 / Day 1+D2.

Walks two payloads and returns the list of top-level + nested
section_paths that differ. Used by :func:`create_version` to
populate ``changed_section_paths`` so the history reader can
surface "this version changed synergy_estimate and risks[0]"
without re-diffing on every render.

W19/D2 adds :func:`diff_versions` — a higher-level helper that
loads two version snapshots and returns:

  - per-section change (added | removed | modified)
  - word-level content delta for each modified section's text
    content (using stdlib :class:`difflib.SequenceMatcher`,
    matching the segment shape the frontend W9 ``DiffPanel``
    renders so W19/D3 can reuse the same component)
  - claim_changes — claim_ids added / removed between versions
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID


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


# ---------------------------------------------------------------------------
# W19/D2 — version-level diff
# ---------------------------------------------------------------------------


ChangeKind = Literal["added", "removed", "modified"]


@dataclass
class DiffSegment:
    """One contiguous run of words tagged with how it changed.
    Matches the frontend ``DiffSeg`` shape (text + status) so the
    W19/D3 diff component is a straight render of these rows."""

    text: str
    status: Literal["same", "added", "removed"]


@dataclass
class SectionChange:
    """One row in :class:`VersionDiff.section_changes`."""

    section_path: str
    change: ChangeKind
    # For 'modified' sections we surface a flat text representation +
    # word-level segments so the UI can render the delta inline.
    # 'added' rows carry only the new text; 'removed' rows only the old.
    old_text: str = ""
    new_text: str = ""
    word_segments: list[DiffSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_path": self.section_path,
            "change": self.change,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "word_segments": [
                {"text": s.text, "status": s.status} for s in self.word_segments
            ],
        }


@dataclass
class VersionDiff:
    """Top-level diff response shape."""

    session_id: str
    version_a: int
    version_b: int
    section_changes: list[SectionChange] = field(default_factory=list)
    claim_changes: dict[str, list[str]] = field(
        default_factory=lambda: {"added": [], "removed": []}
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "version_a": self.version_a,
            "version_b": self.version_b,
            "section_changes": [s.to_dict() for s in self.section_changes],
            "claim_changes": self.claim_changes,
        }


_WORD_RE = re.compile(r"\S+|\s+")


def _stringify(value: Any) -> str:
    """Flatten a section value into a single text blob for word-level
    diffing. Mirrors :func:`core.comments.orphan._stringify` so the
    "what readable text changed" view is consistent across the
    platform."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(_stringify(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_stringify(v) for v in value)
    if value is None:
        return ""
    return str(value)


def _word_diff(old_text: str, new_text: str) -> list[DiffSegment]:
    """Word-level diff via :class:`difflib.SequenceMatcher`. Returns
    the list of segments the frontend W9 ``DiffPanel`` consumes
    (text + same|added|removed). Splits on whitespace runs so the
    rendered diff preserves word boundaries cleanly."""
    if old_text == new_text:
        return [DiffSegment(text=old_text, status="same")] if old_text else []
    a_words = _WORD_RE.findall(old_text)
    b_words = _WORD_RE.findall(new_text)
    matcher = difflib.SequenceMatcher(a=a_words, b=b_words, autojunk=False)
    out: list[DiffSegment] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            text = "".join(a_words[i1:i2])
            if text:
                out.append(DiffSegment(text=text, status="same"))
        elif tag == "delete":
            text = "".join(a_words[i1:i2])
            if text:
                out.append(DiffSegment(text=text, status="removed"))
        elif tag == "insert":
            text = "".join(b_words[j1:j2])
            if text:
                out.append(DiffSegment(text=text, status="added"))
        elif tag == "replace":
            del_text = "".join(a_words[i1:i2])
            ins_text = "".join(b_words[j1:j2])
            if del_text:
                out.append(DiffSegment(text=del_text, status="removed"))
            if ins_text:
                out.append(DiffSegment(text=ins_text, status="added"))
    return out


def _extract_claim_ids(payload: dict[str, Any]) -> set[str]:
    """Pull the claim_id surface for the claim_changes diff. We
    walk the standard claim-carrying fields: key_reasons +
    recommendation_claim_ids + executive_insights +
    key_risks_structured. Returns a set of stringified IDs (cheap
    dedup + symmetric_difference at the call site)."""
    ids: set[str] = set()
    for entry in (payload.get("key_reasons") or []):
        if isinstance(entry, dict):
            cid = entry.get("claim_id")
            if isinstance(cid, str) and cid:
                ids.add(cid)
    for cid in (payload.get("recommendation_claim_ids") or []):
        if isinstance(cid, str) and cid:
            ids.add(cid)
    for collection in ("executive_insights", "key_risks_structured"):
        for entry in (payload.get(collection) or []):
            if isinstance(entry, dict):
                for cid in (entry.get("claim_ids") or []):
                    if isinstance(cid, str) and cid:
                        ids.add(cid)
    return ids


async def diff_versions(
    session_id: UUID, version_a: int, version_b: int,
) -> VersionDiff | None:
    """Load two snapshots and return the structured diff. ``None``
    when either version doesn't exist; the API layer maps that to
    a 404."""
    # Local import — keeps the diff module's import cost low and
    # avoids a circular at module-load time.
    from .service import get_version

    va = await get_version(session_id, version_a)
    vb = await get_version(session_id, version_b)
    if va is None or vb is None:
        return None

    pa = va.payload_snapshot or {}
    pb = vb.payload_snapshot or {}
    diff = VersionDiff(
        session_id=str(session_id),
        version_a=version_a,
        version_b=version_b,
    )

    # Use changed_sections to enumerate the affected paths, then
    # categorise each via membership in the two payloads.
    paths = changed_sections(pa, pb)
    for path in paths:
        present_a = _path_value(pa, path) is not _MISSING
        present_b = _path_value(pb, path) is not _MISSING
        if present_a and not present_b:
            old_value = _path_value(pa, path)
            old_text = _stringify(old_value)
            diff.section_changes.append(SectionChange(
                section_path=path, change="removed",
                old_text=old_text,
            ))
        elif present_b and not present_a:
            new_value = _path_value(pb, path)
            new_text = _stringify(new_value)
            diff.section_changes.append(SectionChange(
                section_path=path, change="added",
                new_text=new_text,
            ))
        else:
            old_value = _path_value(pa, path)
            new_value = _path_value(pb, path)
            old_text = _stringify(old_value)
            new_text = _stringify(new_value)
            diff.section_changes.append(SectionChange(
                section_path=path, change="modified",
                old_text=old_text, new_text=new_text,
                word_segments=_word_diff(old_text, new_text),
            ))

    # Claim deltas across the standard claim-carrying surfaces.
    claims_a = _extract_claim_ids(pa)
    claims_b = _extract_claim_ids(pb)
    diff.claim_changes = {
        "added": sorted(claims_b - claims_a),
        "removed": sorted(claims_a - claims_b),
    }

    return diff


# Sentinel for "path not present in payload" so an absent key is
# distinguishable from a key whose value is None.
_MISSING = object()


def _path_value(payload: dict[str, Any], path: str) -> Any:
    """Resolve a top-level or one-level ``frameworks.x`` path
    against the payload. Returns the sentinel when the key isn't
    present so the diff can distinguish "removed" from "set-to-None"."""
    if "." in path:
        head, tail = path.split(".", 1)
        bucket = payload.get(head)
        if not isinstance(bucket, dict) or tail not in bucket:
            return _MISSING
        return bucket[tail]
    return payload.get(path, _MISSING)


__all__ = [
    "ChangeKind",
    "DiffSegment",
    "SectionChange",
    "VersionDiff",
    "changed_sections",
    "diff_versions",
]
