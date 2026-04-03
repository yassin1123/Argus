"""Programmatic checks on verifier JSON — evidence_ids must exist in catalog (no invented UUIDs)."""

from typing import Any


def sanitize_verification_assessments(
    verification: dict[str, Any],
    allowed_evidence_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Strip invalid evidence_ids from each claim_assessment; drop assessments that are not dicts.
    Returns (mutated verification copy for safety, stats dict).
    """
    out = dict(verification)
    raw = out.get("claim_assessments")
    if not isinstance(raw, list):
        out["claim_assessments"] = []
        return out, {"assessments_in": 0, "assessments_out": 0, "invalid_id_strips": 0, "had_invalid": False}

    cleaned: list[dict[str, Any]] = []
    invalid_strips = 0
    for a in raw:
        if not isinstance(a, dict):
            continue
        row = dict(a)
        eids_raw = row.get("evidence_ids")
        if not isinstance(eids_raw, list):
            row["evidence_ids"] = []
        else:
            kept: list[str] = []
            for x in eids_raw:
                s = str(x).strip()
                if s in allowed_evidence_ids:
                    kept.append(s)
                elif s:
                    invalid_strips += 1
            row["evidence_ids"] = kept
        cleaned.append(row)

    out["claim_assessments"] = cleaned
    stats = {
        "assessments_in": len(raw),
        "assessments_out": len(cleaned),
        "invalid_id_strips": invalid_strips,
        "had_invalid": invalid_strips > 0,
    }
    return out, stats


def verification_assessments_usable(
    verification: dict[str, Any],
    *,
    min_assessments: int = 1,
    key_claims_count: int = 0,
) -> tuple[bool, str]:
    """
    After sanitization: require at least min_assessments assessments when analysis has key claims.
    If key_claims_count > 0 but assessments empty, verification is not usable.
    """
    ca = verification.get("claim_assessments")
    if not isinstance(ca, list):
        return False, "claim_assessments missing or not a list"
    n = len([x for x in ca if isinstance(x, dict)])
    if key_claims_count > 0 and n < min_assessments:
        return False, f"expected at least {min_assessments} claim_assessments, got {n}"
    return True, ""
