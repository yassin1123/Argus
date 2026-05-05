from deliverables.assemble import build_deliverable_document
from deliverables.blueprint import build_deliverable_blueprint
from deliverables.pptx_build import build_slide_blueprint, render_pptx_from_blueprint
from deliverables.render_pdf import render_deliverable_html


def test_build_deliverable_document_minimal() -> None:
    report = {
        "recommendation": "Go",
        "summary": "S",
        "key_reasons": ["a", "b", "c"],
        "risks": ["r1"],
        "consulting_payload": {
            "executive_insights": [{"text": "i1", "claim_ids": ["c1"]}],
            "decision_criteria": [{"criterion": "ROI", "weight": "high", "how_met": "Met"}],
        },
        "reasoning_graph": {"reasoning_slots": [{"slot_id": "market", "summary": "Growing", "claim_ids": []}]},
        "claim_support": [{"claim_text": "x", "evidence_object_ids": ["u1"]}],
        "sources": [{"title": "Doc", "type": "pdf"}],
    }
    doc = build_deliverable_document(report=report, session_query="Should we expand?", session_title="EU")
    assert doc.exec_recommendation == "Go"
    assert len(doc.findings) >= 1
    html = render_deliverable_html(doc, variant="full", report=report)
    assert "Executive summary" in html
    assert "Decision criteria" in html


def test_deliverable_blueprint_unifies_pdf_and_slides() -> None:
    report = {
        "recommendation": "R",
        "summary": "S",
        "key_reasons": ["a"],
        "risks": ["r"],
        "consulting_payload": {
            "decision_criteria": [{"criterion": "C", "weight": "med", "how_met": "ok"}],
        },
        "sources": [{"title": "Src", "type": "pdf"}],
    }
    bp = build_deliverable_blueprint(report=report, session_query="Q?", session_title="T")
    assert bp.document.exec_recommendation == "R"
    assert len(bp.slide_blueprint.slides) >= 2
    assert bp.fingerprint
    data, meta = render_pptx_from_blueprint(bp.slide_blueprint)
    assert len(data) > 1000
    assert meta.get("brand")


def test_pptx_blueprint_roundtrip() -> None:
    report = {
        "recommendation": "R",
        "summary": "S",
        "key_reasons": ["a"],
        "risks": ["r"],
        "consulting_payload": {
            "decision_criteria": [{"criterion": "C", "weight": "med", "how_met": "ok"}],
        },
    }
    bp = build_slide_blueprint(report=report, session_query="Q?", session_title="T")
    assert len(bp.slides) >= 2
    data, meta = render_pptx_from_blueprint(bp)
    assert len(data) > 1000
    assert "slides" in meta
