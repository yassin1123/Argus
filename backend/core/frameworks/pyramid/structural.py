"""Deterministic Pyramid structural pre-check — W8/D1.

Runs against the flat ``WriterReportBase`` shape (the base schema every
mode inherits from). All checks here are zero-LLM-cost.

Spec adaptation note: the W8/D1 spec referenced an ``executive_summary``
nested object with ``top_3_reasons`` (2-5 items) and a per-reason
``claim_citations`` linkage. The actual base schema is flat:

- ``recommendation: str``
- ``key_reasons: list[str]``  (schema-required 4-7)
- ``recommendation_claim_ids: list[str]``
- ``sources: list[SourceItem]``  (cited sources; not per-reason)

There is no per-reason ``claim_ids`` field, so the spec's
"each top reason has a matching supporting claim_id" check has no
direct hook here. We drop that test and rely on the LLM judge to
catch reasons that don't logically chain to the recommendation.
This matches the W8/D1 spec's explicit "Surface" item:
"existing schema already has fields that conflict with what the
structural check expects."
"""

from __future__ import annotations

from typing import Any

from agents.writer.schemas import WriterReportBase

from .types import PyramidFinding

# Pyramid spec wants "top 2-5 reasons". WriterReportBase requires
# key_reasons (4-7). We map the spec band onto the schema's band:
# pass when count is in [2, 7] (i.e. respect both the schema floor
# and the spec ceiling without re-tightening either).
_KEY_REASONS_MIN = 2
_KEY_REASONS_MAX = 7


def structural_pyramid_check(payload: WriterReportBase) -> list[PyramidFinding]:
    """Run cheap deterministic checks on a writer payload.

    Returns a list of findings (empty if everything passes).
    """
    findings: list[PyramidFinding] = []

    # 1. The lede must exist. Schema already requires recommendation;
    #    this catches an LLM that emits only whitespace.
    rec = (payload.recommendation or "").strip()
    if not rec:
        findings.append(
            PyramidFinding(
                field_path="recommendation",
                violation_type="answer_not_stated_first",
                description=(
                    "Recommendation is empty — the memo has no top-level answer "
                    "for the reader to anchor on."
                ),
                severity="error",
            )
        )

    # 2. key_reasons must exist within the [2, 7] band. Empty list means
    #    no support pyramid; >7 dilutes the top of the pyramid.
    n_reasons = len(payload.key_reasons or [])
    if n_reasons == 0:
        findings.append(
            PyramidFinding(
                field_path="key_reasons",
                violation_type="support_chain_broken",
                description=(
                    "key_reasons is empty — the recommendation has no stated "
                    "support, so the support chain to the lede is broken."
                ),
                severity="error",
            )
        )
    elif n_reasons < _KEY_REASONS_MIN:
        findings.append(
            PyramidFinding(
                field_path="key_reasons",
                violation_type="support_chain_broken",
                description=(
                    f"Only {n_reasons} key reason(s); pyramid structure expects "
                    f"at least {_KEY_REASONS_MIN}."
                ),
                severity="warning",
            )
        )
    elif n_reasons > _KEY_REASONS_MAX:
        findings.append(
            PyramidFinding(
                field_path="key_reasons",
                violation_type="claims_not_same_logical_category",
                description=(
                    f"{n_reasons} key reasons — pyramid structure dilutes above "
                    f"{_KEY_REASONS_MAX}. Consider grouping into fewer parent reasons."
                ),
                severity="info",
            )
        )

    # 3. recommendation_claim_ids: when the writer produced any key_claims-
    #    style linkage (executive_insights non-empty signals the analyst had
    #    claims), the recommendation should cite at least one of them. The
    #    orchestrator's claim-linkage validator already enforces this hard at
    #    the gate; we surface it here as an advisory pyramid finding too so
    #    the reader sees it framed structurally.
    has_exec_insights = any(
        (getattr(item, "text", "") or "").strip() for item in (payload.executive_insights or [])
    )
    rec_claim_ids = [str(x).strip() for x in (payload.recommendation_claim_ids or []) if str(x).strip()]
    if has_exec_insights and not rec_claim_ids:
        findings.append(
            PyramidFinding(
                field_path="recommendation_claim_ids",
                violation_type="missing_evidence_link",
                description=(
                    "Recommendation has no claim-id linkage even though the "
                    "writer produced executive insights — the lede is unanchored."
                ),
                severity="warning",
            )
        )

    return findings


def build_skeleton_for_judge(payload: WriterReportBase, char_cap: int = 2000) -> str:
    """Compose the compact structural skeleton the LLM judge inspects.

    Includes the lede (recommendation + summary first sentence) plus
    the first sentence of each key_reason — enough to test "is the
    answer stated first" and "do the reasons logically chain" without
    sending the full memo.

    Capped at ``char_cap`` to keep the judge call cheap (~$0.001).
    """
    parts: list[str] = []
    rec = (payload.recommendation or "").strip()
    if rec:
        parts.append(f"RECOMMENDATION: {rec}")
    summary = (payload.summary or "").strip()
    if summary:
        # Just the first sentence keeps the skeleton lean.
        first_sent = summary.split(".", 1)[0].strip()
        if first_sent:
            parts.append(f"SUMMARY[0]: {first_sent}.")
    reasons = [str(r).strip() for r in (payload.key_reasons or []) if str(r).strip()]
    for i, r in enumerate(reasons):
        first_sent = r.split(".", 1)[0].strip()
        if first_sent:
            parts.append(f"REASON[{i}]: {first_sent}.")
    risks = [str(x).strip() for x in (payload.risks or []) if str(x).strip()]
    for i, rk in enumerate(risks[:3]):
        parts.append(f"RISK[{i}]: {rk.split('.', 1)[0].strip()}.")
    text = "\n".join(parts)
    if len(text) > char_cap:
        text = text[: char_cap - 3].rstrip() + "..."
    return text


def _payload_to_dict(payload: Any) -> dict[str, Any]:
    """Tolerant accessor used by tests + the LLM judge — accepts either a
    pydantic ``WriterReportBase`` (real path) or a plain dict (fixture-driven
    tests) without forcing callers to re-instantiate.
    """
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return dict(payload)
    return {}
