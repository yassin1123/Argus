"""Hard programmatic gates: analyst output must cite persisted evidence (no silent orphan ids)."""

import os
from typing import Any

from models.evidence import EvidenceObject

# If true, every key_claim must cite at least one evidence row that is not is_inference-only.
_STRICT_NO_INFERENCE_ONLY = os.getenv("ARGUS_STRICT_NO_INFERENCE_ONLY", "1").lower() in (
    "1",
    "true",
    "yes",
)


def validate_analyst_evidence_gates(
    analysis: dict[str, Any],
    evidence_objects: list[EvidenceObject],
    *,
    ban_inference_only: bool | None = None,
) -> tuple[bool, list[str]]:
    """
    Returns (ok, error_messages).

    When evidence_objects is non-empty:
    - key_claims must be a non-empty list.
    - Each key_claim with non-empty text must have >=1 evidence_id that exists in the catalog.
    - Optionally: each such claim must cite at least one non-inference evidence object.
    """
    if ban_inference_only is None:
        ban_inference_only = _STRICT_NO_INFERENCE_ONLY

    if not evidence_objects:
        return True, []

    by_id: dict[str, EvidenceObject] = {str(o.id): o for o in evidence_objects if o.id}
    if not by_id:
        return True, []

    kc = analysis.get("key_claims")
    errors: list[str] = []

    if not isinstance(kc, list) or len(kc) == 0:
        errors.append(
            "key_claims must be a non-empty list when evidence objects exist; every substantive "
            "position must be backed by catalog evidence ids."
        )
        return False, errors

    substantive = 0
    for i, item in enumerate(kc):
        if not isinstance(item, dict):
            errors.append(f"key_claims[{i}] is not an object.")
            continue
        text = str(item.get("text", "")).strip()
        raw_ids = item.get("evidence_ids")
        ids = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else []
        if not text:
            continue
        substantive += 1
        if not ids:
            errors.append(f'key_claims[{i}] "{text[:80]}..." has no evidence_ids.')
            continue
        missing = [eid for eid in ids if eid not in by_id]
        if missing:
            errors.append(
                f'key_claims[{i}] cites unknown evidence ids (not in catalog): {missing[:5]}'
            )
        if ban_inference_only and ids and not missing:
            cited = [by_id[eid] for eid in ids if eid in by_id]
            if cited and all(o.is_inference for o in cited):
                errors.append(
                    f'key_claims[{i}] cites only inference-flagged evidence; cite at least one '
                    f"directly grounded row (is_inference=false)."
                )

    if substantive == 0:
        errors.append(
            "key_claims must contain at least one non-empty text entry tied to evidence when "
            "the evidence catalog is non-empty."
        )

    return len(errors) == 0, errors
