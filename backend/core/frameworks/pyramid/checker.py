"""Combined Pyramid checker entry point — W8/D1.

Runs the structural pre-check (deterministic) and the LLM judge
(gpt-4o-mini) and returns a single :class:`PyramidCheckResult`.

The orchestrator calls this post-writer, after schema validation and
``apply_mode_checks``, before the session flips to ``deliverable_ready``.
Findings are advisory — even an ``error`` severity does NOT block
the memo from being delivered. Hard rule from the W8/D1 spec.

Cost target: ≤ $0.05 average per engagement. The LLM call uses the
``entailment`` task config (gpt-4o-mini, ≤2K input, ≤2K output), which
typically lands at ~$0.001-0.003 per call. Structural pre-check is
free.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .judge import llm_pyramid_judge
from .structural import structural_pyramid_check
from .types import PyramidCheckResult, PyramidFinding


async def run_pyramid_check(
    payload: Any,
    *,
    session_id: str | None = None,
    skip_llm: bool = False,
    cost_usd: float = 0.0,
) -> PyramidCheckResult:
    """Combined structural + prose-level pyramid check.

    Parameters
    ----------
    payload:
        Writer payload (``WriterReportBase`` or any subclass). The
        checker treats subclasses generically — it only reads the base
        fields (recommendation, key_reasons, summary, risks,
        executive_insights, recommendation_claim_ids).
    session_id:
        Threaded into the LLM call for cost-tracking continuity.
    skip_llm:
        Test escape hatch — when True, only the structural pre-check
        runs. Used by unit tests that don't want to mock the LLM
        layer.
    cost_usd:
        Caller can pre-seed this when the LLM cost is already known
        (e.g. from a wrapper that records the call separately). The
        judge itself does not yet bubble cost back through the
        ``llm_call_for_task`` helper — the cost-tracking row in
        ``llm_calls`` carries the truth.

    Returns
    -------
    PyramidCheckResult: with ``passed`` true iff no ``error`` findings.
    """
    structural_findings: list[PyramidFinding] = structural_pyramid_check(payload)

    prose_findings: list[PyramidFinding] = []
    model_used: str | None = None
    if not skip_llm:
        prose_findings, model_used = await llm_pyramid_judge(payload, session_id=session_id)

    all_findings = structural_findings + prose_findings
    passed = not any(f.severity == "error" for f in all_findings)

    return PyramidCheckResult(
        passed=passed,
        findings=all_findings,
        checked_at=datetime.now(timezone.utc),
        model_used=model_used or None,
        cost_usd=cost_usd,
    )
