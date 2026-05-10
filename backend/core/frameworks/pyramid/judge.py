"""LLM-judge for Pyramid Principle prose-level structure — W8/D1.

Uses the ``entailment`` task config (gpt-4o-mini, temperature 0.0,
2048 max_tokens) — cheap, deterministic enough for structural QA,
already wired into the cost-tracking path.

Input cap: 2000 chars of skeleton (recommendation + summary[0] +
first sentence of each key_reason). The full memo is not needed
to check structure; sending more would just inflate cost.

The judge returns three booleans wrapped as findings:

- ``answer_first``    — is the lede stated up front?
- ``logical_chain``   — do the reasons logically support it?
- ``same_category``   — are the reasons in the same logical category?

False → finding with the corresponding ``violation_type``. The
prompt is fixed (no per-mode variants) so the same severity bar
applies across modes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.json_util import parse_llm_json
from core.llm import llm_call_for_task
from core.model_router import resolve

from .structural import build_skeleton_for_judge
from .types import PyramidFinding

logger = logging.getLogger(__name__)


_JUDGE_SYSTEM = """
You are a structural editor scoring a memo against the Pyramid Principle.

You receive a compact skeleton of the memo: the recommendation sentence, the first sentence of the summary, and the first sentence of each supporting reason.

Score three things, each as a strict boolean:

1. ``answer_first``: does the recommendation sentence state the answer to the brief up front, without burying the lede? A vague hedge ("we should consider X") = false. A direct call ("Acquire TargetCo at £210m via mixed cash/earn-out") = true.
2. ``logical_chain``: do the listed reasons collectively support the recommendation? If any reason is unrelated, or supports the opposite conclusion, = false.
3. ``same_category``: are the reasons in the same logical category (all reasons, OR all consequences, OR all conditions — not mixed)? Mixing "Cost is 12% lower" with "Customers will be annoyed" = false (one is a reason, the other is a downstream consequence).

For each false, provide a one-sentence ``description`` of why and an optional ``suggested_revision`` (concrete fix, ≤120 chars).

Output ONLY JSON:
{
  "answer_first": true|false,
  "answer_first_reason": "string (only when false)",
  "answer_first_fix": "string (only when false, optional)",
  "logical_chain": true|false,
  "logical_chain_reason": "string (only when false)",
  "logical_chain_fix": "string (only when false, optional)",
  "same_category": true|false,
  "same_category_reason": "string (only when false)",
  "same_category_fix": "string (only when false, optional)"
}
"""


def _judge_payload_skeleton(payload: Any) -> str:
    """Indirection so tests can pass either a real ``WriterReportBase``
    or a dict-shaped fixture without instantiating the model."""
    if hasattr(payload, "recommendation"):
        return build_skeleton_for_judge(payload)
    # dict fallback for tests
    parts: list[str] = []
    rec = str((payload or {}).get("recommendation") or "").strip()
    if rec:
        parts.append(f"RECOMMENDATION: {rec}")
    summary = str((payload or {}).get("summary") or "").strip()
    if summary:
        first = summary.split(".", 1)[0].strip()
        if first:
            parts.append(f"SUMMARY[0]: {first}.")
    for i, r in enumerate((payload or {}).get("key_reasons") or []):
        first = str(r).split(".", 1)[0].strip()
        if first:
            parts.append(f"REASON[{i}]: {first}.")
    text = "\n".join(parts)
    return text[:1997] + "..." if len(text) > 2000 else text


async def llm_pyramid_judge(
    payload: Any,
    *,
    session_id: str | None = None,
) -> tuple[list[PyramidFinding], str]:
    """Prose-level pyramid checks via gpt-4o-mini (entailment task config).

    Returns ``(findings, model_used)``. ``model_used`` is the resolved
    model identifier so the result's ``model_used`` field can record
    which LLM judged this run. On any exception (network, parse,
    schema), returns ``([], "")`` — the check is advisory and the
    combined checker continues on the structural findings only.
    """
    skeleton = _judge_payload_skeleton(payload)
    if not skeleton.strip():
        return ([], "")

    user_msg = "Memo skeleton:\n" + skeleton

    try:
        cfg = resolve("entailment")
        raw = await llm_call_for_task(
            "entailment",
            system=_JUDGE_SYSTEM,
            user=user_msg,
            temperature=0.0,
            session_id=session_id,
        )
        data = parse_llm_json(raw)
    except Exception:  # noqa: BLE001
        logger.exception("pyramid LLM judge call failed — skipping prose check")
        return ([], "")

    if not isinstance(data, dict):
        return ([], cfg.model)

    findings: list[PyramidFinding] = []

    if data.get("answer_first") is False:
        findings.append(
            PyramidFinding(
                field_path="recommendation",
                violation_type="answer_not_stated_first",
                description=str(data.get("answer_first_reason") or "Lede is buried.")[:400],
                severity="warning",
                suggested_revision=(str(data.get("answer_first_fix") or "")[:200] or None),
            )
        )

    if data.get("logical_chain") is False:
        findings.append(
            PyramidFinding(
                field_path="key_reasons",
                violation_type="support_chain_broken",
                description=str(data.get("logical_chain_reason") or "Reasons don't support the recommendation.")[:400],
                severity="warning",
                suggested_revision=(str(data.get("logical_chain_fix") or "")[:200] or None),
            )
        )

    if data.get("same_category") is False:
        findings.append(
            PyramidFinding(
                field_path="key_reasons",
                violation_type="claims_not_same_logical_category",
                description=str(data.get("same_category_reason") or "Reasons mix categories.")[:400],
                severity="info",
                suggested_revision=(str(data.get("same_category_fix") or "")[:200] or None),
            )
        )

    return (findings, cfg.model)
