"""Wire LLM judge + DeBERTa + lexical overlap into one ensemble verdict per
claim_support_row, then return rows enriched with the eight new columns from
``backend/db/migrations/022_ensemble_verdicts.sql``.

This module sits between ``core.claim_support.build_claim_support`` (which
produces legacy rows from the analyst output + LLM verifier output) and
``db.queries.replace_claim_support_rows`` (which persists them). The
enrichment step:

1. Builds the (premise=combined_evidence_quote, hypothesis=claim_text) pair
   per row.
2. Computes the lexical-overlap signal locally — pure regex + spaCy, fast.
3. Dispatches ONE Celery task to the ``nli`` queue (handled by
   nli_worker) carrying all pairs in a single batch — model load is
   amortised once per session, not once per claim.
4. Runs the aggregator (Day 3 truth table) per row to produce
   ``ensemble_verdict`` + ``ensemble_reason``.

If the DeBERTa worker is unreachable / times out we substitute a sentinel
``NLIResult(label="unknown", confidence=0.0)`` and the aggregator's
"unknown DeBERTa label" branch handles it as if neutral. The pipeline does
NOT abort — feature-flag-OFF readers (writer/critic/policy) keep using the
legacy verifier_verdict column anyway.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.nli.aggregator import aggregate
from core.nli.deberta_client import NLIResult
from core.nli.lexical_overlap import score_overlap
from models.evidence import EvidenceObject

logger = logging.getLogger(__name__)

# Time budget for ONE sub-batch DeBERTa call (model load is amortised by
# the worker after the first call; a 5-pair scoring step is sub-second
# once the model is hot, so 60s is plenty even for cold-start on the
# first sub-batch of a session).
_DEBERTA_TIMEOUT_SECONDS: float = 60.0

# Truncate the chunk passed to lexical / DeBERTa so a giant evidence quote
# doesn't bloat the cross-encoder's window. nli_verifier already truncates
# to 384 tokens internally — this is just to keep the Celery payload small.
_CHUNK_MAX_CHARS: int = 4000

# Week 4 / Day 1: nli_worker SIGKILLs in the WSL Docker memory ceiling on
# batches of 17–20 pairs (DeBERTa-v3-base holds activations for the whole
# batch in one PyTorch forward pass). Per-pair truncation IS firing in
# deberta_client._truncate_to_relevant_window — the OOM is purely from
# unbounded batch size. Fix: chunk the dispatcher into sub-batches of 5,
# dispatch sequentially, concatenate. Single model load amortises across
# sub-batches because nli_worker has --max-tasks-per-child=1000000 (the
# Celery 5.3.6 sentinel from Week 2 / Day 1).
_DEBERTA_SUBBATCH_SIZE: int = 5


def _combined_chunk(
    eids: list[str],
    evidence_by_id: dict[str, EvidenceObject],
) -> str:
    """Concatenate the cited evidence quotes into one premise string.

    Empty when the row cites no evidence (e.g. an analyst assumption row).
    The aggregator handles that case via its "unknown LLM verdict" branch
    when verifier_verdict is also absent.
    """
    pieces: list[str] = []
    for e in eids:
        obj = evidence_by_id.get(e)
        if obj is None:
            continue
        q = (obj.quote or "").strip()
        if q:
            pieces.append(q)
    text = " ".join(pieces)
    return text[:_CHUNK_MAX_CHARS]


def _unknown_deberta() -> dict[str, Any]:
    return {"label": "unknown", "confidence": 0.0, "softmax": [0.0, 0.0, 0.0]}


def _pair_size_stats(pairs: list[list[str]]) -> dict[str, int]:
    """Diagnostic stats logged before each dispatch — the data we'd want
    to see if a future batch unexpectedly OOMs again.
    """
    if not pairs:
        return {"n": 0, "total_chars": 0, "max_premise_chars": 0, "max_hyp_chars": 0}
    max_p = 0
    max_h = 0
    total = 0
    for p, h in pairs:
        lp = len(p or "")
        lh = len(h or "")
        total += lp + lh
        if lp > max_p:
            max_p = lp
        if lh > max_h:
            max_h = lh
    return {
        "n": len(pairs),
        "total_chars": total,
        "max_premise_chars": max_p,
        "max_hyp_chars": max_h,
    }


async def _send_one_subbatch(
    sub_pairs: list[list[str]],
    *,
    sub_index: int,
    n_subs: int,
) -> list[dict[str, Any]]:
    """Dispatch ONE sub-batch to nli_worker and wait for the result.

    Catches every exception (broker errors, worker SIGKILL, timeout) and
    returns a list of ``unknown`` sentinels of the right length so the
    caller can keep going. Day 1 contract: a single sub-batch failure
    must not poison the rest.
    """
    if not sub_pairs:
        return []
    from tasks.pipeline import celery_app  # noqa: WPS433

    try:
        async_result = celery_app.send_task(
            "nli.score_pairs",
            args=[sub_pairs],
            queue="nli",
        )
        # ``.get()`` is sync; off-load to a thread so the orchestrator's
        # event loop isn't blocked while DeBERTa scores the sub-batch.
        results = await asyncio.to_thread(
            async_result.get, timeout=_DEBERTA_TIMEOUT_SECONDS
        )
        if not isinstance(results, list) or len(results) != len(sub_pairs):
            logger.warning(
                "DeBERTa sub-batch %d/%d returned unexpected shape "
                "(%d pairs in, %s out)",
                sub_index + 1,
                n_subs,
                len(sub_pairs),
                type(results).__name__,
            )
            return [_unknown_deberta() for _ in sub_pairs]
        return results  # type: ignore[no-any-return]
    except Exception as e:  # noqa: BLE001 — degrade, don't abort
        logger.warning(
            "DeBERTa sub-batch %d/%d dispatch failed (%d pairs): %s",
            sub_index + 1,
            n_subs,
            len(sub_pairs),
            e,
        )
        return [_unknown_deberta() for _ in sub_pairs]


async def _dispatch_deberta_batch(pairs: list[list[str]]) -> list[dict[str, Any]]:
    """Submit pairs to ``nli.score_pairs`` in sub-batches of
    :data:`_DEBERTA_SUBBATCH_SIZE`, dispatch sequentially, concatenate.

    Sequential rather than parallel because the worker has concurrency=1
    by design (DeBERTa is heavy and the model loads once per fork) — two
    in-flight tasks would just serialise behind each other while doubling
    Redis traffic. Sub-batch failures degrade per-sub-batch (sentinels
    only for the failing window) so one OOM doesn't blank the whole
    enrichment.

    Imported lazily so this module's import cost stays small (and so unit
    tests can monkeypatch the dispatch without dragging Celery in).
    """
    if not pairs:
        return []

    stats = _pair_size_stats(pairs)
    n_subs = (len(pairs) + _DEBERTA_SUBBATCH_SIZE - 1) // _DEBERTA_SUBBATCH_SIZE
    logger.info(
        "DeBERTa dispatch: %d pairs in %d sub-batch(es) of %d "
        "(total_chars=%d, max_premise_chars=%d, max_hyp_chars=%d)",
        stats["n"],
        n_subs,
        _DEBERTA_SUBBATCH_SIZE,
        stats["total_chars"],
        stats["max_premise_chars"],
        stats["max_hyp_chars"],
    )

    out: list[dict[str, Any]] = []
    for i in range(0, len(pairs), _DEBERTA_SUBBATCH_SIZE):
        sub = pairs[i : i + _DEBERTA_SUBBATCH_SIZE]
        sub_index = i // _DEBERTA_SUBBATCH_SIZE
        sub_results = await _send_one_subbatch(sub, sub_index=sub_index, n_subs=n_subs)
        out.extend(sub_results)
    return out


async def enrich_with_ensemble_signals(
    rows: list[dict[str, Any]],
    evidence_objects: list[EvidenceObject],
) -> list[dict[str, Any]]:
    """Augment each claim_support row with the 8 new ensemble columns.

    Returns NEW row dicts; does not mutate input. The augmented dicts are
    a superset of what ``build_claim_support`` produced, so the downstream
    persistence layer (``replace_claim_support_rows``) accepts them
    without further changes.

    Order of operations:
        rows from build_claim_support
          -> compute lexical signal per row (sync, fast)
          -> dispatch ONE batched DeBERTa task to nli_worker
          -> run aggregator per row
    """
    if not rows:
        return []

    evidence_by_id: dict[str, EvidenceObject] = {
        str(o.id): o for o in evidence_objects if o.id
    }

    # Phase 1: lexical overlap is local — compute per row up-front so the
    # batched DeBERTa call sees identical (premise, hypothesis) pairs.
    enriched: list[dict[str, Any]] = []
    pairs: list[list[str]] = []
    lexicals: list = []  # list[LexicalSignal], avoiding a second import.
    for row in rows:
        eids = [str(x) for x in (row.get("evidence_object_ids") or []) if x]
        chunk_text = _combined_chunk(eids, evidence_by_id)
        claim_text = str(row.get("claim_text", ""))
        lex = score_overlap(claim_text, chunk_text)
        lexicals.append(lex)
        pairs.append([chunk_text, claim_text])  # premise, hypothesis
        # Don't write ensemble columns yet — DeBERTa hasn't returned.
        enriched.append({**row})

    # Phase 2: batched DeBERTa.
    deberta_results = await _dispatch_deberta_batch(pairs)

    # Phase 3: aggregate + attach all eight columns.
    for i, row in enumerate(enriched):
        d = deberta_results[i] if i < len(deberta_results) else _unknown_deberta()
        sm = d.get("softmax") or [0.0, 0.0, 0.0]
        if not isinstance(sm, (list, tuple)) or len(sm) != 3:
            sm = [0.0, 0.0, 0.0]
        nli_obj = NLIResult(
            label=str(d.get("label") or "unknown"),  # type: ignore[arg-type]
            confidence=float(d.get("confidence") or 0.0),
            softmax=(float(sm[0]), float(sm[1]), float(sm[2])),
        )
        lex = lexicals[i]
        llm_verdict = row.get("verifier_verdict") or ""
        ensemble_verdict, ensemble_reason = aggregate(llm_verdict, nli_obj, lex)

        row["nli_label"] = nli_obj.label
        row["nli_confidence"] = nli_obj.confidence
        row["numeric_overlap_score"] = lex.numeric_overlap_score
        row["numeric_overlap_missing"] = list(lex.numeric_missing)
        row["entity_overlap_score"] = lex.entity_overlap_score
        row["entity_overlap_missing"] = list(lex.entity_missing)
        row["ensemble_verdict"] = ensemble_verdict
        row["ensemble_reason"] = ensemble_reason

    return enriched
