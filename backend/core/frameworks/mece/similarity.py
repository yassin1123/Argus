"""Pairwise-embedding similarity engine — W8/D2.

Given a list of items and an async embedder, returns the overlap
findings above the configured threshold. No LLM judging — that's a
deliberate v1 choice per the W8/D2 hard rules:

- Pairwise embedding is cheap (~$0.00002 per item with
  ``text-embedding-3-small``) and deterministic.
- An LLM judge for MECE would introduce non-reproducibility we
  don't want yet.

Skip rules:

- Items with fewer than ``DEFAULT_MIN_WORDS_PER_ITEM`` words are
  skipped from pairing (too short to embed meaningfully).
- Lists with more than ``DEFAULT_MAX_LIST_SIZE`` items get a
  structural finding instead of pairwise comparison (avoids
  combinatorial blow-up + cost spike on poorly-bounded lists).

The embedder is passed in as ``Callable[[list[str]], Awaitable[list[list[float]]]]``
so callers can swap implementations (real OpenAI batch call, mocked
deterministic embedder for tests, etc.) without touching this module.
"""

from __future__ import annotations

import math
from typing import Awaitable, Callable

from .types import (
    DEFAULT_MAX_LIST_SIZE,
    DEFAULT_MIN_WORDS_PER_ITEM,
    DEFAULT_THRESHOLD,
    MECEOverlap,
)

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _preview(text: str, n: int = 80) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else (t[: n - 1] + "…")


def _suggested_resolution(a: str, b: str, score: float) -> str:
    """Auto-decide: short, prescriptive sentence the consultant can act on.

    Auto-decided per spec ("suggested_resolution wording" listed under
    auto-decide). One template; no LLM in the loop.
    """
    return (
        f"These two items overlap (cosine={score:.2f}) — consider merging into one, "
        f"or sharpening the difference (what does '{_preview(a, 50)}' say that "
        f"'{_preview(b, 50)}' does not?)."
    )


async def check_list_for_overlaps(
    items: list[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    embedder: Embedder,
    max_list_size: int = DEFAULT_MAX_LIST_SIZE,
    min_words_per_item: int = DEFAULT_MIN_WORDS_PER_ITEM,
) -> tuple[list[MECEOverlap], int]:
    """Pairwise-similarity check on one annotated list.

    Returns ``(overlaps, items_embedded)`` — the second value lets the
    caller tally an embedding cost (USD per token isn't a constant
    we want to hard-code here; the checker does the multiplication).

    Behaviour:

    - Empty / one-element lists → ``([], 0)``.
    - List longer than ``max_list_size`` → one structural finding with
      ``item_a_index = item_b_index = -1`` and ``similarity_score=0.0``;
      no embedding calls made.
    - Items with fewer than ``min_words_per_item`` words → skipped
      from the comparison (no finding, no embedding call for the
      short items). If after filtering fewer than 2 items remain,
      returns ``([], 0)``.
    """
    if not items or len(items) < 2:
        return ([], 0)

    if len(items) > max_list_size:
        overlap = MECEOverlap(
            field_path="",  # caller fills this
            item_a_index=-1,
            item_b_index=-1,
            item_a_text=_preview(items[0]),
            item_b_text=f"(+{len(items) - 1} more)",
            similarity_score=0.0,
            suggested_resolution=(
                f"List has {len(items)} items, exceeds {max_list_size}-item MECE limit. "
                f"Group sub-items under fewer parent categories before re-running."
            ),
        )
        return ([overlap], 0)

    # Filter out items that are too short to embed meaningfully.
    keep: list[tuple[int, str]] = []
    for idx, text in enumerate(items):
        if len(text.split()) >= min_words_per_item:
            keep.append((idx, text))
    if len(keep) < 2:
        return ([], 0)

    texts_to_embed = [t for _, t in keep]
    embeddings = await embedder(texts_to_embed)
    if len(embeddings) != len(texts_to_embed):
        # Embedder API drift — bail safely.
        return ([], 0)

    overlaps: list[MECEOverlap] = []
    for i in range(len(keep)):
        for j in range(i + 1, len(keep)):
            idx_a, text_a = keep[i]
            idx_b, text_b = keep[j]
            score = _cosine(embeddings[i], embeddings[j])
            if score >= threshold:
                overlaps.append(
                    MECEOverlap(
                        field_path="",  # caller fills
                        item_a_index=idx_a,
                        item_b_index=idx_b,
                        item_a_text=_preview(text_a),
                        item_b_text=_preview(text_b),
                        similarity_score=round(score, 4),
                        suggested_resolution=_suggested_resolution(text_a, text_b, score),
                    )
                )
    return (overlaps, len(texts_to_embed))
