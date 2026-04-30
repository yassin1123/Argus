"""NLI citation verifier — does the cited chunk actually entail the claim?

Per the engineering brief: *"citation hallucination is the failure mode that
kills the product."* This is the moat.

Implementation:
  - For each (claim, chunk) pair in the StructuredAnswer, ask a fast LLM judge
    (gpt-4o-mini) to classify entailment/neutral/contradiction with structured
    JSON output via Instructor.
  - Aggregate per-claim worst-case → adjust the claim's `confidence`:
      contradiction anywhere  → confidence = "contested"
      at least one entailment → confidence retained or upgraded
      all neutral             → confidence = "medium"

Why LLM judge instead of a hosted NLI checkpoint:
  HuggingFace's free Inference API no longer routes the classic NLI models
  (DeBERTa-v3-MNLI etc.) for text-pair classification — they're tagged as
  zero-shot which doesn't fit fact verification. A v1 deployment can swap in
  a dedicated Inference Endpoint (paid, ~$0.06/hr) or a sentence-transformers
  cross-encoder loaded into the worker. Both are config swaps; the verifier
  interface stays the same.

Falls back to "skipped" gracefully when OPENAI_API_KEY is missing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

import instructor
import litellm
from pydantic import BaseModel, Field

from models.structured_answer import (
    GroundedClaim,
    NliResult,
    StructuredAnswer,
)

logger = logging.getLogger(__name__)

NLI_JUDGE_MODEL = os.getenv("ARGUS_NLI_JUDGE_MODEL", "gpt-4o-mini")

# Cap to keep judge calls cheap.
_MAX_PREMISE_CHARS = 1500
_MAX_HYPOTHESIS_CHARS = 600
_MAX_PARALLEL = 8
_TIMEOUT = 25.0


JUDGE_SYSTEM = """You are an NLI verifier inside a consulting AI workbench.
You receive a PREMISE (a passage from a source document) and a HYPOTHESIS
(a claim made in the report).

Classify the relationship into exactly one label:

  - entailment   : the premise unambiguously supports the hypothesis
  - contradiction: the premise says something that contradicts the hypothesis
  - neutral      : the premise is unrelated, or doesn't say enough to verify

Return a JSON object with `label` and `score` (0.0-1.0 confidence in your label).
Be strict — if the premise is only loosely related, label `neutral`, not `entailment`.
"""


class _JudgeOutput(BaseModel):
    label: Literal["entailment", "contradiction", "neutral"] = Field(
        ..., description="The NLI verdict."
    )
    score: float = Field(0.7, ge=0.0, le=1.0, description="Your confidence, 0-1.")


def _has_openai_key() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


async def _classify_pair(client, *, premise: str, hypothesis: str) -> tuple[str, float]:
    p = (premise or "").strip()[:_MAX_PREMISE_CHARS]
    h = (hypothesis or "").strip()[:_MAX_HYPOTHESIS_CHARS]
    if not p or not h:
        return "skipped", 0.0
    try:
        result: _JudgeOutput = await client.chat.completions.create(
            model=NLI_JUDGE_MODEL,
            response_model=_JudgeOutput,
            timeout=_TIMEOUT,
            max_retries=1,
            temperature=0.0,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {
                    "role": "user",
                    "content": f"PREMISE:\n{p}\n\nHYPOTHESIS:\n{h}",
                },
            ],
        )
        return result.label, float(result.score)
    except Exception as e:  # noqa: BLE001
        logger.warning("NLI judge call failed: %s", e)
        return "skipped", 0.0


def _aggregate_confidence(claim: GroundedClaim) -> str:
    if not claim.nli_results:
        return claim.confidence
    labels = [r.label for r in claim.nli_results]
    if "contradiction" in labels:
        return "contested"
    if "entailment" in labels:
        return "high" if claim.confidence != "contested" else claim.confidence
    if all(l in ("neutral", "skipped") for l in labels):
        # If all non-skipped were neutral, that's "medium". If all skipped, leave as-is.
        if any(l == "neutral" for l in labels):
            return "medium"
    return claim.confidence


async def verify_structured_answer(
    answer: StructuredAnswer,
    chunks_by_id: dict[str, dict],
    *,
    on_progress=None,
) -> StructuredAnswer:
    """Run NLI per (claim, chunk) pair; mutate `answer` with results + confidences.

    `on_progress(answer)` is awaited after each claim's NLI pairs complete so the
    caller can persist partial state. The frontend's poll loop sees citations
    resolve from "verifying..." to their final state one claim at a time —
    instead of waiting for ALL pairs to finish.
    """
    answer.verification_state = "verifying"
    if on_progress:
        try:
            await on_progress(answer)
        except Exception as e:  # noqa: BLE001
            logger.warning("on_progress (initial) failed: %s", e)

    if not _has_openai_key():
        if "NLI verification skipped (no OPENAI_API_KEY)." not in answer.validation_notes:
            answer.validation_notes.append("NLI verification skipped (no OPENAI_API_KEY).")
        answer.verification_state = "complete"
        if on_progress:
            await on_progress(answer)
        return answer

    # Group pairs by claim so we update one claim at a time.
    claim_groups: list[tuple[GroundedClaim, list[tuple[str, str, str]]]] = []
    for section in answer.sections:
        for claim in section.claims:
            pairs: list[tuple[str, str, str]] = []
            for cid in claim.chunk_ids:
                chunk = chunks_by_id.get(cid)
                if chunk:
                    pairs.append((cid, claim.text, chunk.get("content", "")))
            if pairs:
                claim_groups.append((claim, pairs))

    if not claim_groups:
        answer.validation_notes.append("NLI verifier: no (claim, chunk) pairs to check.")
        answer.verification_state = "complete"
        if on_progress:
            await on_progress(answer)
        return answer

    client = instructor.from_litellm(litellm.acompletion)
    sem = asyncio.Semaphore(_MAX_PARALLEL)

    async def _one(cid: str, claim_text: str, premise: str):
        async with sem:
            label, score = await _classify_pair(client, premise=premise, hypothesis=claim_text)
        return cid, label, score

    contradicted = 0
    weakened = 0

    for claim, pairs in claim_groups:
        results = await asyncio.gather(*(_one(*p) for p in pairs), return_exceptions=False)
        for cid, label, score in results:
            claim.nli_results.append(NliResult(chunk_id=cid, label=label, score=float(score)))  # type: ignore[arg-type]

        prior = claim.confidence
        new_conf = _aggregate_confidence(claim)
        if new_conf == "contested" and prior != "contested":
            contradicted += 1
            claim.notes = (
                (claim.notes + " " if claim.notes else "")
                + "[NLI: cited chunk contradicts the claim — review.]"
            )
        elif new_conf == "medium" and prior == "high":
            weakened += 1
        claim.confidence = new_conf  # type: ignore[assignment]

        if on_progress:
            try:
                await on_progress(answer)
            except Exception as e:  # noqa: BLE001
                logger.warning("on_progress callback failed (continuing): %s", e)

    if contradicted:
        answer.validation_notes.append(
            f"NLI verifier flagged {contradicted} claim(s) where a cited chunk contradicts the text."
        )
    if weakened:
        answer.validation_notes.append(
            f"NLI verifier downgraded {weakened} high-confidence claim(s) to medium (no entailment)."
        )
    if not contradicted and not weakened:
        answer.validation_notes.append("NLI verifier: all citations entail their claims.")

    answer.verification_state = "complete"
    if on_progress:
        await on_progress(answer)
    return answer
