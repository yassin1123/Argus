"""Golden-set data shapes — Phase 5 / Week 21 / Day 1.

Ground-truth labels use four classes:

  - ``supported``     evidence directly establishes the claim
  - ``partial``       evidence supports part of the claim but not
                      the whole (e.g. direction without magnitude,
                      one-of-several attributions)
  - ``insufficient``  evidence is on the right topic but does not
                      address the claim's specific assertion
  - ``contradicted``  evidence states the opposite

These map onto the 5-class ensemble verdict the verifier produces:

  ensemble verdict (5-class)      ground truth (4-class)
  ----------------------------    -----------------------
  supported_high / supported_low  supported
  weak                            partial
  unsupported                     insufficient
  contradicted                    contradicted

The Day 2 evaluator collapses the verifier's 5-class output into
the 4-class ground-truth space before scoring agreement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    """Four-class ground-truth label."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    CONTRADICTED = "contradicted"


class Category(str, Enum):
    """Claim-shape category. The Day 4 regression breaks accuracy
    down by category to see where the verifier weakest — numeric
    claims will reveal lexical-overlap calibration; causal claims
    reveal the LLM judge's interpretation of "supports"; forecasts
    reveal whether the verifier confuses "evidence says X happened"
    with "evidence supports the prediction Y will happen"."""

    NUMERIC = "numeric_claim"
    CAUSAL = "causal_claim"
    COMPARATIVE = "comparative"
    ATTRIBUTION = "attribution"
    FORECAST = "forecast"


# Both enums above are str-subclasses so the YAML/JSON round-trip
# is a plain string — no enum machinery needs to leak into the
# label CLI or the loader.


@dataclass
class GoldenEntry:
    """One labelled (claim, evidence) pair.

    ``evidence_source`` is either ``synthetic`` (constructed in
    :mod:`build_synthetic`) or ``real_run`` (extracted from a
    historical engagement + labelled by a human). The Day 2-3
    tuning treats both equally for scoring; Day 4 regression
    breaks accuracy down by source to spot synthetic over-fitting.
    """

    id: str
    claim: str
    evidence: str
    evidence_source: str        # "synthetic" | "real_run"
    ground_truth: str           # one of :class:`Verdict` values
    label_rationale: str
    category: str               # one of :class:`Category` values
    adversarial: bool = False
    # When evidence_source == "real_run", we record where the row
    # came from so a labeller can review the original engagement
    # if a label is later disputed.
    real_run_session_id: str | None = None
    real_run_claim_id: str | None = None
    # Optional metadata bag — pair-level notes a labeller may add
    # (e.g. "magnitude mismatched 12% vs 14%"). Never carries free
    # prose from the engagement; this is the labeller's own short
    # rationale text.
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate enums up-front so a bad fixture row fails loud.
        if self.ground_truth not in {v.value for v in Verdict}:
            raise ValueError(
                f"GoldenEntry {self.id}: bad ground_truth {self.ground_truth!r}"
            )
        if self.category not in {c.value for c in Category}:
            raise ValueError(
                f"GoldenEntry {self.id}: bad category {self.category!r}"
            )
        if self.evidence_source not in {"synthetic", "real_run"}:
            raise ValueError(
                f"GoldenEntry {self.id}: bad evidence_source "
                f"{self.evidence_source!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoldenSet:
    """A loaded golden set — synthetic backbone + any real-run
    labelled batch. Indexed by ``id`` (which is unique by
    construction)."""

    entries: list[GoldenEntry] = field(default_factory=list)

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def by_verdict(self) -> dict[str, list[GoldenEntry]]:
        out: dict[str, list[GoldenEntry]] = {v.value: [] for v in Verdict}
        for e in self.entries:
            out[e.ground_truth].append(e)
        return out

    def by_category(self) -> dict[str, list[GoldenEntry]]:
        out: dict[str, list[GoldenEntry]] = {c.value: [] for c in Category}
        for e in self.entries:
            out[e.category].append(e)
        return out

    def by_source(self) -> dict[str, list[GoldenEntry]]:
        out: dict[str, list[GoldenEntry]] = {
            "synthetic": [], "real_run": [],
        }
        for e in self.entries:
            out[e.evidence_source].append(e)
        return out


# Mapping the 5-class ensemble verdict → 4-class ground truth, so
# the Day 2 evaluator can collapse before scoring. Public so the
# tests + the evaluator share one source of truth.
VERDICT_COLLAPSE_5_TO_4: dict[str, str] = {
    "supported_high": Verdict.SUPPORTED.value,
    "supported_low": Verdict.SUPPORTED.value,
    "weak": Verdict.PARTIAL.value,
    "unsupported": Verdict.INSUFFICIENT.value,
    "contradicted": Verdict.CONTRADICTED.value,
}


def collapse_verdict(ensemble_verdict: str) -> str:
    """Map a 5-class ensemble verdict onto the 4-class ground-truth
    label space. Unknown verdicts collapse to ``partial`` — we
    refuse to either reward (supported) or penalise (insufficient)
    an unrecognised label."""
    return VERDICT_COLLAPSE_5_TO_4.get(
        (ensemble_verdict or "").strip().lower(),
        Verdict.PARTIAL.value,
    )


__all__ = [
    "Category",
    "GoldenEntry",
    "GoldenSet",
    "VERDICT_COLLAPSE_5_TO_4",
    "Verdict",
    "collapse_verdict",
]
