"""Celery task that runs DeBERTa NLI on a batch of (premise, hypothesis) pairs.

Lives on the dedicated ``nli`` queue served by the ``nli_worker`` compose
service so the model loads exactly once per process. The main worker (default
``celery`` queue, see tasks/pipeline.py) does NOT subscribe to this queue and
won't pick up these tasks even if it has spare capacity — important because
the main worker has ``worker_max_tasks_per_child=1`` which would force a
~10s model reload per task.

Day 1 scope: task is registered, callable from the main worker, and
returns serialisable dicts. Day 3 wires it into the verifier path.
"""

from __future__ import annotations

import logging
from typing import Any

from tasks.pipeline import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="nli.score_pairs", queue="nli")
def score_pairs_task(pairs: list[list[str]]) -> list[dict[str, Any]]:
    """Score a batch of NLI pairs on the dedicated NLI worker.

    Parameters
    ----------
    pairs:
        List of ``[premise, hypothesis]`` lists (lists not tuples — JSON
        serialisation collapses tuples to lists, so we accept either).
        **Premise is the cited chunk; hypothesis is the claim.**

    Returns
    -------
    list[dict]
        One dict per input pair with keys ``label`` (str),
        ``confidence`` (float), ``softmax`` (3-tuple of floats in
        contradiction/entailment/neutral order). Plain Python types so
        the Celery JSON result serialiser is happy.
    """
    # Late import so simply importing this module on the main worker
    # doesn't drag torch + transformers into the main worker's address
    # space. They only land when score_pairs_task actually runs, which
    # only happens on nli_worker (queue=nli).
    from core.nli.deberta_client import score_pairs  # noqa: WPS433

    normalised = [(str(p[0]), str(p[1])) for p in pairs]
    logger.info("nli.score_pairs received %d pair(s)", len(normalised))
    results = score_pairs(normalised)
    return [
        {
            "label": r.label,
            "confidence": r.confidence,
            "softmax": list(r.softmax),
        }
        for r in results
    ]
