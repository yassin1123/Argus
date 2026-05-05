"""Tests for the UI evidence graph normalizer (`build_ui_evidence_graph`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.evidence_graph import build_ui_evidence_graph

FIXTURES = Path(__file__).parent / "fixtures" / "germany_vs_france"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _claim_node_for(graph: dict[str, Any], claim_id: str) -> dict[str, Any] | None:
    for n in graph["nodes"]:
        if n["type"] == "claim" and n["id"] == claim_id:
            return n
    return None


def test_empty_inputs_yield_empty_graph() -> None:
    g = build_ui_evidence_graph(
        reasoning_graph=None,
        evidence_objects=None,
        claim_support_rows=None,
    )
    assert g["nodes"] == []
    assert g["edges"] == []
    assert g["stats"] == {
        "claims": 0,
        "evidence": 0,
        "sources": 0,
        "supported": 0,
        "weak": 0,
        "unsupported": 0,
    }


def test_germany_fixture_has_expected_node_distribution() -> None:
    rg = _load("report")["reasoning_graph"]
    ev = _load("evidence")
    cs = _load("claim_support")
    cp = {"recommendation_claim_ids": _load("report").get("recommendation_claim_ids", [])}

    g = build_ui_evidence_graph(
        reasoning_graph=rg,
        evidence_objects=ev,
        claim_support_rows=cs,
        consulting_payload=cp,
    )

    counts: dict[str, int] = {}
    for n in g["nodes"]:
        counts[n["type"]] = counts.get(n["type"], 0) + 1

    assert counts.get("claim") == 6
    # Each of the 9 web sources contributes one evidence object (Numeum is shared).
    # Some claims reuse the same evidence id, so referenced count <= 10.
    assert counts.get("evidence", 0) >= 6
    assert counts.get("source", 0) >= 6


def test_germany_fixture_verdict_counts_match_claim_support() -> None:
    rg = _load("report")["reasoning_graph"]
    ev = _load("evidence")
    cs = _load("claim_support")

    g = build_ui_evidence_graph(
        reasoning_graph=rg,
        evidence_objects=ev,
        claim_support_rows=cs,
    )
    assert g["stats"]["supported"] == 5
    assert g["stats"]["weak"] == 1
    assert g["stats"]["unsupported"] == 0


def test_recommendation_claims_flagged_in_recommendation() -> None:
    rg = _load("report")["reasoning_graph"]
    ev = _load("evidence")
    cs = _load("claim_support")
    rec_ids = _load("report")["recommendation_claim_ids"]

    g = build_ui_evidence_graph(
        reasoning_graph=rg,
        evidence_objects=ev,
        claim_support_rows=cs,
        consulting_payload={"recommendation_claim_ids": rec_ids},
    )
    for cid in rec_ids:
        node = _claim_node_for(g, cid)
        assert node is not None, f"recommendation claim {cid} missing from graph"
        assert node["in_recommendation"] is True

    # Non-recommendation claims should have in_recommendation = False
    other = _claim_node_for(g, "c6")
    assert other is not None
    assert other["in_recommendation"] is False


def test_inference_evidence_carries_is_inference_true() -> None:
    rg = _load("report")["reasoning_graph"]
    ev = _load("evidence")
    cs = _load("claim_support")

    g = build_ui_evidence_graph(
        reasoning_graph=rg,
        evidence_objects=ev,
        claim_support_rows=cs,
    )
    inference_nodes = [n for n in g["nodes"] if n["type"] == "evidence" and n.get("is_inference")]
    assert len(inference_nodes) == 1
    assert "argus" in inference_nodes[0]["source_title"].lower()


def test_every_edge_endpoint_has_a_node() -> None:
    rg = _load("report")["reasoning_graph"]
    ev = _load("evidence")
    cs = _load("claim_support")

    g = build_ui_evidence_graph(
        reasoning_graph=rg,
        evidence_objects=ev,
        claim_support_rows=cs,
    )
    node_ids = {n["id"] for n in g["nodes"]}
    for edge in g["edges"]:
        assert edge["from"] in node_ids, f"edge.from {edge['from']} missing"
        assert edge["to"] in node_ids, f"edge.to {edge['to']} missing"


def test_weak_claim_carries_weak_flag() -> None:
    rg = _load("report")["reasoning_graph"]
    ev = _load("evidence")
    cs = _load("claim_support")

    g = build_ui_evidence_graph(
        reasoning_graph=rg,
        evidence_objects=ev,
        claim_support_rows=cs,
    )
    c4 = _claim_node_for(g, "c4")
    assert c4 is not None
    assert c4["weak"] is True
    assert c4["verifier_verdict"] == "weak"


def test_sources_aggregate_evidence_correctly() -> None:
    rg = _load("report")["reasoning_graph"]
    ev = _load("evidence")
    cs = _load("claim_support")

    g = build_ui_evidence_graph(
        reasoning_graph=rg,
        evidence_objects=ev,
        claim_support_rows=cs,
    )
    sources = [n for n in g["nodes"] if n["type"] == "source"]
    # Source evidence_count must equal number of evidence-to-source edges into it.
    for src in sources:
        in_edges = [e for e in g["edges"] if e["to"] == src["id"]]
        assert len(in_edges) == src["evidence_count"], (
            f"source {src['id']}: {len(in_edges)} edges vs {src['evidence_count']} count"
        )


def test_missing_evidence_id_emits_stub_node() -> None:
    """If reasoning_graph cites an evidence id we don't have an object for,
    a stub evidence node is emitted so the graph stays connected."""
    rg = {
        "claims": [
            {"claim_id": "c1", "text": "test claim", "evidence_object_ids": ["missing-uuid"]},
        ]
    }
    g = build_ui_evidence_graph(
        reasoning_graph=rg,
        evidence_objects=[],
        claim_support_rows=[],
    )
    stub = next((n for n in g["nodes"] if n["id"] == "missing-uuid"), None)
    assert stub is not None
    assert stub["type"] == "evidence"
    assert "missing" in stub["label"].lower()


def test_claim_only_in_claim_support_rows_still_appears() -> None:
    """A claim present in claim_support_rows but absent from reasoning_graph.claims
    should still be promoted into the graph."""
    cs = [
        {
            "claim_id": "x1",
            "claim_text": "Orphan claim",
            "evidence_object_ids": [],
            "support_type": "inference",
            "verifier_verdict": "weak",
            "weak_or_unsupported": True,
        }
    ]
    g = build_ui_evidence_graph(
        reasoning_graph={},
        evidence_objects=[],
        claim_support_rows=cs,
    )
    node = _claim_node_for(g, "x1")
    assert node is not None
    assert node["weak"] is True


@pytest.mark.parametrize("verdict,expected", [
    ("supported", "supported"),
    ("weak", "weak"),
    ("unsupported", "unsupported"),
    ("overstates", "overstates"),
    ("contradicts", "contradicts"),
    ("nonsense", "unknown"),
    (None, "unknown"),
])
def test_verdict_normalization(verdict: str | None, expected: str) -> None:
    cs = [
        {
            "claim_id": "v1",
            "claim_text": "test",
            "evidence_object_ids": [],
            "support_type": "inference",
            "verifier_verdict": verdict,
        }
    ]
    g = build_ui_evidence_graph(
        reasoning_graph={},
        evidence_objects=[],
        claim_support_rows=cs,
    )
    node = _claim_node_for(g, "v1")
    assert node is not None
    assert node["verifier_verdict"] == expected
