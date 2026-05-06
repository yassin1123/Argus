"""DeBERTa cross-encoder NLI client.

Wraps ``cross-encoder/nli-deberta-v3-base`` (sentence-transformers
``CrossEncoder``) for per-pair entailment scoring. The model is loaded
lazily once per process and cached at module scope; running this inside the
``nli_worker`` Celery service (concurrency=1, --max-tasks-per-child=0 so the
fork is never recycled) means production code amortises the ~10s load over
the lifetime of the worker, not every task.

This module deliberately does NOT touch the verifier yet — Day 1 is about
proving the model loads, scores pairs correctly, and stays under the latency
+ memory budget. The verifier integration is Day 3.

LABEL ORDER (read this before touching anything)
================================================
``cross-encoder/nli-deberta-v3-base`` emits a 3-class logit vector in the
order **(contradiction, entailment, neutral)**. We expose the post-softmax
probabilities in the same order via ``NLIResult.softmax`` and document this
loudly because:

1. Other NLI cross-encoders (e.g. some MNLI checkpoints) use
   (entailment, neutral, contradiction) — silently swapping models is a
   real way to invert verifier verdicts.
2. The label index <-> name mapping comes from the model's ``id2label``
   config; we read it at load time and verify it matches our assumption,
   raising RuntimeError on mismatch rather than silently misinterpreting.

PAIR ORDER
==========
``score_pairs`` takes ``(premise, hypothesis)``. In Argus terms:
**premise = the cited chunk, hypothesis = the claim**.
Flipping the order produces nonsense — the model scores
"does the premise entail the hypothesis" and is not symmetric. The
order-sensitivity assertion in
``backend/tests/test_nli_deberta_smoke.py`` exists exactly to catch the
bug where a future caller swaps these.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from threading import Lock
from typing import Literal

logger = logging.getLogger(__name__)

MODEL_NAME = "cross-encoder/nli-deberta-v3-base"

# Order matches the model's id2label; we assert this at load time.
_LABEL_ORDER: tuple[str, str, str] = ("contradiction", "entailment", "neutral")

NliLabel = Literal["entailment", "neutral", "contradiction"]


@dataclass(frozen=True)
class NLIResult:
    """One verdict for a single (premise, hypothesis) pair.

    Attributes
    ----------
    label:
        Argmax over the three classes.
    confidence:
        Softmax probability of ``label`` (i.e. the max-class probability).
    softmax:
        Full 3-tuple in label order ``(contradiction, entailment, neutral)``.
        Stored as a tuple so the dataclass stays hashable / JSON-friendly
        (Celery serialises results as JSON).
    """

    label: NliLabel
    confidence: float
    softmax: tuple[float, float, float]


# ---------------------------------------------------------------------------
# Model loading (lazy, process-level cache)
# ---------------------------------------------------------------------------

_MODEL = None
_MODEL_LOCK = Lock()


def _load_model():  # type: ignore[no-untyped-def]
    """Load the cross-encoder once per process. Subsequent calls return the
    cached instance. Thread-safe via a module-level lock so simultaneous
    Celery tasks on the same fork don't race the first load.
    """
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        # Late import — the heavy torch / transformers import is paid only
        # when something actually calls into NLI (so e.g. the FastAPI
        # backend container, which doesn't run NLI, never pays it).
        from sentence_transformers import CrossEncoder  # noqa: WPS433

        logger.info("Loading DeBERTa NLI cross-encoder: %s", MODEL_NAME)
        model = CrossEncoder(MODEL_NAME)

        # Verify the model's label order matches our assumption. If a future
        # bump pulls a different checkpoint with a different id2label we
        # want to crash here, not silently misinterpret verdicts in prod.
        id2label = getattr(model.config, "id2label", None) or {}
        observed = tuple(str(id2label.get(i, "")).strip().lower() for i in range(3))
        if observed != _LABEL_ORDER:
            raise RuntimeError(
                f"DeBERTa NLI label order mismatch. "
                f"Expected {_LABEL_ORDER}, got {observed}. "
                "Update _LABEL_ORDER (and downstream consumers) intentionally — "
                "this is not a bug to silently work around."
            )
        logger.info("DeBERTa cross-encoder loaded — label order=%s", observed)
        _MODEL = model
        return _MODEL


# ---------------------------------------------------------------------------
# Premise-window truncation
# ---------------------------------------------------------------------------

# Conservative content-word stop list. The point of removing these is to
# prevent windows full of "the / and / for" from out-scoring a window with
# real entity overlap; we don't need a perfect linguistic stopword list.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "of", "for", "and", "or", "but", "in", "on", "at",
        "to", "from", "by", "with", "as", "is", "are", "was", "were", "be",
        "been", "being", "has", "have", "had", "this", "that", "these",
        "those", "it", "its", "into", "than", "then", "so", "if", "not",
        "no", "nor", "do", "does", "did", "done",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9€$£%]+")


def _content_tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOPWORDS}


def _truncate_to_relevant_window(
    premise: str,
    hypothesis: str,
    *,
    max_tokens: int = 384,
) -> str:
    """Trim ``premise`` to the ``max_tokens``-token window with the highest
    content-word overlap with ``hypothesis``.

    Naive end-truncation drops the second half of long evidence quotes
    even when the second half is what the claim is talking about. Sliding
    a window across the premise and picking the best-overlap window keeps
    the relevant sentences regardless of where they sit in the source.

    Tokenisation uses the model's own tokenizer so the budget matches what
    the cross-encoder will actually consume. Returns plain text — the
    caller passes it back to ``model.predict`` which retokenises.
    """
    model = _load_model()
    tokenizer = model.tokenizer

    # Encode without special tokens; we only need the count + the slice.
    ids = tokenizer.encode(premise or "", add_special_tokens=False)
    if len(ids) <= max_tokens:
        return premise or ""

    hyp_keywords = _content_tokens(hypothesis)
    if not hyp_keywords:
        # No content words to align on — fall back to keeping the head
        # window (still better than mid-document truncation in practice).
        head = tokenizer.decode(ids[:max_tokens], skip_special_tokens=True)
        return head

    stride = max(1, max_tokens // 2)  # 50% overlap so we don't miss boundaries
    best_text = ""
    best_score = -1
    for start in range(0, len(ids) - max_tokens + 1, stride):
        window_ids = ids[start : start + max_tokens]
        window_text = tokenizer.decode(window_ids, skip_special_tokens=True)
        window_keywords = _content_tokens(window_text)
        score = len(window_keywords & hyp_keywords)
        if score > best_score:
            best_score = score
            best_text = window_text
    # Make sure the trailing window is considered too, even if stride
    # doesn't land exactly on it.
    tail_ids = ids[-max_tokens:]
    tail_text = tokenizer.decode(tail_ids, skip_special_tokens=True)
    tail_score = len(_content_tokens(tail_text) & hyp_keywords)
    if tail_score > best_score:
        best_text = tail_text
    return best_text


# ---------------------------------------------------------------------------
# Public scoring API
# ---------------------------------------------------------------------------


def score_pairs(pairs: list[tuple[str, str]]) -> list[NLIResult]:
    """Score a batch of (premise, hypothesis) pairs.

    Parameters
    ----------
    pairs:
        List of ``(premise, hypothesis)`` tuples. **Premise is the cited
        chunk; hypothesis is the claim.** Flipping these produces
        nonsense — see the module docstring.

    Returns
    -------
    list[NLIResult]
        One result per input pair, in input order.
    """
    if not pairs:
        return []

    # Late math import so the smoke test's import doesn't pay for it
    # twice if the test happens to land before _load_model.
    import numpy as np  # noqa: WPS433

    model = _load_model()

    # Truncate premises that exceed the model's window. Hypotheses are
    # always short claims; the cross-encoder will pair-encode (premise +
    # [SEP] + hypothesis) so we leave headroom for the hypothesis.
    truncated: list[tuple[str, str]] = []
    for premise, hypothesis in pairs:
        # We give the premise a 384-token budget; nli-deberta-v3-base
        # has a 512-token total context, so 384 leaves ~120 for the
        # hypothesis + special tokens which is comfortably enough for
        # any single claim sentence.
        trimmed = _truncate_to_relevant_window(premise or "", hypothesis or "", max_tokens=384)
        truncated.append((trimmed, hypothesis or ""))

    raw_logits = model.predict(
        [[p, h] for p, h in truncated],
        apply_softmax=False,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    # Softmax row-wise — sentence-transformers returns (N, 3) for 3-class.
    arr = np.asarray(raw_logits, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    # Numerically stable softmax.
    shifted = arr - arr.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    probs = exp / exp.sum(axis=1, keepdims=True)

    results: list[NLIResult] = []
    for row in probs:
        idx = int(row.argmax())
        label = _LABEL_ORDER[idx]
        results.append(
            NLIResult(
                label=label,  # type: ignore[arg-type]
                confidence=float(row[idx]),
                softmax=(float(row[0]), float(row[1]), float(row[2])),
            )
        )
    return results
