from core.verification_validate import sanitize_verification_assessments, verification_assessments_usable


def test_sanitize_strips_unknown_evidence_ids() -> None:
    allowed = {"aaa", "bbb"}
    ver = {
        "claim_assessments": [
            {"claim": "c1", "evidence_ids": ["aaa", "fake"], "verdict": "supported"},
            "not-a-dict",
        ],
        "overall": "sufficient",
    }
    out, stats = sanitize_verification_assessments(ver, allowed)
    assert stats["invalid_id_strips"] == 1
    ca = out["claim_assessments"]
    assert len(ca) == 1
    assert ca[0]["evidence_ids"] == ["aaa"]


def test_usable_requires_assessments_when_key_claims() -> None:
    ver = {"claim_assessments": []}
    ok, _ = verification_assessments_usable(ver, key_claims_count=0)
    assert ok is True
    ok2, _ = verification_assessments_usable(ver, key_claims_count=2)
    assert ok2 is False
