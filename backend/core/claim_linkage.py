"""Validate writer output claim_id references against analyst key_claims."""

import os
from typing import Any

from models.report import WriterReportPayload

_STRICT = os.getenv("ARGUS_STRICT_WRITER_CLAIM_IDS", "1").lower() in ("1", "true", "yes")


def allowed_claim_ids_from_analysis(analysis: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    kc = analysis.get("key_claims")
    if not isinstance(kc, list):
        return out
    for item in kc:
        if isinstance(item, dict) and str(item.get("text", "")).strip():
            cid = str(item.get("claim_id") or "").strip()
            if cid:
                out.add(cid)
    return out


def substantive_key_claim_count(analysis: dict[str, Any]) -> int:
    kc = analysis.get("key_claims")
    if not isinstance(kc, list):
        return 0
    n = 0
    for item in kc:
        if isinstance(item, dict) and str(item.get("text", "")).strip():
            n += 1
    return n


def validate_writer_claim_linkage(
    payload: WriterReportPayload,
    analysis: dict[str, Any],
    *,
    strict: bool | None = None,
) -> tuple[bool, list[str]]:
    """
    Ensures executive_insights, recommendation_claim_ids, and key_risks_structured
    only reference analyst key_claims.claim_id values when strict.
    """
    if strict is None:
        strict = _STRICT
    errors: list[str] = []
    allowed = allowed_claim_ids_from_analysis(analysis)
    n_kc = substantive_key_claim_count(analysis)

    def _check_ids(label: str, cids: list[str]) -> None:
        for cid in cids:
            s = str(cid).strip()
            if s and s not in allowed:
                errors.append(f'{label}: unknown claim_id "{s}" (not in analyst key_claims).')

    for i, ins in enumerate(payload.executive_insights):
        _check_ids(f"executive_insights[{i}]", list(ins.claim_ids))

    _check_ids("recommendation_claim_ids", list(payload.recommendation_claim_ids))

    for i, kr in enumerate(payload.key_risks_structured):
        _check_ids(f"key_risks_structured[{i}]", list(kr.claim_ids))

    if strict and n_kc > 0:
        if not payload.recommendation_claim_ids:
            errors.append(
                "recommendation_claim_ids must be non-empty when the analysis has substantive key_claims."
            )
        if not payload.executive_insights:
            errors.append(
                "executive_insights must be non-empty (each item needs text + claim_ids) when key_claims exist."
            )

    return len(errors) == 0, errors
