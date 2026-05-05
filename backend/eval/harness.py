"""Argus eval harness — score a StructuredAnswer against a golden case.

Used by the regression suite (`backend/tests/test_golden_eval.py`) to fail the
build when citation faithfulness or recommendation specificity drops below the
case's threshold.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from models.structured_answer import StructuredAnswer

GOLDEN_DIR = Path(__file__).parent / "golden"


@dataclass
class GoldenCase:
    id: str
    prompt: str
    expected_recommendation_keywords: list[str]
    min_supporting_claims: int
    min_citation_faithfulness: float
    max_unsupported_pct: float
    banned_phrases: list[str]
    notes: str = ""

    @classmethod
    def load(cls, name: str) -> "GoldenCase":
        path = GOLDEN_DIR / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            id=data["id"],
            prompt=data["prompt"],
            expected_recommendation_keywords=data.get("expected_recommendation_keywords", []),
            min_supporting_claims=int(data.get("min_supporting_claims", 1)),
            min_citation_faithfulness=float(data.get("min_citation_faithfulness", 0.5)),
            max_unsupported_pct=float(data.get("max_unsupported_pct", 0.5)),
            banned_phrases=data.get("banned_phrases", []),
            notes=data.get("notes", ""),
        )


@dataclass
class EvalScore:
    case_id: str
    total_claims: int
    claims_with_entailment: int
    claims_contested: int
    citation_faithfulness: float
    unsupported_pct: float
    keyword_hits: int
    banned_phrase_hits: list[str]
    passed: bool
    failures: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "total_claims": self.total_claims,
            "claims_with_entailment": self.claims_with_entailment,
            "claims_contested": self.claims_contested,
            "citation_faithfulness": round(self.citation_faithfulness, 3),
            "unsupported_pct": round(self.unsupported_pct, 3),
            "keyword_hits": self.keyword_hits,
            "banned_phrase_hits": self.banned_phrase_hits,
            "passed": self.passed,
            "failures": self.failures,
        }


def score_against_case(answer: StructuredAnswer, case: GoldenCase) -> EvalScore:
    """Score the structured answer. Returns pass/fail + the metrics."""
    failures: list[str] = []

    # 1. Claim metrics
    all_claims = [c for s in answer.sections for c in s.claims]
    total = len(all_claims)
    with_entail = 0
    contested = 0
    for c in all_claims:
        labels = [r.label for r in c.nli_results] if c.nli_results else []
        if "entailment" in labels:
            with_entail += 1
        if c.confidence == "contested" or "contradiction" in labels:
            contested += 1

    faithfulness = (with_entail / total) if total else 0.0
    unsupported_pct = (contested / total) if total else 0.0

    if total < case.min_supporting_claims:
        failures.append(
            f"too_few_claims (got {total}, need ≥{case.min_supporting_claims})"
        )
    # Only enforce faithfulness when NLI actually ran (some claims have results).
    nli_ran = any(c.nli_results for c in all_claims)
    if nli_ran and faithfulness < case.min_citation_faithfulness:
        failures.append(
            f"low_faithfulness ({faithfulness:.2f} < {case.min_citation_faithfulness})"
        )
    if nli_ran and unsupported_pct > case.max_unsupported_pct:
        failures.append(
            f"too_many_unsupported ({unsupported_pct:.2f} > {case.max_unsupported_pct})"
        )

    # 2. Recommendation keyword presence (case-insensitive substring).
    recommendation_text = answer.tldr.lower()
    keyword_hits = sum(
        1 for kw in case.expected_recommendation_keywords if kw.lower() in recommendation_text
    )
    if case.expected_recommendation_keywords and keyword_hits == 0:
        failures.append(
            f"no_expected_keywords (none of {case.expected_recommendation_keywords})"
        )

    # 3. Banned-phrase regression — case-insensitive whole-substring match across ALL prose.
    full_text = " ".join(
        [answer.tldr or ""] + [s.text for s in answer.sections] + [c.text for s in answer.sections for c in s.claims] + [answer.caveats or ""]
    ).lower()
    banned_hits = [
        phrase for phrase in case.banned_phrases if re.search(rf"\b{re.escape(phrase.lower())}\b", full_text)
    ]
    if banned_hits:
        failures.append(f"banned_phrases_present ({banned_hits})")

    return EvalScore(
        case_id=case.id,
        total_claims=total,
        claims_with_entailment=with_entail,
        claims_contested=contested,
        citation_faithfulness=faithfulness,
        unsupported_pct=unsupported_pct,
        keyword_hits=keyword_hits,
        banned_phrase_hits=banned_hits,
        passed=len(failures) == 0,
        failures=failures,
    )
