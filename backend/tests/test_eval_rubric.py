import json
import pathlib

from core.eval_rubric import score_pipeline_artifacts


def test_rubric_flags_consulting_blocks() -> None:
    m = score_pipeline_artifacts(
        report_payload={},
        verification={"overall": "sufficient", "claim_assessments": []},
        evidence_count=3,
        gate_passed=True,
        consulting_payload={
            "decision_criteria": [{"criterion": "ROI"}],
            "options_matrix": [{"option": "A"}],
            "kill_criteria": ["If budget cuts"],
            "what_would_change_our_mind": "A definitive RCT showing harm.",
            "evidence_ledger_summary": "Three primary sources support the call.",
        },
    )
    assert m["has_decision_criteria"] is True
    assert m["has_options_matrix"] is True
    assert m["has_kill_criteria"] is True
    assert m["has_what_would_change_mind"] is True
    assert m["has_evidence_ledger_summary"] is True
    assert m["gate_passed"] is True
    assert m["rubric_version"] == 3
    assert m["branch_coverage_rate"] == 1.0


def test_golden_tasks_fixture_loads() -> None:
    p = pathlib.Path(__file__).parent / "fixtures" / "golden_tasks.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data.get("tasks"), list)
    assert len(data["tasks"]) >= 1
    assert int(data.get("version", 0)) >= 2
