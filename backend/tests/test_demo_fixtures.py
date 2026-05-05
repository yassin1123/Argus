"""Validate that demo fixtures parse correctly and have the shape the seeder expects.

This is the "single source of truth" check that keeps `DEMO_MODE`, the case-study
docs, and the test suite in sync. If a fixture drifts from the schema, tests fail
loudly before the demo seeder ever runs against Postgres.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "germany_vs_france"

REQUIRED_FILES = [
    "session.json",
    "evidence.json",
    "report.json",
    "claim_support.json",
    "agent_outputs.json",
    "pipeline_events.json",
]

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _load(name: str) -> Any:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename", REQUIRED_FILES)
def test_fixture_file_exists_and_parses(filename: str) -> None:
    path = FIXTURE_ROOT / filename
    assert path.exists(), f"missing fixture file: {filename}"
    json.loads(path.read_text(encoding="utf-8"))


def test_session_fixture_shape() -> None:
    s = _load("session.json")
    assert UUID_RE.match(s["id"]), "session.id must be a UUID"
    assert s["status"] in ("draft", "complete", "processing", "failed", "insufficient")
    assert s["report_mode"] in ("general", "market_entry", "due_diligence", "growth_strategy")
    assert isinstance(s["metadata"], dict)
    assert s["metadata"].get("demo") is True, "demo flag must be set on demo fixtures"
    assert "client_label" in s["metadata"]
    assert "engagement_type" in s["metadata"]
    assert isinstance(s["intake_questions"], list)
    assert isinstance(s["intake_answers"], list)


def test_evidence_fixture_shape() -> None:
    items = _load("evidence.json")
    assert isinstance(items, list) and len(items) > 0
    for e in items:
        assert UUID_RE.match(e["id"]), f"evidence.id must be a UUID, got {e['id']}"
        assert isinstance(e["task_id"], int)
        assert e["source_type"] in ("web", "document", "knowledge")
        assert e["confidence"] in ("high", "medium", "low", "unknown")
        assert isinstance(e["is_inference"], bool)
        assert 0.0 <= float(e["source_score"]) <= 1.0
        assert e["quote"], "every evidence object must carry a quote"


def test_report_fixture_shape() -> None:
    r = _load("report.json")
    assert UUID_RE.match(r["id"])
    assert r["recommendation"]
    assert r["confidence_level"]
    assert r["summary"]
    assert isinstance(r["key_reasons"], list) and len(r["key_reasons"]) >= 3
    assert isinstance(r["sources"], list) and len(r["sources"]) > 0
    assert isinstance(r["verification"], dict)
    assert isinstance(r["reasoning_graph"], dict)
    assert "nodes" in r["reasoning_graph"]
    assert "edges" in r["reasoning_graph"]


def test_executive_insights_link_to_known_claim_ids() -> None:
    r = _load("report.json")
    cs = _load("claim_support.json")
    known_claims = {row["claim_id"] for row in cs}

    for insight in r.get("executive_insights", []):
        for cid in insight.get("claim_ids", []):
            assert cid in known_claims, f"executive insight references unknown claim_id {cid}"

    for risk in r.get("key_risks_structured", []):
        for cid in risk.get("claim_ids", []):
            assert cid in known_claims, f"key risk references unknown claim_id {cid}"

    for cid in r.get("recommendation_claim_ids", []):
        assert cid in known_claims, f"recommendation references unknown claim_id {cid}"


def test_claim_support_rows_reference_known_evidence() -> None:
    cs = _load("claim_support.json")
    ev = _load("evidence.json")
    known_evidence = {e["id"] for e in ev}

    for row in cs:
        assert row["claim_id"]
        assert row["claim_text"]
        assert row["support_type"] in (
            "direct_quote",
            "paraphrase",
            "inference",
            "assumption",
        )
        if row.get("verifier_verdict") is not None:
            assert row["verifier_verdict"] in (
                "supported",
                "weak",
                "unsupported",
                "overstates",
                "contradicts",
            )
        for eid in row.get("evidence_object_ids", []):
            assert eid in known_evidence, f"claim {row['claim_id']} cites missing evidence {eid}"
        if "entailment_score" in row:
            assert 0.0 <= float(row["entailment_score"]) <= 1.0


def test_pipeline_events_cover_full_pipeline() -> None:
    events = _load("pipeline_events.json")
    stages_seen = {e.get("stage") for e in events if isinstance(e, dict)}
    expected = {"planner", "researcher", "analyst", "critic", "verifier", "writer"}
    assert expected.issubset(stages_seen), f"missing stages: {expected - stages_seen}"

    # Every started/progress event for a stage should be followed by a completed/error event.
    by_stage: dict[str, list[str]] = {}
    for e in events:
        stage = e.get("stage")
        status = e.get("status")
        if stage and status:
            by_stage.setdefault(stage, []).append(status)
    for stage, statuses in by_stage.items():
        if stage == "pipeline":
            continue
        if "started" in statuses:
            assert any(s in statuses for s in ("completed", "failed")), (
                f"stage {stage} has 'started' without a terminal event"
            )


def test_agent_outputs_cover_revision_cycle() -> None:
    outputs = _load("agent_outputs.json")
    names = [o.get("agent_name") for o in outputs]
    assert "planner" in names
    assert "researcher" in names
    assert "analyst" in names
    assert "critic" in names
    assert "verifier" in names
    assert "writer" in names
    # Token counts should be present and positive.
    for o in outputs:
        assert isinstance(o.get("token_count"), int) and o["token_count"] > 0


def test_verifier_section_assesses_known_claims() -> None:
    r = _load("report.json")
    cs = _load("claim_support.json")
    known_claims = {row["claim_id"] for row in cs}

    assessments = r.get("verification", {}).get("claim_assessments", [])
    assert len(assessments) >= 1
    for a in assessments:
        cid = a.get("claim_id")
        assert cid in known_claims, f"verifier assesses unknown claim {cid}"
        assert a.get("verdict") in (
            "supported",
            "weak",
            "unsupported",
            "overstates",
            "contradicts",
        )
