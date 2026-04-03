from core.evidence_graph import build_evidence_graph_v1
from models.evidence import EvidenceObject


def test_build_evidence_graph_v1_minimal() -> None:
    ev = EvidenceObject(
        session_id="00000000-0000-0000-0000-000000000001",
        task_id=1,
        claim="c",
        quote="q",
        source_title="t",
        source_url="https://x",
        source_date=None,
        source_type="web",
        source_score=0.8,
        confidence="high",
        is_inference=False,
    )
    ev.id = "e1"
    g = build_evidence_graph_v1(
        analysis={"recommendation": "Do X"},
        verification={"claim_assessments": [], "contradictions": []},
        claim_support=[
            {
                "claim_id": "k1",
                "claim_text": "Market grows",
                "evidence_object_ids": ["e1"],
                "support_type": "direct_quote",
            }
        ],
        evidence_objects=[ev],
    )
    assert g["version"] == 1
    assert any(e["kind"] == "evidence" for e in g["entities"])
    assert g["trust_scores"].get("e1")
