"""StructuredAnswer schema — every claim references real chunk IDs.

Produced by the structured grounder (Phase 7) after the existing writer runs.
NLI-verified by the verifier (Phase 8). Surfaced inline by the frontend so
hovering a citation shows page/section/timestamp from the underlying chunk.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConfidenceLevel = Literal["high", "medium", "contested"]
NliLabel = Literal["entailment", "neutral", "contradiction", "skipped"]
VerificationState = Literal["pending", "verifying", "complete"]


class NliResult(BaseModel):
    """Verifier output for a single (claim, chunk) pair."""

    chunk_id: str
    label: NliLabel = "skipped"
    score: float = 0.0  # model's probability for the assigned label

    model_config = {"extra": "ignore"}


class GroundedClaim(BaseModel):
    """A single factual claim within a Section, grounded in chunks."""

    text: str = Field(..., description="The claim as it appears in the section text.")
    chunk_ids: list[str] = Field(default_factory=list, description="Chunk UUIDs that support this claim.")
    confidence: ConfidenceLevel = "medium"
    notes: str = Field(default="", description="Optional rationale (e.g. why confidence was downgraded).")
    # Phase 8: NLI verifier writes per-(claim, chunk) entailment results here.
    nli_results: list[NliResult] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class StructuredSection(BaseModel):
    """One narrative section: a paragraph or bullet, with claims attached."""

    heading: str = Field(default="", description="Optional section title.")
    text: str = Field(..., description="The narrative prose for this section.")
    claims: list[GroundedClaim] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class StructuredAnswer(BaseModel):
    """The deliverable, structured for citation-faithful rendering."""

    tldr: str = Field(default="", description="One- or two-sentence headline answer.")
    sections: list[StructuredSection] = Field(default_factory=list)
    caveats: str = Field(default="", description="Surfaces unsupported / weak claims explicitly.")
    validation_notes: list[str] = Field(
        default_factory=list,
        description="Ingest-time validation messages: dropped chunk_ids, downgraded claims, etc.",
    )
    # Verification streaming state — frontend renders per-claim "verifying..."
    # markers when this is "verifying" and a claim has no nli_results yet.
    verification_state: VerificationState = "pending"

    model_config = {"extra": "ignore"}

    def total_chunk_refs(self) -> int:
        n = 0
        for s in self.sections:
            for c in s.claims:
                n += len(c.chunk_ids)
        return n

    def unique_chunk_ids(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in self.sections:
            for c in s.claims:
                for cid in c.chunk_ids:
                    if cid not in seen:
                        seen[cid] = None
        return list(seen.keys())
