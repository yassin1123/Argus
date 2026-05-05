import json

import pytest

from agents.orchestrator import build_evidence_bundle
from models.evidence import RetrievedChunk


def test_retrieved_chunk_from_row() -> None:
    row = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "chunk_text": "Hello world evidence",
        "chunk_index": 0,
        "file_id": None,
        "chunk_meta": {"source_url": "https://example.com/x", "page": 2},
        "filename": "doc.pdf",
        "file_type": "pdf",
        "similarity": 0.91,
    }
    c = RetrievedChunk.from_row(row)
    assert c.chunk_id == "550e8400-e29b-41d4-a716-446655440000"
    assert c.similarity == 0.91
    assert c.source_url == "https://example.com/x"
    assert c.page == 2


def test_build_evidence_bundle_flattens() -> None:
    research = {
        "findings": [
            {
                "task_id": 1,
                "finding": "F1",
                "evidence": [{"chunk_id": "a", "quote": "q"}],
                "web_citations": [{"title": "T", "url": "https://u", "snippet": "S"}],
            }
        ]
    }
    b = build_evidence_bundle(research)
    assert len(b) == 2
    kinds = {x["kind"] for x in b}
    assert "document_chunk" in kinds
    assert "web" in kinds


def test_research_payload_schema() -> None:
    from models.evidence import ResearchPayload

    raw = {
        "findings": [
            {
                "task_id": 1,
                "question": "Q",
                "finding": "F",
                "confidence": "low",
                "evidence": [{"chunk_id": "x", "quote": "verbatim from doc"}],
                "web_citations": [],
                "gaps": "none",
            }
        ]
    }
    p = ResearchPayload.model_validate(raw)
    assert len(p.findings) == 1
    assert p.findings[0].evidence[0].chunk_id == "x"


def test_writer_report_payload_still_validates() -> None:
    from models.report import WriterReportPayload

    data = {
        "recommendation": "R",
        "confidence_level": "Medium",
        "summary": "S",
        "key_reasons": ["a"],
        "risks": ["b"],
        "counterarguments": ["c"],
        "next_steps": ["d"],
        "sources": [{"title": "t", "type": "document"}],
        "caveats": "caveat",
    }
    WriterReportPayload.model_validate(data)


def test_golden_fixture_bundle() -> None:
    import pathlib

    p = pathlib.Path(__file__).parent / "fixtures" / "golden_research.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    b = build_evidence_bundle(data)
    assert any(x.get("kind") == "document_chunk" for x in b)


def test_save_report_sql_shape() -> None:
    """Regression: save_report accepts evidence_bundle and verification kwargs (signature)."""
    import inspect

    from db import queries

    sig = inspect.signature(queries.save_report)
    assert "evidence_bundle" in sig.parameters
    assert "verification" in sig.parameters
    assert "consulting_payload" in sig.parameters


def test_evidence_object_roundtrip_model() -> None:
    from models.evidence import EvidenceObject

    o = EvidenceObject(
        session_id="550e8400-e29b-41d4-a716-446655440000",
        task_id=1,
        claim="c",
        quote="q",
        source_title="t",
        source_url="https://x",
        source_type="web",
        source_score=0.5,
        confidence="high",
        is_inference=False,
    )
    row = {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "session_id": o.session_id,
        "task_id": 1,
        "claim": "c",
        "quote": "q",
        "source_title": "t",
        "source_url": "https://x",
        "source_date": None,
        "source_type": "web",
        "source_score": 0.5,
        "confidence": "high",
        "is_inference": False,
        "created_at": None,
    }
    back = EvidenceObject.from_db_row(row)
    assert back.id == row["id"]
    assert back.quote == "q"
