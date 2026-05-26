"""Tests for the W21/D1 golden-set fixtures + loader + labelling CLI.

Six spec assertions:

  1. synthetic set builds deterministically (same call → same list)
  2. synthetic set covers all 4 verdict classes
  3. synthetic set covers all 5 categories
  4. loader composes synthetic + labelled real-run files into one set
  5. extraction worksheet shape is what the labeller consumes
  6. label CLI's --apply-json mode records ground-truth onto rows

All six run with no DB. The extraction worksheet test uses a
synthetic worksheet shape (the SQL path is exercised separately
when Postgres is available).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from eval.golden_set import GoldenEntry, GoldenSet  # noqa: E402
from eval.golden_set.build_synthetic import (  # noqa: E402
    build_synthetic_entries,
)
from eval.golden_set.loader import load_golden_set  # noqa: E402
from eval.golden_set.types import (  # noqa: E402
    VERDICT_COLLAPSE_5_TO_4,
    Category,
    Verdict,
    collapse_verdict,
)


# ---------------------------------------------------------------------------
# 1. determinism
# ---------------------------------------------------------------------------


def test_synthetic_set_builds_deterministically() -> None:
    """Two consecutive calls must produce byte-identical lists. A
    stable regression baseline is non-negotiable."""
    first = build_synthetic_entries()
    second = build_synthetic_entries()
    assert len(first) == len(second)
    # Compare by id + ground_truth + claim + evidence + category — these
    # are the fields the Day 2 evaluator scores against; any drift
    # invalidates a prior accuracy measurement.
    keys = ["id", "ground_truth", "claim", "evidence", "category", "adversarial"]
    a = [{k: getattr(e, k) for k in keys} for e in first]
    b = [{k: getattr(e, k) for k in keys} for e in second]
    assert a == b
    # ids are sequential.
    assert [e.id for e in first] == [
        f"gs_{i+1:03d}" for i in range(len(first))
    ]


# ---------------------------------------------------------------------------
# 2. verdict coverage
# ---------------------------------------------------------------------------


def test_synthetic_covers_all_verdict_classes() -> None:
    """Every ground-truth verdict appears at least 5 times.
    Day 2's accuracy bench needs enough per-bucket samples that
    the per-class precision/recall isn't dominated by a single
    misclassification."""
    entries = build_synthetic_entries()
    by_verdict: dict[str, int] = {}
    for e in entries:
        by_verdict[e.ground_truth] = by_verdict.get(e.ground_truth, 0) + 1
    expected = {v.value for v in Verdict}
    assert set(by_verdict.keys()) == expected, (
        f"missing verdicts: {expected - by_verdict.keys()}"
    )
    for verdict, n in by_verdict.items():
        assert n >= 5, f"{verdict} only has {n} entries; spec asks for ≥5"


# ---------------------------------------------------------------------------
# 3. category coverage
# ---------------------------------------------------------------------------


def test_synthetic_covers_all_categories() -> None:
    """Every category appears at least 8 times — enough to break
    Day 4's regression report down by category and still report
    meaningful per-category accuracy."""
    entries = build_synthetic_entries()
    by_category: dict[str, int] = {}
    for e in entries:
        by_category[e.category] = by_category.get(e.category, 0) + 1
    expected = {c.value for c in Category}
    assert set(by_category.keys()) == expected, (
        f"missing categories: {expected - by_category.keys()}"
    )
    for category, n in by_category.items():
        assert n >= 8, f"{category} only has {n} entries; spec asks for ≥8"

    # Total ≥ 60 — spec target is ~60 synthetic pairs.
    assert len(entries) >= 60

    # Adversarial cases exist (Day 4 needs the calibration-sensitive
    # rows). At least 10 across the set.
    adversarial = sum(1 for e in entries if e.adversarial)
    assert adversarial >= 10, (
        f"only {adversarial} adversarial entries; need ≥10 "
        "to cover Day 4's magnitude/attribution mismatch checks"
    )


# ---------------------------------------------------------------------------
# 4. loader composes synthetic + real-run files
# ---------------------------------------------------------------------------


def test_golden_set_loads_synthetic_and_real(tmp_path: Path) -> None:
    """Drop a labelled real-run YAML/JSON into a tmp dir; assert the
    loader merges it with the synthetic backbone, sorts real entries
    by id, and exposes all four buckets via the convenience accessors."""
    real_runs = tmp_path / "real_runs"
    real_runs.mkdir()

    # Two labelled real-run rows.
    fixture = {
        "version": 1,
        "labelled_at": "2026-05-26T12:00:00+00:00",
        "entries": [
            {
                "id": "rr_002",
                "claim": "CompetitorB lost market share in FY2023.",
                "evidence": "CompetitorB's FY2023 share fell 180 bps.",
                "evidence_source": "real_run",
                "ground_truth": "supported",
                "label_rationale": "Explicit 180 bps share decline.",
                "category": "numeric_claim",
                "adversarial": False,
                "real_run_session_id": "11111111-1111-1111-1111-111111111111",
                "real_run_claim_id": "cl_99",
                "extra": {"verifier_verdict_at_label_time": "supported_high"},
            },
            {
                "id": "rr_001",
                "claim": "The CEO confirmed dividends would resume in FY2024.",
                "evidence": "Capital allocation was discussed; no specific commitment was made.",
                "evidence_source": "real_run",
                "ground_truth": "insufficient",
                "label_rationale": "No specific resume commitment.",
                "category": "attribution",
                "adversarial": True,
                "real_run_session_id": "22222222-2222-2222-2222-222222222222",
                "real_run_claim_id": "cl_42",
                "extra": {"verifier_verdict_at_label_time": "supported_low"},
            },
        ],
    }
    (real_runs / "labelled_2026-05-26.json").write_text(json.dumps(fixture))

    gs = load_golden_set(real_runs_dir=real_runs)
    assert isinstance(gs, GoldenSet)
    synth = [e for e in gs if e.evidence_source == "synthetic"]
    real = [e for e in gs if e.evidence_source == "real_run"]
    assert len(synth) >= 60
    assert len(real) == 2
    # Real rows sorted by id ascending — rr_001 first, rr_002 second.
    assert [e.id for e in real] == ["rr_001", "rr_002"]
    # by_source / by_verdict / by_category accessors all populated.
    assert len(gs.by_source()["synthetic"]) >= 60
    assert len(gs.by_source()["real_run"]) == 2
    assert "supported" in gs.by_verdict() and gs.by_verdict()["supported"]
    assert (
        "attribution" in gs.by_category()
        and gs.by_category()["attribution"]
    )

    # The 5→4 verdict collapse helper maps cleanly:
    assert collapse_verdict("supported_high") == "supported"
    assert collapse_verdict("supported_low") == "supported"
    assert collapse_verdict("weak") == "partial"
    assert collapse_verdict("unsupported") == "insufficient"
    assert collapse_verdict("contradicted") == "contradicted"
    assert collapse_verdict("garbage") == "partial"  # defensive default


# ---------------------------------------------------------------------------
# 5. labelling worksheet shape
# ---------------------------------------------------------------------------


def test_labeling_worksheet_generated_from_real_runs(tmp_path: Path) -> None:
    """The extraction worksheet must carry the fields the labeller
    sees + the row-keys the label CLI applies labels onto. Builds
    one synthetically (the DB extraction is exercised when Postgres
    is up) and asserts the shape."""
    worksheet = {
        "version": 1,
        "generated_at": "2026-05-26T12:00:00+00:00",
        "source": {
            "firm_slug": "meridian-advisory",
            "session_id": None,
            "per_verdict": 10,
            "limit": 400,
        },
        "rows": [
            {
                "id": "wks_0001",
                "session_id": "11111111-1111-1111-1111-111111111111",
                "claim_id": "ev_1",
                "claim": "CompetitorB lost market share in FY2023.",
                "evidence": "CompetitorB's FY2023 share fell 180 bps.",
                "verifier_verdict": "supported_high",
                "evidence_source_type": "sec_filing",
                "label": None,
                "label_rationale": None,
                "category": None,
            },
        ],
    }
    path = tmp_path / "worksheet.json"
    path.write_text(json.dumps(worksheet))
    loaded = json.loads(path.read_text())
    # Shape contract:
    assert loaded["version"] == 1
    assert "generated_at" in loaded
    assert "rows" in loaded and isinstance(loaded["rows"], list)
    row = loaded["rows"][0]
    required_keys = {
        "id", "session_id", "claim", "evidence",
        "verifier_verdict", "evidence_source_type",
        "label", "label_rationale", "category",
    }
    assert required_keys.issubset(row.keys())
    # Labels start as None — the labeller fills them in.
    assert row["label"] is None
    assert row["category"] is None


# ---------------------------------------------------------------------------
# 6. label CLI --apply-json records ground truth onto worksheet rows
# ---------------------------------------------------------------------------


def test_label_cli_records_ground_truth(tmp_path: Path) -> None:
    """Drive ``tools/label_claims.py`` via its non-interactive
    --apply-json path. The script reads a worksheet + a pre-recorded
    JSON map of {id → label info}, writes the labelled fixture to
    --out, and the result must round-trip through the loader as
    real-run GoldenEntry rows."""
    # Load the label CLI via importlib — the tools/ dir isn't a
    # package, and adding it to sys.path can collide with stdlib
    # module names. importlib gives us a direct file load.
    import importlib.util
    # _REPO is the `backend/` dir; tools/ lives at the actual repo root.
    project_root = _REPO.parent
    spec = importlib.util.spec_from_file_location(
        "label_claims_cli", project_root / "tools" / "label_claims.py",
    )
    assert spec and spec.loader
    label_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(label_cli)

    worksheet = {
        "version": 1,
        "rows": [
            {
                "id": "wks_0001",
                "session_id": "11111111-1111-1111-1111-111111111111",
                "claim_id": "ev_1",
                "claim": "CompetitorB lost market share in FY2023.",
                "evidence": "CompetitorB's FY2023 share fell 180 bps.",
                "verifier_verdict": "supported_high",
                "evidence_source_type": "sec_filing",
                "label": None, "label_rationale": None, "category": None,
            },
            {
                "id": "wks_0002",
                "session_id": "11111111-1111-1111-1111-111111111111",
                "claim_id": "ev_2",
                "claim": "FY2024 EBITDA will grow 30%.",
                "evidence": "FY2024 guidance projected EBITDA growth of 10-15%.",
                "verifier_verdict": "supported_low",
                "evidence_source_type": "transcript",
                "label": None, "label_rationale": None, "category": None,
            },
        ],
    }
    ws_path = tmp_path / "worksheet.json"
    ws_path.write_text(json.dumps(worksheet))

    labels = {
        "wks_0001": {
            "label": "supported",
            "category": "numeric_claim",
            "label_rationale": "Direct 180 bps share decline.",
            "adversarial": False,
        },
        "wks_0002": {
            "label": "partial",
            "category": "forecast",
            "label_rationale": "Direction supported, magnitude overstated.",
            "adversarial": True,
        },
    }
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(labels))

    out_path = tmp_path / "labelled.json"  # avoid yaml dep
    rc = label_cli.main([
        "--in", str(ws_path),
        "--out", str(out_path),
        "--apply-json", str(labels_path),
    ])
    assert rc == 0
    assert out_path.exists()

    # Round-trip through the loader from a tmp real_runs dir.
    real_runs = tmp_path / "real_runs"
    real_runs.mkdir()
    (real_runs / "labelled.json").write_text(out_path.read_text())
    gs = load_golden_set(
        include_synthetic=False, real_runs_dir=real_runs,
    )
    assert len(gs) == 2
    entries = sorted(gs.entries, key=lambda e: e.id)
    assert entries[0].id == "wks_0001"
    assert entries[0].ground_truth == "supported"
    assert entries[0].category == "numeric_claim"
    assert entries[0].evidence_source == "real_run"
    assert entries[0].real_run_session_id == (
        "11111111-1111-1111-1111-111111111111"
    )
    assert entries[1].id == "wks_0002"
    assert entries[1].ground_truth == "partial"
    assert entries[1].adversarial is True
    # The verifier's verdict at label time was preserved in extra —
    # the Day 2 evaluator uses this to spot the disagreements.
    assert (
        entries[1].extra.get("verifier_verdict_at_label_time")
        == "supported_low"
    )
