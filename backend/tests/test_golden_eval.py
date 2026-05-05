"""Golden-case eval tests — guard against citation faithfulness regression.

These tests load a fixture StructuredAnswer (so they don't burn LLM tokens on
every CI run) and score it against the golden case. Real end-to-end runs are
done out-of-band by `tools/run_full_eval.py`.
"""

from __future__ import annotations

from models.structured_answer import (
    GroundedClaim,
    NliResult,
    StructuredAnswer,
    StructuredSection,
)

from eval.harness import GoldenCase, score_against_case


def _make_passing_answer() -> StructuredAnswer:
    """Build a StructuredAnswer that should pass the germany_vs_france case."""
    return StructuredAnswer(
        tldr="Run a 6-month Mittelstand pilot in Germany before committing to France.",
        sections=[
            StructuredSection(
                heading="Market sizing",
                text="Germany's market is the largest in continental Europe.",
                claims=[
                    GroundedClaim(
                        text="Germany's B2B SaaS market is roughly 1.6x France's.",
                        chunk_ids=["c1"],
                        confidence="high",
                        nli_results=[NliResult(chunk_id="c1", label="entailment", score=0.91)],
                    ),
                    GroundedClaim(
                        text="Mittelstand procurement cycles are 7.2 months on average.",
                        chunk_ids=["c2"],
                        confidence="high",
                        nli_results=[NliResult(chunk_id="c2", label="entailment", score=0.85)],
                    ),
                    GroundedClaim(
                        text="France grows 22% YoY but the public-sector wedge is hard to capture at 12 HC.",
                        chunk_ids=["c3"],
                        confidence="high",
                        nli_results=[NliResult(chunk_id="c3", label="entailment", score=0.82)],
                    ),
                ],
            ),
        ],
        caveats="Pilot success base rates rest on internal pattern data — directional only.",
    )


def _make_failing_answer() -> StructuredAnswer:
    """Forces a banned-phrase failure + low faithfulness."""
    return StructuredAnswer(
        tldr="Pursue a phased approach to leverage synergies across Europe.",
        sections=[
            StructuredSection(
                heading="Strategy",
                text="The market is large.",
                claims=[
                    GroundedClaim(
                        text="The market is large.",
                        chunk_ids=[],
                        confidence="contested",
                        nli_results=[],
                    ),
                ],
            ),
        ],
    )


def test_passing_answer_meets_germany_case() -> None:
    case = GoldenCase.load("germany_vs_france")
    score = score_against_case(_make_passing_answer(), case)
    assert score.passed, f"Expected pass, got failures: {score.failures}"
    assert score.citation_faithfulness == 1.0
    assert score.unsupported_pct == 0.0
    assert score.keyword_hits >= 2  # Germany, Mittelstand
    assert score.banned_phrase_hits == []


def test_failing_answer_is_rejected_for_banned_phrase() -> None:
    case = GoldenCase.load("germany_vs_france")
    score = score_against_case(_make_failing_answer(), case)
    assert not score.passed
    # Both "phased approach" and "leverage synergies" should be flagged.
    assert "banned_phrases_present" in " ".join(score.failures)
    assert "phased approach" in score.banned_phrase_hits


def test_too_few_claims_is_rejected() -> None:
    case = GoldenCase.load("germany_vs_france")
    answer = StructuredAnswer(
        tldr="Run a Mittelstand pilot in Germany.",
        sections=[
            StructuredSection(
                heading="Plan",
                text="Plan.",
                claims=[
                    GroundedClaim(
                        text="One supporting claim.",
                        chunk_ids=["c1"],
                        confidence="high",
                        nli_results=[NliResult(chunk_id="c1", label="entailment", score=0.9)],
                    ),
                ],
            )
        ],
    )
    score = score_against_case(answer, case)
    assert not score.passed
    assert any("too_few_claims" in f for f in score.failures)
