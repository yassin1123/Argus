from agents.research.orchestrator import _dedupe_web_evidence_best_url
from models.evidence import EvidenceObject


def test_dedupe_keeps_higher_score_per_url() -> None:
    a = EvidenceObject(
        session_id="550e8400-e29b-41d4-a716-446655440000",
        task_id=1,
        claim="c",
        quote="q1",
        source_title="t",
        source_url="https://example.com/page?utm_source=x",
        source_type="web",
        source_score=0.3,
        confidence="medium",
        is_inference=False,
    )
    b = EvidenceObject(
        session_id="550e8400-e29b-41d4-a716-446655440000",
        task_id=1,
        claim="c",
        quote="q2",
        source_title="t",
        source_url="https://example.com/page",
        source_type="web",
        source_score=0.9,
        confidence="medium",
        is_inference=False,
    )
    doc = EvidenceObject(
        session_id="550e8400-e29b-41d4-a716-446655440000",
        task_id=1,
        claim="c",
        quote="qd",
        source_title="pdf",
        source_url="",
        source_type="document",
        source_score=0.5,
        confidence="high",
        is_inference=False,
    )
    out = _dedupe_web_evidence_best_url([a, b, doc])
    assert len(out) == 2
    webs = [x for x in out if x.source_type == "web"]
    assert len(webs) == 1
    assert webs[0].source_score == 0.9


def test_preferred_domain_boost() -> None:
    from core.research_utils import preferred_domain_boost

    assert preferred_domain_boost("www.sec.gov", ["sec.gov"]) > 0
    assert preferred_domain_boost("news.ycombinator.com", ["sec.gov"]) == 0.0
