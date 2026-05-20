"""Interview guide exporters — markdown (W13/D3). PDF follows W13/D4.

The interview guide is the consultant's tool for expert validation
calls. Three sections per spec:

  - A: Critical evidence gaps (gap_report-derived, capped at 7).
  - B: Pressure-test the recommendation (top-3 reasons + top-2 risks
       turned into questions, capped at 5).
  - C: Mode-specific deep-dive (M&A integration / growth market
       dynamics / general failure-mode scan, capped at 5).

Total cap across the guide: 15 questions (45-60 min realistic budget).

Reserved underscore-prefixed payload keys consumed by the builder:
  - ``gap_report``: top-level dict {missing_evidence: [...], ...}.
    The service layer injects this via ``_gap_report`` when generating
    interview_guide artifacts so the builder doesn't need a DB round-trip.
  - ``_engagement_title``, ``_target_name``, ``_firm_name``,
    ``_mode_hint``: same as the other exporters.
"""

from __future__ import annotations

from typing import Any

from ._base import ClaimCitation, ExporterBase, ExporterResult
from ._registry import register
from .interview_guide_builder import InterviewGuideBuilder


@register("interview_guide", "md")
class InterviewGuideMarkdownExporter(ExporterBase):
    artifact_type = "interview_guide"
    format = "md"

    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        builder = InterviewGuideBuilder(payload, firm_branding, citations)
        md = builder.build_markdown()
        encoded = md.encode("utf-8")
        return ExporterResult(
            file_bytes=encoded,
            file_size=len(encoded),
            claim_citation_count=builder.citation_count,
            metadata={
                "format_subtype": "markdown",
                "mode": builder.mode,
                "question_count": builder.question_count,
                "section_a_count": len(builder.section_a),
                "section_b_count": len(builder.section_b),
                "section_c_count": len(builder.section_c),
                "cited_claim_ids": list(builder.cited_claim_ids),
            },
        )


__all__ = ["InterviewGuideMarkdownExporter"]
