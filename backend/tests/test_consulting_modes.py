from core.consulting_modes import branch_ids_from_evidence_claims, check_mode_satisfied
from models.evidence import EvidenceObject


def test_branch_ids_from_claim_prefix() -> None:
    o = EvidenceObject(
        session_id="x",
        task_id=1,
        claim="[branch:market] demand rising",
        quote="q",
        source_title="t",
        source_url="",
        source_type="web",
        source_score=0.1,
        confidence="medium",
        is_inference=False,
    )
    assert branch_ids_from_evidence_claims([o]) == {"market"}


def test_check_mode_satisfied() -> None:
    ok, gaps = check_mode_satisfied(
        "market_entry",
        branch_ids_present={"market", "competition"},
        evidence_count=5,
    )
    assert ok is False
    assert any("regulation" in g for g in gaps)

    ok2, gaps2 = check_mode_satisfied(
        "market_entry",
        branch_ids_present={"market", "competition", "regulation"},
        evidence_count=5,
    )
    assert ok2 is True
    assert gaps2 == []
