from agents.analyst import _strip_ungrounded_key_claims, _sanitize_evidence_ids


def test_strip_ungrounded_moves_to_candidates() -> None:
    analysis = {
        "key_claims": [
            {"text": "Grounded", "evidence_ids": ["u1"]},
            {"text": "Ungrounded", "evidence_ids": []},
        ]
    }
    allowed = {"u1"}
    _sanitize_evidence_ids(analysis, allowed)
    _strip_ungrounded_key_claims(analysis)
    kc = analysis["key_claims"]
    assert len(kc) == 1
    assert kc[0]["text"] == "Grounded"
    uc = analysis.get("ungrounded_candidates") or []
    assert len(uc) == 1
    assert uc[0]["text"] == "Ungrounded"
