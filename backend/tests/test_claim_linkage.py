import os

from core.claim_linkage import validate_writer_claim_linkage
from models.report import WriterReportPayload


def test_validate_writer_claim_linkage_ok() -> None:
    analysis = {
        "key_claims": [
            {"claim_id": "cid-1", "text": "Markets grew", "evidence_ids": ["e1"]},
        ]
    }
    p = WriterReportPayload.model_validate(
        {
            "recommendation": "Expand",
            "confidence_level": "Medium",
            "summary": "S",
            "key_reasons": ["a"],
            "risks": ["r"],
            "counterarguments": ["c"],
            "next_steps": ["n"],
            "sources": [{"title": "t", "type": "web"}],
            "executive_insights": [{"text": "Growth", "claim_ids": ["cid-1"]}],
            "recommendation_claim_ids": ["cid-1"],
            "key_risks_structured": [{"text": "Volatility", "claim_ids": ["cid-1"]}],
        }
    )
    ok, errs = validate_writer_claim_linkage(p, analysis, strict=True)
    assert ok and not errs


def test_validate_rejects_unknown_claim_id() -> None:
    analysis = {"key_claims": [{"claim_id": "cid-1", "text": "x", "evidence_ids": []}]}
    p = WriterReportPayload.model_validate(
        {
            "recommendation": "R",
            "confidence_level": "Low",
            "summary": "S",
            "key_reasons": ["a"],
            "risks": ["r"],
            "counterarguments": ["c"],
            "next_steps": ["n"],
            "sources": [{"title": "t", "type": "web"}],
            "recommendation_claim_ids": ["bad-id"],
            "executive_insights": [{"text": "i", "claim_ids": ["cid-1"]}],
        }
    )
    ok, errs = validate_writer_claim_linkage(p, analysis, strict=True)
    assert not ok
    assert any("unknown claim_id" in e for e in errs)


def test_no_key_claims_allows_empty_linkage() -> None:
    old = os.environ.get("ARGUS_STRICT_WRITER_CLAIM_IDS")
    os.environ["ARGUS_STRICT_WRITER_CLAIM_IDS"] = "1"
    try:
        analysis = {"key_claims": []}
        p = WriterReportPayload.model_validate(
            {
                "recommendation": "R",
                "confidence_level": "Low",
                "summary": "S",
                "key_reasons": ["a"],
                "risks": ["r"],
                "counterarguments": ["c"],
                "next_steps": ["n"],
                "sources": [{"title": "t", "type": "web"}],
            }
        )
        ok, errs = validate_writer_claim_linkage(p, analysis, strict=True)
        assert ok and not errs
    finally:
        if old is None:
            os.environ.pop("ARGUS_STRICT_WRITER_CLAIM_IDS", None)
        else:
            os.environ["ARGUS_STRICT_WRITER_CLAIM_IDS"] = old
