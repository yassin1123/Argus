"""Tests for the W21/D4 hallucination red-team suite.

Six spec assertions:

  1. every red-team case's ground truth is NOT-supported
  2. every exploit type is represented in the set
  3. catch rate is computed
  4. escapes are listed with their exploit type
  5. numeric-consistency probe catches a fabricated figure
  6. per-exploit-type breakdown is produced

The runner is exercised with a controlled-stub verifier so the
test is deterministic + cheap. The real heuristic verifier is
exercised by the manual smoke run that writes escapes.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from core.nli.threshold_config import (  # noqa: E402
    ThresholdConfig,
    default_threshold_config,
)
from eval.calibration.runner import RawScores  # noqa: E402
from eval.red_team import (  # noqa: E402
    AdversarialCase,
    ExploitType,
    build_adversarial_cases,
    numeric_consistency_check,
)
from eval.red_team.run_red_team import (  # noqa: E402
    EXPLOIT_MITIGATIONS,
    run_red_team,
    triage,
    write_red_team_report,
)


# ---------------------------------------------------------------------------
# 1. every red-team case is NOT-supported
# ---------------------------------------------------------------------------


def test_red_team_set_all_labeled_unsupported() -> None:
    """W21/D4 hard rule. Any pair whose ground truth is 'supported'
    is a category error — the red-team measures escapes, not
    correctness on positives."""
    cases = build_adversarial_cases()
    # ≥30 pairs (spec said "~30-40").
    assert len(cases) >= 30
    # Every expected_verdict ∈ {partial, insufficient, contradicted}.
    valid = {"partial", "insufficient", "contradicted"}
    for c in cases:
        assert c.expected_verdict in valid, (
            f"{c.id}: ground truth must not be 'supported'; "
            f"got {c.expected_verdict!r}"
        )
    # AdversarialCase __post_init__ rejects "supported" too — confirm.
    with pytest.raises(ValueError):
        AdversarialCase(
            id="bad", exploit_type=ExploitType.MAGNITUDE_MISMATCH.value,
            claim="x", evidence="y",
            expected_verdict="supported",
            rationale="should reject",
        )


# ---------------------------------------------------------------------------
# 2. every exploit type covered
# ---------------------------------------------------------------------------


def test_red_team_covers_all_exploit_types() -> None:
    """Every category from the spec must appear at least twice so
    the per-exploit catch rate has meaningful denominators."""
    cases = build_adversarial_cases()
    by_type: dict[str, int] = {}
    for c in cases:
        by_type[c.exploit_type] = by_type.get(c.exploit_type, 0) + 1
    expected_types = {t.value for t in ExploitType}
    assert set(by_type.keys()) == expected_types, (
        f"missing types: {expected_types - by_type.keys()}; "
        f"extras: {set(by_type.keys()) - expected_types}"
    )
    for exploit_type, n in by_type.items():
        assert n >= 2, (
            f"{exploit_type}: only {n} cases; spec asks for ≥2 per type"
        )
    # Each exploit type has a prescribed mitigation in the library.
    for exploit_type in expected_types:
        assert exploit_type in EXPLOIT_MITIGATIONS, (
            f"{exploit_type}: missing mitigation entry"
        )


# ---------------------------------------------------------------------------
# 3. catch rate is computed
# ---------------------------------------------------------------------------


class _PerfectVerifier:
    """Stub that ALWAYS reports unsupported so every adversarial
    pair is caught. Catch rate must be 100%."""

    name = "perfect_stub"

    def score(self, claim: str, evidence: str) -> RawScores:
        return RawScores(
            llm_verdict="unsupported",
            deberta_label="neutral",
            deberta_confidence=0.4,
            deberta_softmax=(0.2, 0.3, 0.5),
            lexical_numeric_score=1.0,
            lexical_entity_score=1.0,
        )


class _NaiveVerifier:
    """Stub that ALWAYS reports supported_high so every adversarial
    pair escapes (until the numeric probe runs)."""

    name = "naive_stub"

    def score(self, claim: str, evidence: str) -> RawScores:
        return RawScores(
            llm_verdict="supported",
            deberta_label="entailment",
            deberta_confidence=0.9,
            deberta_softmax=(0.02, 0.92, 0.06),
            lexical_numeric_score=1.0,
            lexical_entity_score=1.0,
        )


def test_catch_rate_computed() -> None:
    results = run_red_team(verifier=_PerfectVerifier())
    summary = triage(results)
    assert summary["total"] == len(build_adversarial_cases())
    assert summary["catch_rate"] == pytest.approx(1.0)
    assert summary["escapes"] == 0
    assert summary["caught"] == summary["total"]


# ---------------------------------------------------------------------------
# 4. escapes are listed with their exploit type
# ---------------------------------------------------------------------------


def test_escapes_listed_with_exploit_type() -> None:
    """A naive verifier without the numeric probe ESCAPES on every
    case. Each listed escape carries its exploit type + mitigation."""
    results = run_red_team(
        verifier=_NaiveVerifier(),
        apply_numeric_probe=False,
    )
    summary = triage(results)
    assert summary["escapes"] == summary["total"]
    assert len(summary["escape_details"]) == summary["total"]
    for e in summary["escape_details"]:
        # Required fields on every escape row.
        assert e["exploit_type"] in {t.value for t in ExploitType}
        assert e["prescribed_mitigation"]
        # The pre-probe verdict is what the verifier said — must
        # show up as a "supported" verdict for these escapes.
        assert e["pre_probe_verdict"] in {
            "supported_high", "supported_low",
        }


# ---------------------------------------------------------------------------
# 5. numeric-consistency probe catches a fabricated figure
# ---------------------------------------------------------------------------


def test_numeric_consistency_catches_fabricated_figure() -> None:
    """Direct unit test on the probe + integration test via the runner.

    The probe is a hard veto on a supported verdict when the claim
    contains a numeric the evidence doesn't carry. Never weakens
    "supported" by lowering thresholds — it adds a targeted veto."""

    # --- unit ---
    # A supported verdict with a fabricated 247bps claim → probe
    # vetoes to "weak".
    probe = numeric_consistency_check(
        ensemble_verdict="supported_high",
        claim="Gross margin improved by exactly 247 basis points.",
        evidence=(
            "Gross margin expanded materially in FY2023 driven by the "
            "pricing programme and lower input costs."
        ),
    )
    assert probe.triggered is True
    assert probe.final_verdict == "weak"
    assert any("247" in m for m in probe.missing_numbers), (
        f"expected 247 in missing list; got {probe.missing_numbers}"
    )

    # A supported verdict where every claim numeric IS in the
    # evidence → probe does NOT fire.
    probe_clean = numeric_consistency_check(
        ensemble_verdict="supported_high",
        claim="Revenue grew 12% in FY2023.",
        evidence="Revenue grew 12% in FY2023 to £50.4m, up from £45.0m.",
    )
    assert probe_clean.triggered is False
    assert probe_clean.final_verdict == "supported_high"

    # Non-supported verdicts are NEVER touched by the probe — even
    # if numerics drift, an "unsupported" / "contradicted" verdict
    # passes through.
    for non_sup in ("weak", "unsupported", "contradicted"):
        probe_off = numeric_consistency_check(
            ensemble_verdict=non_sup,
            claim="Margin grew 247bps.",
            evidence="Margin expansion noted, no specific number.",
        )
        assert probe_off.triggered is False
        assert probe_off.final_verdict == non_sup

    # --- integration via the runner ---
    # The "naive verifier" returns supported_high for everything.
    # WITH the probe, every fabricated-specific case (which by
    # construction has a number absent from evidence) gets caught.
    results_with_probe = run_red_team(
        verifier=_NaiveVerifier(),
        apply_numeric_probe=True,
    )
    fabricated_results = [
        r for r in results_with_probe
        if r.exploit_type == ExploitType.FABRICATED_SPECIFIC.value
    ]
    # The probe must catch the fabricated-specific cases that
    # carry a numeric in the claim. Allow one or two non-numeric
    # fabricated specifics to escape (e.g. a fabricated date).
    fabricated_caught_by_probe = [
        r for r in fabricated_results if r.probe_triggered and r.caught
    ]
    assert len(fabricated_caught_by_probe) >= 4, (
        f"numeric probe caught only "
        f"{len(fabricated_caught_by_probe)} fabricated-specific cases"
    )


# ---------------------------------------------------------------------------
# 6. per-exploit breakdown
# ---------------------------------------------------------------------------


def test_per_exploit_breakdown() -> None:
    """The triage report has a dense per-exploit-type panel where
    every exploit category appears, even if it's at 0 escapes."""
    results = run_red_team(verifier=_PerfectVerifier())
    summary = triage(results)
    breakdown = summary["per_exploit_type"]
    assert set(breakdown.keys()) == {t.value for t in ExploitType}
    for exploit_type, bucket in breakdown.items():
        # Required keys.
        assert {"total", "caught", "escapes", "catch_rate"} <= bucket.keys()
        # PerfectVerifier catches everything.
        assert bucket["catch_rate"] == pytest.approx(1.0)
        assert bucket["escapes"] == []
        assert bucket["caught"] == bucket["total"]


# ---------------------------------------------------------------------------
# Smoke: write_red_team_report end-to-end + numeric-probe contribution
# ---------------------------------------------------------------------------


def test_write_red_team_report_round_trip(tmp_path: Path) -> None:
    """End-to-end: writer dumps escapes.json with the documented
    shape + the probe-contribution panel when the probe is on."""
    out = tmp_path / "escapes.json"
    # Force a deterministic verifier so the report shape is
    # reproducible across CI runs.
    report = write_red_team_report(
        out_path=out,
        verifier=_NaiveVerifier(),
        config=default_threshold_config(),
        apply_numeric_probe=True,
    )
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["numeric_probe_enabled"] is True
    assert "config_used" in loaded
    assert "summary" in loaded
    assert "probe_contribution" in loaded["summary"]
    pc = loaded["summary"]["probe_contribution"]
    # Naive verifier escapes every case without the probe; the
    # probe catches the fabricated-numeric ones → contribution > 0.
    assert pc["additional_catches_from_probe"] >= 4
    assert pc["catch_rate_with_probe"] > pc["catch_rate_without_probe"]
