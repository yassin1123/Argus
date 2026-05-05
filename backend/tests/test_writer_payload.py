import pytest

from models.report import WriterReportPayload


def test_writer_payload_coerces_sources_and_lists() -> None:
    raw = {
        "recommendation": "Do X",
        "confidence_level": "High",
        "summary": "Short",
        "key_reasons": ["a", "b"],
        "risks": ["r"],
        "counterarguments": ["c"],
        "next_steps": ["n"],
        "sources": [{"title": "T", "type": "web"}, {"title": "Bare"}],
        "caveats": "Be careful",
        "executive_insights": [{"text": "Insight", "claim_ids": ["c1"]}],
        "recommendation_claim_ids": ["c1"],
        "key_risks_structured": [{"text": "Risk", "claim_ids": ["c1"]}],
    }
    p = WriterReportPayload.model_validate(raw)
    assert p.caveats == "Be careful"
    assert len(p.sources) == 2
    assert p.sources[1].type == "knowledge"
    assert len(p.executive_insights) == 1
    assert p.recommendation_claim_ids == ["c1"]
