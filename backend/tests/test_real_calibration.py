"""Tests for the W22/D1 real-claim calibration.

Five spec assertions:

  1. extraction worksheet is stratified across verifier verdicts
  2. real calibration drives every pair through the real verifier
     path (via the runner's VerifierProtocol surface) — never an LLM
     call we don't own
  3. raw scores are cached to raw_scores_real.json for replay
  4. synthetic-vs-real comparison numbers + deltas are computed
  5. the scoping verdict is recorded with the W22/D1 disposition
     rules: light_polish / borderline / full_fix / labeling_pending

The runner is exercised with a controlled-stub verifier so the
test is deterministic + cheap (no LLM, no DeBERTa, no DB).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from eval.calibration.run_real_calibration import (  # noqa: E402
    BORDERLINE_FP_CEILING,
    LIGHT_POLISH_FP_CEILING,
    W21_SYNTHETIC_FP_RATE,
    W21_SYNTHETIC_RECALL_INS,
    _classify_scoping,
    write_real_calibration,
)
from eval.calibration.runner import RawScores  # noqa: E402
from eval.golden_set import GoldenEntry, GoldenSet  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — stub verifier + a small labelled real batch
# ---------------------------------------------------------------------------


class _StubVerifier:
    """Returns hard-coded raw scores per claim id (encoded in the
    claim text via a known prefix). Lets the test produce specific
    FP rates without any LLM calls."""

    name = "test_stub_real"

    def __init__(self) -> None:
        self.calls = 0

    def score(self, claim: str, evidence: str) -> RawScores:
        self.calls += 1
        # All claims in the test fixture push toward "supported" so
        # the FP rate is dictated by ground truth.
        return RawScores(
            llm_verdict="supported",
            deberta_label="entailment",
            deberta_confidence=0.85,
            deberta_softmax=(0.05, 0.85, 0.10),
            lexical_numeric_score=1.0,
            lexical_entity_score=1.0,
        )


def _labelled_batch(real_runs: Path, fixture: list[dict]) -> None:
    """Drop a labelled JSON file the loader can pick up."""
    real_runs.mkdir(parents=True, exist_ok=True)
    (real_runs / "labelled.json").write_text(
        json.dumps({"version": 1, "entries": fixture})
    )


# ---------------------------------------------------------------------------
# 1. worksheet stratified across verdicts
# ---------------------------------------------------------------------------


def test_real_batch_extracted_stratified(tmp_path: Path) -> None:
    """The extractor's _stratify keeps at most ``per_verdict`` rows
    per verifier verdict bucket so the labelling worksheet isn't
    dominated by the most common class."""
    # Load tools/extract_claims_for_labeling.py via importlib.
    project_root = _REPO.parent
    spec = importlib.util.spec_from_file_location(
        "extract_cli",
        project_root / "tools" / "extract_claims_for_labeling.py",
    )
    assert spec and spec.loader
    extract_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract_cli)

    rows = [
        {"id": f"a{i}", "verifier_verdict": "supported_high"}
        for i in range(20)
    ] + [
        {"id": f"b{i}", "verifier_verdict": "weak"} for i in range(8)
    ] + [
        {"id": f"c{i}", "verifier_verdict": "unsupported"} for i in range(5)
    ]
    stratified = extract_cli._stratify(rows, per_verdict=10)
    by_v: dict[str, int] = {}
    for r in stratified:
        by_v[r["verifier_verdict"]] = by_v.get(r["verifier_verdict"], 0) + 1
    # Each bucket is capped at 10; under-represented buckets pass
    # through unchanged so the labeller sees their full population.
    assert by_v == {
        "supported_high": 10,   # capped
        "weak": 8,              # under cap, all kept
        "unsupported": 5,       # under cap, all kept
    }
    # Total never exceeds sum of caps.
    assert len(stratified) == 23


# ---------------------------------------------------------------------------
# 2. calibration drives every pair through the verifier
# ---------------------------------------------------------------------------


def test_real_calibration_runs_through_real_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every labelled real-batch pair is sent to ``verifier.score``.
    Counts the calls + asserts the loader picked them all up."""
    fixture = [
        {
            "id": f"rr_{i:03d}",
            "claim": f"unique claim text {i}",
            "evidence": f"evidence chunk {i}",
            "evidence_source": "real_run",
            "ground_truth": "supported",
            "label_rationale": "test",
            "category": "numeric_claim",
            "adversarial": False,
            "real_run_session_id": None,
            "real_run_claim_id": None,
        }
        for i in range(5)
    ]
    real_runs = tmp_path / "real_runs"
    _labelled_batch(real_runs, fixture)

    # Redirect the loader to this tmp dir + redirect output paths.
    import eval.calibration.run_real_calibration as mod
    from eval.golden_set import loader as loader_mod
    monkeypatch.setattr(loader_mod, "REAL_RUNS_DIR", real_runs)

    stub = _StubVerifier()
    monkeypatch.setattr(
        mod, "_select_verifier", lambda name: stub,
    )

    out = tmp_path / "summary.json"
    raw = tmp_path / "raw_scores_real.json"
    summary = write_real_calibration(
        verifier_name="real_ensemble",  # opts into the path we mocked
        out_path=out, raw_path=raw,
    )
    assert summary["real_pair_count"] == 5
    assert stub.calls == 5, (
        f"verifier was called {stub.calls} times; expected 5"
    )
    assert summary["verifier_source"] == "test_stub_real"


# ---------------------------------------------------------------------------
# 3. raw scores cached to raw_scores_real.json
# ---------------------------------------------------------------------------


def test_real_raw_scores_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cached file lives at the W22/D1 path and round-trips
    through the runner's load_scored_pairs helper."""
    fixture = [
        {
            "id": "rr_001", "claim": "x", "evidence": "y",
            "evidence_source": "real_run", "ground_truth": "supported",
            "label_rationale": "test", "category": "numeric_claim",
            "adversarial": False,
        },
    ]
    real_runs = tmp_path / "real_runs"
    _labelled_batch(real_runs, fixture)

    import eval.calibration.run_real_calibration as mod
    from eval.golden_set import loader as loader_mod
    monkeypatch.setattr(loader_mod, "REAL_RUNS_DIR", real_runs)
    monkeypatch.setattr(mod, "_select_verifier", lambda name: _StubVerifier())

    out = tmp_path / "summary.json"
    raw = tmp_path / "raw_scores_real.json"
    write_real_calibration(
        verifier_name="real_ensemble", out_path=out, raw_path=raw,
    )
    assert raw.exists(), "raw_scores_real.json must be written"
    payload = json.loads(raw.read_text())
    assert payload["pair_count"] == 1
    assert payload["scored_pairs"][0]["id"] == "rr_001"

    # The runner's load helper round-trips the cached row.
    from eval.calibration.runner import load_scored_pairs
    pairs = load_scored_pairs(raw)
    assert len(pairs) == 1
    assert pairs[0].id == "rr_001"


# ---------------------------------------------------------------------------
# 4. synthetic vs real comparison
# ---------------------------------------------------------------------------


def test_real_vs_synthetic_comparison_computed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When real labels exist, the summary carries fp_delta +
    recall_delta + the synthetic-was-worst-case boolean."""
    # 5 supported + 5 insufficient; the stub always says supported.
    # That gives FP-rate = 5/10 = 50%; recall on insufficient = 0%.
    fixture = (
        [
            {
                "id": f"sup_{i}", "claim": f"sup claim {i}",
                "evidence": f"ev {i}",
                "evidence_source": "real_run", "ground_truth": "supported",
                "label_rationale": "t", "category": "numeric_claim",
                "adversarial": False,
            }
            for i in range(5)
        ]
        + [
            {
                "id": f"ins_{i}", "claim": f"ins claim {i}",
                "evidence": f"ev {i}",
                "evidence_source": "real_run", "ground_truth": "insufficient",
                "label_rationale": "t", "category": "numeric_claim",
                "adversarial": False,
            }
            for i in range(5)
        ]
    )
    real_runs = tmp_path / "real_runs"
    _labelled_batch(real_runs, fixture)

    import eval.calibration.run_real_calibration as mod
    from eval.golden_set import loader as loader_mod
    monkeypatch.setattr(loader_mod, "REAL_RUNS_DIR", real_runs)
    monkeypatch.setattr(mod, "_select_verifier", lambda name: _StubVerifier())

    summary = write_real_calibration(
        verifier_name="real_ensemble",
        out_path=tmp_path / "s.json",
        raw_path=tmp_path / "r.json",
    )
    comp = summary["comparison"]
    real_fp = summary["real_metrics"]["fp_rate_on_supported"]
    # FP delta = real (0.5) - synthetic (0.6) = -0.1.
    assert real_fp == pytest.approx(0.5)
    assert comp["real_vs_synthetic_fp_delta"] == pytest.approx(
        real_fp - W21_SYNTHETIC_FP_RATE, abs=1e-3,
    )
    # synthetic_was_worst_case True iff real_fp is meaningfully
    # below synthetic. Here real (0.5) < synthetic (0.6) by 0.1,
    # which crosses the runner's 0.05 worst-case threshold.
    assert comp["synthetic_was_worst_case"] is True


# ---------------------------------------------------------------------------
# 5. scoping verdict recorded with the spec's disposition
# ---------------------------------------------------------------------------


def test_scoping_verdict_recorded() -> None:
    """The four W22/D1 dispositions land on the right thresholds.

    The spec defines:
      - real_count = 0          -> labeling_pending
      - real_fp ≤ 0.10          -> light_polish
      - 0.10 < real_fp ≤ 0.20   -> borderline
      - real_fp >  0.20         -> full_fix
    """
    # labeling_pending
    v = _classify_scoping(real_fp=None, real_count=0)
    assert v.verdict == "labeling_pending"
    assert "synthetic" in v.rationale.lower()
    assert "full fix" in v.drives_w22_days_2_to_5.lower()

    # light_polish — well under ceiling
    v = _classify_scoping(real_fp=0.05, real_count=50)
    assert v.verdict == "light_polish"
    assert v.real_fp_rate_on_supported == pytest.approx(0.05)
    assert "polish" in v.rationale.lower()
    assert "light polish" in v.drives_w22_days_2_to_5.lower()

    # exactly at the light_polish ceiling — still light_polish (≤)
    v = _classify_scoping(real_fp=LIGHT_POLISH_FP_CEILING, real_count=50)
    assert v.verdict == "light_polish"

    # just above ceiling — borderline
    v = _classify_scoping(real_fp=0.12, real_count=50)
    assert v.verdict == "borderline"
    assert "borderline" in v.rationale.lower()

    # at borderline ceiling — still borderline (≤)
    v = _classify_scoping(real_fp=BORDERLINE_FP_CEILING, real_count=50)
    assert v.verdict == "borderline"

    # well above — full fix
    v = _classify_scoping(real_fp=0.40, real_count=50)
    assert v.verdict == "full_fix"
    assert "full upstream fix" in v.rationale.lower()
    assert "full upstream fix" in v.drives_w22_days_2_to_5.lower()
    # The synthetic baseline numbers are surfaced regardless.
    assert v.synthetic_fp_rate_on_supported == pytest.approx(
        W21_SYNTHETIC_FP_RATE,
    )
    assert v.synthetic_recall_on_insufficient == pytest.approx(
        W21_SYNTHETIC_RECALL_INS,
    )
