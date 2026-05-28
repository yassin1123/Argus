"""Edit telemetry — Phase 5 / Week 24 / Day 3.

Measures how much a consultant rewrote the auto-generated draft
before approving it. The killer signal: a high edit rate means the
system isn't producing usable drafts.

We diff the **version-1 (auto-generated) payload** against the
**approved/live payload** at the word level (reusing the W19 diff
helpers) and the claim set at the structural level. We persist only
the COUNTS + the 0..1 ``edit_fraction`` — never the prose (W20
privacy line: log that an edit happened + how much, never what).

``edit_fraction`` is symmetric churn over the union::

    edit_fraction = (words_added + words_removed)
                    / (words_same + words_added + words_removed)

so 0.0 = approved verbatim, 1.0 = entirely rewritten. The
engagement view renders "approved with N% edits".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from db.connection import acquire


@dataclass
class EditTelemetry:
    session_id: str
    firm_id: str
    words_baseline: int
    words_same: int
    words_added: int
    words_removed: int
    edit_fraction: float
    claims_baseline: int
    claims_added: int
    claims_removed: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def _baseline_payload(session_id: UUID | str) -> dict[str, Any] | None:
    """The auto-generated draft: the earliest payload version
    (change_type='initial', else lowest version_number)."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT payload_snapshot
              FROM payload_versions
             WHERE session_id = $1::uuid
             ORDER BY (change_type = 'initial') DESC, version_number ASC
             LIMIT 1
            """,
            str(session_id),
        )
    if not row:
        return None
    import json
    snap = row["payload_snapshot"]
    if isinstance(snap, str):
        try:
            snap = json.loads(snap)
        except Exception:
            return None
    return snap if isinstance(snap, dict) else None


async def compute_edit_telemetry(
    session_id: UUID | str, firm_id: UUID | str,
) -> EditTelemetry:
    """Compute (but don't persist) the word + claim churn between the
    auto-generated draft and the current live payload. Returns an
    all-zero telemetry when there's no baseline version (nothing to
    diff against)."""
    from core.versioning.diff import (
        _WORD_RE, _extract_claim_ids, _stringify, changed_sections,
    )
    from core.versioning.service import _load_live_payload_for_session

    baseline = await _baseline_payload(session_id)
    final = await _load_live_payload_for_session(UUID(str(session_id)))

    if baseline is None:
        # No version history → treat the live payload as the baseline
        # (zero edits measured rather than a misleading number).
        baseline = final or {}

    same = added = removed = 0
    # Count baseline words across every top-level section.
    baseline_words = 0
    for k in set(baseline.keys()) | set((final or {}).keys()):
        old_text = _stringify(baseline.get(k))
        new_text = _stringify((final or {}).get(k))
        baseline_words += len(
            [w for w in _WORD_RE.findall(old_text) if w.strip()]
        )
        if old_text == new_text:
            same += len([w for w in _WORD_RE.findall(old_text) if w.strip()])
            continue
        import difflib
        a = _WORD_RE.findall(old_text)
        b = _WORD_RE.findall(new_text)
        matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            n_a = len([w for w in a[i1:i2] if w.strip()])
            n_b = len([w for w in b[j1:j2] if w.strip()])
            if tag == "equal":
                same += n_a
            elif tag == "delete":
                removed += n_a
            elif tag == "insert":
                added += n_b
            elif tag == "replace":
                removed += n_a
                added += n_b

    total = same + added + removed
    edit_fraction = (added + removed) / total if total else 0.0

    claims_base = _extract_claim_ids(baseline)
    claims_final = _extract_claim_ids(final or {})

    return EditTelemetry(
        session_id=str(session_id),
        firm_id=str(firm_id),
        words_baseline=baseline_words,
        words_same=same,
        words_added=added,
        words_removed=removed,
        edit_fraction=round(edit_fraction, 4),
        claims_baseline=len(claims_base),
        claims_added=len(claims_final - claims_base),
        claims_removed=len(claims_base - claims_final),
    )


async def compute_and_record_edit_telemetry(
    session_id: UUID | str,
    firm_id: UUID | str,
    approved_by: UUID | str | None = None,
) -> EditTelemetry:
    """Compute the telemetry and upsert it. One row per engagement;
    a re-approval refreshes it. Best-effort at the call site — the
    approval must not roll back if telemetry fails."""
    t = await compute_edit_telemetry(session_id, firm_id)
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO engagement_edit_telemetry
                (session_id, firm_id, words_baseline, words_same,
                 words_added, words_removed, edit_fraction,
                 claims_baseline, claims_added, claims_removed, approved_by)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (session_id) DO UPDATE SET
                words_baseline = EXCLUDED.words_baseline,
                words_same = EXCLUDED.words_same,
                words_added = EXCLUDED.words_added,
                words_removed = EXCLUDED.words_removed,
                edit_fraction = EXCLUDED.edit_fraction,
                claims_baseline = EXCLUDED.claims_baseline,
                claims_added = EXCLUDED.claims_added,
                claims_removed = EXCLUDED.claims_removed,
                approved_by = EXCLUDED.approved_by,
                created_at = NOW()
            """,
            str(session_id), str(firm_id), t.words_baseline, t.words_same,
            t.words_added, t.words_removed, t.edit_fraction,
            t.claims_baseline, t.claims_added, t.claims_removed,
            str(approved_by) if approved_by else None,
        )
    return t


__all__ = [
    "EditTelemetry",
    "compute_and_record_edit_telemetry",
    "compute_edit_telemetry",
]
