"""Golden-set fixtures for the verifier accuracy bench — Phase 5 / Week 21.

This package holds the ground-truth claim–evidence pairs used to
measure verifier accuracy + tune NLI thresholds. Two sources of
truth:

  - ``build_synthetic.py`` — deterministic, hand-constructed pairs
    where the correct label is known by construction (we wrote the
    evidence to support / contradict / partially-cover / not address
    the claim). No LLM involvement.
  - ``real_runs/*.yaml`` — held-out claim–evidence pairs extracted
    from real engagements and labelled by a human (the tooling is
    in ``tools/label_claims.py``).

:mod:`loader` merges the two streams into one :class:`GoldenSet`
with a stable iteration order so the Day 2-3 tuning runs and the
Day 4 regression suite are reproducible.

Hard rule (from the W21/D1 spec): LLMs do not label ground truth.
Synthetic labels are known by construction; real labels come from
a human reviewer. Anything else is circular.
"""

from .types import (
    Category,
    GoldenEntry,
    GoldenSet,
    Verdict,
)

__all__ = ["Category", "GoldenEntry", "GoldenSet", "Verdict"]
