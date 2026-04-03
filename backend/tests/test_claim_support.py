from core.claim_support import build_claim_support, lexical_entailment_score
from models.evidence import EvidenceObject


def test_lexical_entailment_partial_overlap() -> None:
    s = lexical_entailment_score("revenue grew in q3", "company revenue increased during third quarter")
    assert 0 < s <= 1.0


def test_build_claim_support_types() -> None:
    ev = EvidenceObject(
        session_id="00000000-0000-0000-0000-000000000001",
        task_id=1,
        claim="c",
        quote="revenue grew strongly in q3",
        source_title="doc",
        source_url="",
        source_type="document",
        source_score=0.5,
        confidence="high",
        is_inference=False,
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    analysis = {
        "key_claims": [
            {"text": "Revenue grew in Q3", "evidence_ids": [ev.id]},
        ],
        "assumptions": ["Management will execute"],
    }
    verification = {
        "claim_assessments": [{"claim": "Revenue grew in Q3", "verdict": "supports", "evidence_ids": [ev.id]}]
    }
    rows = build_claim_support(analysis, [ev], verification)
    assert len(rows) >= 2
    kc = next(r for r in rows if r.get("claim_text", "").startswith("Revenue"))
    assert kc.get("support_type") == "direct_quote"
    asm = next(r for r in rows if "Management" in (r.get("claim_text") or ""))
    assert asm.get("support_type") == "assumption"
