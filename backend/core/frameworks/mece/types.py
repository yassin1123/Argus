"""MECE checker output schema — W8/D2.

:class:`MECEOverlap` is one detected pair-overlap; :class:`MECECheckResult`
is the per-engagement rollup persisted to ``session.metadata.mece_check_result``.

``passed`` is True iff zero overlaps above the threshold. Like the
Pyramid checker, MECE findings are advisory and never block
``deliverable_ready`` — the consultant decides whether to merge or
differentiate the flagged items.

Structural findings (e.g. "list too long for MECE check") also land
here, with ``item_a_index = item_b_index = -1`` as a sentinel so
downstream UI knows the overlap entry isn't a pair-level finding.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# Default threshold per W8/D2 spec. Don't tune this to make demos pass.
DEFAULT_THRESHOLD = 0.85

# Max items per list before we skip pairwise comparison and emit a
# structural finding instead — keeps the cost bounded and avoids
# combinatorial blow-up on poorly-bounded lists.
DEFAULT_MAX_LIST_SIZE = 20

# Items with fewer words than this are too short for the embedding
# model to discriminate meaningfully. Skipped from comparison; not
# treated as a finding (a 2-word reason isn't a MECE bug, it's a
# different writer issue).
DEFAULT_MIN_WORDS_PER_ITEM = 4


class MECEOverlap(BaseModel):
    """One detected overlap between two items in an annotated list."""

    field_path: str = Field(..., description="Dotted path to the parent list, e.g. 'key_reasons'.")
    item_a_index: int = Field(..., description="Index of the first item in the source list (-1 for structural findings).")
    item_b_index: int = Field(..., description="Index of the second item (-1 for structural findings).")
    item_a_text: str = Field(..., description="Short preview of item A (truncated to keep the row scannable).")
    item_b_text: str = Field(..., description="Short preview of item B.")
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Cosine similarity of the two embeddings.")
    suggested_resolution: str = Field(..., description="Human-readable hint on how to disambiguate or merge.")

    model_config = {"extra": "ignore"}


class MECECheckResult(BaseModel):
    """Full output of one MECE check pass over a writer payload."""

    passed: bool = Field(..., description="True iff zero overlaps above the threshold.")
    overlaps: list[MECEOverlap] = Field(default_factory=list)
    fields_checked: list[str] = Field(
        default_factory=list,
        description="Dotted paths the walker found and the engine inspected.",
    )
    threshold: float = Field(..., ge=0.0, le=1.0, description="Cosine threshold used for this pass.")
    checked_at: datetime
    cost_usd: float = Field(0.0, ge=0.0, description="Embedding-API USD cost incurred by this pass.")

    model_config = {"extra": "ignore"}

    @property
    def overlap_count(self) -> int:
        return len([o for o in self.overlaps if o.item_a_index >= 0])

    @property
    def structural_finding_count(self) -> int:
        return len([o for o in self.overlaps if o.item_a_index < 0])
