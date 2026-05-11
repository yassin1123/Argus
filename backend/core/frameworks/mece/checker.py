"""Combined MECE checker entry point — W8/D2.

Walks the writer payload for annotated lists, runs pairwise embedding
similarity on each, returns a single :class:`MECECheckResult`.

The orchestrator calls this post-writer alongside the Pyramid check.
Findings are advisory and never block ``deliverable_ready``.

Cost target: < $0.01 per engagement. With ``text-embedding-3-small``
at ~$0.02 / 1M tokens, embedding ~30 short list items per memo lands
at fractions of a cent. The checker tallies token-equivalent cost
optimistically (4 chars ≈ 1 token) as a guard rail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable

from pydantic import BaseModel

from core.embeddings import embed_texts

from .similarity import check_list_for_overlaps
from .types import DEFAULT_THRESHOLD, MECECheckResult, MECEOverlap
from .walker import find_mece_check_targets

# text-embedding-3-small pricing as of 2025-01: $0.02 / 1M tokens.
# Used as a cheap upper-bound estimate; the cost-tracking row in
# ``llm_calls`` (when the orchestrator records the embed batch
# separately) is the authoritative figure.
_EMBED_USD_PER_TOKEN = 0.02 / 1_000_000
_CHARS_PER_TOKEN_EST = 4

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


def _estimate_cost(items_embedded: int, total_chars: int) -> float:
    if items_embedded <= 0:
        return 0.0
    approx_tokens = max(items_embedded, total_chars // _CHARS_PER_TOKEN_EST)
    return round(approx_tokens * _EMBED_USD_PER_TOKEN, 6)


async def run_mece_check(
    payload: BaseModel,
    *,
    embedder: Embedder | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> MECECheckResult:
    """Combined MECE check across every annotated list on ``payload``.

    Parameters
    ----------
    payload:
        Writer payload (``WriterReportBase`` or subclass). The walker
        inspects ``json_schema_extra`` on each field to decide which
        lists to inspect.
    embedder:
        Async callable that embeds a batch of strings. Defaults to
        the project's ``core.embeddings.embed_texts`` (OpenAI
        ``text-embedding-3-small``). Tests inject a deterministic
        stand-in via this parameter.
    threshold:
        Cosine threshold above which a pair is flagged. Default 0.85
        per W8/D2 spec; don't tune this to make demos pass.
    """
    if embedder is None:
        embedder = embed_texts

    targets = find_mece_check_targets(payload)
    all_overlaps: list[MECEOverlap] = []
    total_items_embedded = 0
    total_chars = 0

    for field_path, items in targets:
        overlaps, items_embedded = await check_list_for_overlaps(
            items,
            threshold=threshold,
            embedder=embedder,
        )
        for o in overlaps:
            o.field_path = field_path
            all_overlaps.append(o)
        total_items_embedded += items_embedded
        total_chars += sum(len(t) for t in items)

    cost = _estimate_cost(total_items_embedded, total_chars)
    return MECECheckResult(
        passed=not any(o.item_a_index >= 0 for o in all_overlaps),
        overlaps=all_overlaps,
        fields_checked=[p for p, _ in targets],
        threshold=threshold,
        checked_at=datetime.now(timezone.utc),
        cost_usd=cost,
    )
