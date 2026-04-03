from core.contradiction_policy import (
    apply_confidence_cap,
    compute_contradiction_severity,
    max_allowed_rank_for_severity,
)
from models.report import WriterReportPayload


def test_compute_severity_counts_sources() -> None:
    cs = [
        {"nli_label": "contradicts", "verifier_verdict": "supported", "contradiction_flag": False},
        {"nli_label": "neutral", "verifier_verdict": "unsupported", "contradiction_flag": True},
    ]
    s = compute_contradiction_severity(
        research_contradictions=["a", "b"],
        verification={"contradictions": ["v1"]},
        claim_support=cs,
    )
    assert s >= 5


def test_apply_confidence_cap_lowers_high() -> None:
    p = WriterReportPayload.model_validate(
        {
            "recommendation": "R",
            "confidence_level": "High",
            "summary": "S",
            "key_reasons": ["a"],
            "risks": ["r"],
            "counterarguments": ["c"],
            "next_steps": ["n"],
            "sources": [{"title": "t", "type": "web"}],
        }
    )
    apply_confidence_cap(p, severity=10)
    assert p.confidence_level == "Low"


def test_max_allowed_rank_monotonic() -> None:
    assert max_allowed_rank_for_severity(0) > max_allowed_rank_for_severity(10)
