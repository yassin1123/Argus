"""Pyramid Principle finding + result schema — W8/D1.

Two output shapes:

- :class:`PyramidFinding` — one issue the checker surfaced. Both
  structural (deterministic) and LLM-judge findings share the same
  shape so downstream UI / dashboards don't branch on origin.
- :class:`PyramidCheckResult` — the full check output: pass/fail
  rollup + list of findings + cost + which model judged the prose.

``passed`` is ``True`` if no finding has severity ``error``. Warnings
and info entries do not flip the bit — they're advisory, surfaced
in the workspace, and the consultant decides whether to act on them.

The result is persisted to ``session.metadata.pyramid_check_result``
and the finding count is mirrored to ``sessions.pyramid_findings_count``
for cheap dashboard queries (migration 029).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PyramidViolationType = Literal[
    "answer_not_stated_first",            # recommendation prose buries the lede
    "support_chain_broken",                # top reasons not supported by linked claims
    "claims_not_same_logical_category",    # mixing reasons with consequences (advisory)
    "missing_evidence_link",               # claim without claim_id linkage
]


class PyramidFinding(BaseModel):
    """One issue surfaced by the pyramid checker.

    ``field_path`` is a dotted path into the writer payload so the UI
    can deep-link to the offending section (e.g.
    ``"recommendation"``, ``"key_reasons.0"``).
    """

    field_path: str = Field(..., description="Dotted path into the writer payload.")
    violation_type: PyramidViolationType
    description: str = Field(..., description="Human-readable description of the issue.")
    severity: Literal["info", "warning", "error"]
    suggested_revision: str | None = Field(
        None, description="Optional concrete fix; populated by the LLM judge when it has a useful suggestion."
    )

    model_config = {"extra": "ignore"}


class PyramidCheckResult(BaseModel):
    """Full output of a pyramid check pass over a writer payload."""

    passed: bool = Field(..., description="True iff zero error-severity findings (warnings/info OK).")
    findings: list[PyramidFinding] = Field(default_factory=list)
    checked_at: datetime = Field(..., description="UTC timestamp the check was completed.")
    model_used: str | None = Field(
        None,
        description=(
            "Identifier of the LLM judge model when prose-level checks ran. "
            "``None`` when only the structural pre-check fired (e.g. judge "
            "skipped or failed)."
        ),
    )
    cost_usd: float = Field(0.0, ge=0.0, description="Total USD cost of this check pass.")

    model_config = {"extra": "ignore"}

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "info")
