from core.reasoning_skeleton import get_required_slots, validate_reasoning_skeleton


def test_general_mode_no_required_slots() -> None:
    assert get_required_slots("general") == []
    ok, errs = validate_reasoning_skeleton({"key_claims": []}, "general")
    assert ok and errs == []


def test_market_entry_requires_slots() -> None:
    required = get_required_slots("market_entry")
    assert "market_attractiveness" in required
    analysis = {
        "key_claims": [{"claim_id": "c1", "text": "x", "evidence_ids": ["e1"]}],
        "reasoning_slots": [],
    }
    ok, errs = validate_reasoning_skeleton(analysis, "market_entry")
    assert not ok
    assert any("Missing reasoning slot" in e for e in errs)


def test_slots_with_valid_claim_ids() -> None:
    analysis = {
        "key_claims": [{"claim_id": "c1", "text": "Market is growing", "evidence_ids": ["e1"]}],
        "reasoning_slots": [
            {
                "slot_id": "market_attractiveness",
                "summary": "Demand signals are positive in target segment",
                "claim_ids": ["c1"],
            },
            {
                "slot_id": "competition",
                "summary": "Fragmented landscape with two dominant vendors",
                "claim_ids": ["c1"],
            },
            {
                "slot_id": "risks",
                "summary": "Execution and regulatory risks remain material",
                "claim_ids": ["c1"],
            },
            {
                "slot_id": "feasibility",
                "summary": "Operational feasibility depends on partner network",
                "claim_ids": ["c1"],
            },
        ],
    }
    ok, errs = validate_reasoning_skeleton(analysis, "market_entry")
    assert ok and not errs
