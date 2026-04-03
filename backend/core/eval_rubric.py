"""Lightweight post-run rubric scores (deterministic checks) for evaluations / golden tests."""

from typing import Any


def score_pipeline_artifacts(
    *,
    report_payload: dict[str, Any],
    verification: dict[str, Any],
    evidence_count: int,
    gate_passed: bool,
    consulting_payload: dict[str, Any] | None = None,
    report_mode: str = "general",
    branch_ids_present: set[str] | None = None,
    verifier_invalid_id_strips: int = 0,
    mean_entailment_score: float | None = None,
    research_followup_queries: int = 0,
) -> dict[str, Any]:
    """Returns metrics merged into evaluations.metrics."""
    cp = consulting_payload or report_payload.get("consulting_payload") or {}
    if not isinstance(cp, dict):
        cp = {}

    criteria = cp.get("decision_criteria") or []
    matrix = cp.get("options_matrix") or []
    kill = cp.get("kill_criteria") or []
    wwcm = (cp.get("what_would_change_our_mind") or "").strip()
    ledger = (cp.get("evidence_ledger_summary") or "").strip()

    unsupported = sum(
        1
        for a in (verification.get("claim_assessments") or [])
        if isinstance(a, dict) and str(a.get("verdict", "")).lower() in ("unsupported", "overstates")
    )

    from core.consulting_modes import get_mode_config

    cfg = get_mode_config(report_mode)
    req_br = [str(b).lower() for b in (cfg.get("required_branches") or [])]
    pres = {b.lower() for b in (branch_ids_present or set())}
    covered = sum(1 for b in req_br if b in pres)
    branch_coverage_rate = (covered / len(req_br)) if req_br else 1.0

    return {
        "rubric_version": 3,
        "report_mode": report_mode,
        "gate_passed": gate_passed,
        "evidence_count": evidence_count,
        "unsupported_claim_assessments": unsupported,
        "has_decision_criteria": bool(isinstance(criteria, list) and len(criteria) > 0),
        "has_options_matrix": bool(isinstance(matrix, list) and len(matrix) > 0),
        "has_kill_criteria": bool(isinstance(kill, list) and len(kill) > 0),
        "has_what_would_change_mind": bool(len(wwcm) > 20),
        "has_evidence_ledger_summary": bool(len(ledger) > 20),
        "verifier_overall": str(verification.get("overall", "")).lower(),
        "required_branches_count": len(req_br),
        "covered_branches_count": covered,
        "branch_coverage_rate": round(branch_coverage_rate, 4),
        "verifier_invalid_id_strips": int(verifier_invalid_id_strips),
        "mean_entailment_score": round(mean_entailment_score, 4) if mean_entailment_score is not None else None,
        "research_followup_queries": int(research_followup_queries),
    }
