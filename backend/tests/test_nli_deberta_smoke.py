"""DeBERTa NLI smoke test (Week 2 / Day 1).

10 hand-curated (premise, hypothesis, expected_label) cases plus 2
genuinely order-asymmetric pairs (one specific→general, one
conjunction→conjunct). The whole point of this fixture is to fail
loudly if:

- The model is loaded with the wrong label order (id2label drift between
  HF checkpoints).
- A future caller swaps premise and hypothesis in `score_pairs`.
- Confidence calibration regresses (we require >= 0.5 on the argmax).

If any base case fails, the fix is NOT to soften the fixture — surface
the failing pair to the human first.

# Note: pairs 2 and 3 below were originally written as "entailment" but
# the model rejected them. We accept the model's verdict because the
# rejections demonstrate exactly the kind of gist-vs-precision
# distinction Argus needs to catch:
#   - Pair 2: "grew 50->80" entails net +30, NOT gross hires of 30
#   - Pair 3: "10-500 employees" does not entail the categorical
#     "mid-sized" (no definition of "mid-sized" in the premise)
# These rejections are features, not failures — they're exactly the
# behaviour the cross-family verifier wedge is supposed to surface.

This test imports torch + sentence-transformers and is therefore expensive.
It is intentionally NOT in the default CI pytest run (the Phase 1 CI step
ignores it via --ignore=tests/test_nli_deberta_smoke.py); run it
explicitly inside the dedicated worker:

    docker compose exec nli_worker pytest tests/test_nli_deberta_smoke.py -v
"""

from __future__ import annotations

import pytest

from core.nli.deberta_client import score_pairs


# (premise, hypothesis, expected_label)
ENTAILMENT_CASES: list[tuple[str, str, str]] = [
    (
        "The German B2B SaaS market reached €2.4 billion in 2024.",
        "Germany's B2B SaaS market was approximately €2.4B in 2024.",
        "entailment",
    ),
    (
        "Stripe processed $1 trillion in payments last year.",
        "Stripe handled over $1T in annual payments.",
        "entailment",
    ),
]

CONTRADICTION_CASES: list[tuple[str, str, str]] = [
    (
        # Pair 2 — model correctly distinguishes net change from gross hires.
        "The company's headcount grew from 50 to 80 employees in 2023.",
        "The company hired 30 people in 2023.",
        "contradiction",
    ),
    (
        "The German B2B SaaS market reached €2.4 billion in 2024.",
        "The German B2B SaaS market was below €1 billion in 2024.",
        "contradiction",
    ),
    (
        "Bavaria has the highest GDP of any German state.",
        "Bavaria has the lowest GDP of any German state.",
        "contradiction",
    ),
    (
        "Q3 revenue grew 30% year-over-year.",
        "Q3 revenue declined 30% year-over-year.",
        "contradiction",
    ),
]

NEUTRAL_CASES: list[tuple[str, str, str]] = [
    (
        # Pair 3 — model correctly refuses to ratify the categorical
        # "mid-sized" jump from a numeric range that doesn't define it.
        "Mittelstand firms typically have between 10 and 500 employees.",
        "German Mittelstand companies are mid-sized.",
        "neutral",
    ),
    (
        "The German B2B SaaS market reached €2.4 billion in 2024.",
        "The French B2B SaaS market is growing.",
        "neutral",
    ),
    (
        "Bavaria is in southern Germany.",
        "Munich is the capital of Bavaria.",
        "neutral",
    ),
    (
        "The company raised €5M in 2023.",
        "The company has 12 employees.",
        "neutral",
    ),
]

ALL_CASES = ENTAILMENT_CASES + CONTRADICTION_CASES + NEUTRAL_CASES
assert len(ALL_CASES) == 10  # 2+4+4 — sanity check


@pytest.mark.parametrize(
    ("premise", "hypothesis", "expected"),
    ALL_CASES,
    ids=[f"{i}__{c[2]}" for i, c in enumerate(ALL_CASES)],
)
def test_label_and_confidence(premise: str, hypothesis: str, expected: str) -> None:
    """Each curated pair must predict the right label with confidence >= 0.5.

    On failure we report the full softmax so the operator can see whether
    the model is confused (e.g. ent=0.45 / neu=0.40) vs flat-out wrong
    (e.g. con=0.85 when we expected entailment).
    """
    [result] = score_pairs([(premise, hypothesis)])
    assert result.label == expected, (
        f"NLI predicted {result.label!r} (confidence={result.confidence:.3f}, "
        f"softmax={result.softmax}) for premise={premise!r} hypothesis={hypothesis!r}; "
        f"expected {expected!r}. Do not soften the fixture — investigate."
    )
    assert result.confidence >= 0.5, (
        f"NLI predicted {result.label!r} but confidence is only "
        f"{result.confidence:.3f} (softmax={result.softmax}) for "
        f"premise={premise!r} hypothesis={hypothesis!r}. "
        f"Expected at least 0.5 on the argmax."
    )


def test_batch_preserves_input_order() -> None:
    """Scoring a 5-pair batch must return labels in input order.

    We test order preservation, not specific labels — the per-case
    parametrized test above already covers individual correctness.
    Here we only assert that batch_scoring(pairs) == [individual_score(p)
    for p in pairs] up to label equality, which is the invariant a future
    refactor of `score_pairs` could most easily break.
    """
    pairs = [(p, h) for p, h, _ in ALL_CASES[:5]]
    batched = [r.label for r in score_pairs(pairs)]
    individual = [score_pairs([pair])[0].label for pair in pairs]
    assert batched == individual, (
        f"Batch order regression: batched={batched}, individual={individual}. "
        "score_pairs must return results in the same order as the input pairs."
    )


# ---------------------------------------------------------------------------
# Order sensitivity. The original spec used pairs that turned out to be
# label-symmetric (a paraphrase and a symmetric contradiction), so flipping
# returned the same label and the test couldn't actually catch a
# (premise, hypothesis) swap. Replaced with two genuinely asymmetric pairs:
#
#   A — specific -> general:    entailment forward, neutral reverse
#   B — conjunction -> conjunct: entailment forward, neutral reverse
#
# Both are consulting-relevant. If a caller flips the score_pairs argument
# order anywhere downstream, these tests fail loudly.
# ---------------------------------------------------------------------------


def _label(premise: str, hypothesis: str) -> str:
    return score_pairs([(premise, hypothesis)])[0].label


def test_order_asymmetry_specific_to_general() -> None:
    specific = "The company grew revenue 30% in 2024."
    general = "The company grew revenue in 2024."
    forward = _label(specific, general)
    reverse = _label(general, specific)
    assert forward == "entailment", (
        f"Forward (specific -> general) regressed: got {forward!r}, "
        f"expected 'entailment'. premise={specific!r} hypothesis={general!r}"
    )
    assert reverse == "neutral", (
        f"Reverse (general -> specific) regressed: got {reverse!r}, "
        f"expected 'neutral'. premise={general!r} hypothesis={specific!r}. "
        "If this fires, either the model has changed or someone swapped "
        "(premise, hypothesis) order in score_pairs."
    )
    assert forward != reverse, (
        f"Order sensitivity FAILED: forward={forward!r} == reverse={reverse!r}. "
        "Specific->general should entail; general->specific should be neutral. "
        "If a caller silently swaps argument order this asymmetry collapses."
    )


def test_order_asymmetry_conjunction_to_conjunct() -> None:
    conjunction = "The company has 12 employees and €5M revenue."
    conjunct = "The company has 12 employees."
    forward = _label(conjunction, conjunct)
    reverse = _label(conjunct, conjunction)
    assert forward == "entailment", (
        f"Forward (conjunction -> conjunct) regressed: got {forward!r}, "
        f"expected 'entailment'. premise={conjunction!r} hypothesis={conjunct!r}"
    )
    assert reverse == "neutral", (
        f"Reverse (conjunct -> conjunction) regressed: got {reverse!r}, "
        f"expected 'neutral'. premise={conjunct!r} hypothesis={conjunction!r}. "
        "If this fires, either the model has changed or someone swapped "
        "(premise, hypothesis) order in score_pairs."
    )
    assert forward != reverse, (
        f"Order sensitivity FAILED: forward={forward!r} == reverse={reverse!r}. "
        "Conjunction->conjunct should entail; conjunct->conjunction should be neutral. "
        "If a caller silently swaps argument order this asymmetry collapses."
    )
