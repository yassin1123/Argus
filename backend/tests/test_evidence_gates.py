from models.evidence import EvidenceObject
from core.evidence_gates import validate_analyst_evidence_gates


def _obj(eid: str, inference: bool = False) -> EvidenceObject:
    return EvidenceObject(
        id=eid,
        session_id="550e8400-e29b-41d4-a716-446655440000",
        task_id=1,
        claim="c",
        quote="q",
        source_title="t",
        source_url="",
        source_type="document",
        source_score=0.5,
        confidence="high",
        is_inference=inference,
    )


def test_gate_passes_with_valid_key_claims() -> None:
    ev = [_obj("11111111-1111-1111-1111-111111111111", False)]
    analysis = {
        "key_claims": [
            {"text": "Markets rose", "evidence_ids": ["11111111-1111-1111-1111-111111111111"]},
        ]
    }
    ok, errs = validate_analyst_evidence_gates(analysis, ev, ban_inference_only=False)
    assert ok and not errs


def test_gate_fails_empty_key_claims_when_evidence_exists() -> None:
    ev = [_obj("11111111-1111-1111-1111-111111111111")]
    ok, errs = validate_analyst_evidence_gates({"key_claims": []}, ev)
    assert not ok
    assert any("non-empty" in e.lower() or "key_claims" in e for e in errs)


def test_gate_fails_inference_only_when_banned() -> None:
    ev = [_obj("11111111-1111-1111-1111-111111111111", inference=True)]
    analysis = {
        "key_claims": [
            {"text": "X", "evidence_ids": ["11111111-1111-1111-1111-111111111111"]},
        ]
    }
    ok, errs = validate_analyst_evidence_gates(analysis, ev, ban_inference_only=True)
    assert not ok
    assert any("inference" in e.lower() for e in errs)


def test_gate_skips_when_no_evidence_catalog() -> None:
    ok, errs = validate_analyst_evidence_gates({"key_claims": []}, [])
    assert ok
