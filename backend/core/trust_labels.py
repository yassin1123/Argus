"""Server-side labels for trust / evidence strength (UI consumes labels only)."""

from __future__ import annotations

from typing import Any


def score_band(score: float | None) -> str:
    if score is None:
        return "Unrated"
    s = float(score)
    if s >= 0.55:
        return "Strong"
    if s >= 0.32:
        return "Moderate"
    return "Weak"


def evidence_quality_mix_label(evidence_objects: list[dict[str, Any]]) -> str:
    if not evidence_objects:
        return "No sources"
    bands = [score_band(float(o.get("source_score") or 0)) for o in evidence_objects]
    strong = sum(1 for b in bands if b == "Strong")
    if strong >= max(2, len(bands) // 3):
        return "Mostly strong"
    if any(b == "Strong" for b in bands):
        return "Mixed quality"
    if all(b == "Weak" for b in bands):
        return "Mostly thin"
    return "Balanced"


def build_trust_labels(
    *,
    report: dict[str, Any] | None,
    verification: dict[str, Any] | None,
    evidence_objects: list[dict[str, Any]],
    contradiction_severity: float | None = None,
) -> dict[str, Any]:
    """Structured trust object subset for API / metadata (no raw verifier field names in labels)."""
    ver = verification or {}
    overall = str(ver.get("overall", "")).lower()
    unsupported = int(report.get("unsupported_claim_count") or 0) if report else 0
    conf = str(report.get("confidence_level", "") if report else "")
    mix = evidence_quality_mix_label(evidence_objects)
    sev = float(contradiction_severity or 0)
    contra_label = "None"
    if sev >= 0.65:
        contra_label = "High"
    elif sev >= 0.35:
        contra_label = "Moderate"
    elif sev > 0:
        contra_label = "Low"

    cap_reason = ""
    if overall == "insufficient":
        cap_reason = "Verification marked the evidence base as insufficient."
    elif unsupported > 0:
        cap_reason = f"{unsupported} claim(s) flagged as weak or unsupported."

    return {
        "confidence_level": conf,
        "confidence_display": conf,
        "evidence_strength_label": mix,
        "verification_overall_label": "Sufficient" if overall == "sufficient" else "Insufficient" if overall else "Pending",
        "contradiction_severity_label": contra_label,
        "unsupported_claims_count": unsupported,
        "what_capped_confidence": cap_reason,
    }
