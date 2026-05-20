"""InterviewGuideBuilder — composes a 45-60 min expert validation guide.

Sourcing logic:
  - Section A pulls from the session's ``gap_report.missing_evidence``
    (1-2 questions per gap, capped at 7). When the gap_report is
    empty, Section A renders a single line ("No critical evidence
    gaps identified.") rather than padding with weak questions.
  - Section B pressure-tests the recommendation via top-3-reason +
    top-3-risk → question conversions. Each Section B question
    carries ``linked_claim_ids`` so the consultant can cross-reference
    back to the memo.
  - Section C is mode-specific:
      * m_and_a_diligence → integration / synergy validation /
        walk-away trigger questions
      * growth_strategy → market dynamics / competitive response /
        channel mix questions
      * general → assumptions / implementation / monitoring

Hard caps per spec:
  - Section A ≤ 7 questions
  - Section B ≤ 5 questions
  - Section C ≤ 5 questions
  - Total ≤ 15 questions across the guide

Each question is a structured dict (see ``Question`` TypedDict) with
``text``, ``priority``, ``time_estimate_minutes``, ``topic``,
``linked_claim_ids``, ``source``, ``why_asking``, and an optional
``follow_up_probe`` line.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, TypedDict

from ._base import ClaimCitation, payload_get


class Question(TypedDict, total=False):
    text: str
    priority: str  # "high" | "medium" | "low"
    time_estimate_minutes: int
    topic: str
    linked_claim_ids: list[str]
    source: str  # "gap_report" | "recommendation_pressure_test" | "mode_specific"
    why_asking: str
    follow_up_probe: str


# Hard caps per spec.
_MAX_SECTION_A = 7
_MAX_SECTION_B = 5
_MAX_SECTION_C = 5
_MAX_TOTAL = 15


class InterviewGuideBuilder:
    """Pure builder — produces a structured set of three sections + a
    markdown render. Tests can poke at the section lists directly
    (``self.section_a``, etc.) without going through the markdown
    string."""

    def __init__(
        self,
        payload: Any,
        firm_branding: dict[str, Any] | None,
        citations: list[ClaimCitation] | None,
    ) -> None:
        self._payload = payload
        self._branding = dict(firm_branding or {})
        self._citations = list(citations or [])

        mode_hint = payload_get(payload, "_mode_hint", default=None)
        explicit_mode = str(payload_get(payload, "mode", default="") or "").strip()
        self.mode: str = mode_hint or explicit_mode or "general"

        self.target_name: str = str(
            payload_get(payload, "_target_name", "_engagement_title", default="") or ""
        )
        self.engagement_title: str = str(
            payload_get(payload, "_engagement_title", default="") or ""
        )
        self.firm_name: str = str(
            self._branding.get("_firm_name")
            or payload_get(payload, "_firm_name", default="Argus")
            or "Argus"
        )

        # gap_report can be injected via payload (W13/D3 service layer
        # plumbing) or live as a top-level dict on the payload.
        gr = payload_get(payload, "gap_report", "_gap_report", default={}) or {}
        if isinstance(gr, str):
            try:
                import json as _json
                gr = _json.loads(gr)
            except Exception:
                gr = {}
        self._gap_report: dict[str, Any] = gr if isinstance(gr, dict) else {}

        # Build the sections eagerly so ``question_count`` and the
        # markdown render stay in sync.
        self.section_a: list[Question] = self._build_section_a()
        self.section_b: list[Question] = self._build_section_b()
        self.section_c: list[Question] = self._build_section_c()
        self._enforce_total_cap()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def question_count(self) -> int:
        return len(self.section_a) + len(self.section_b) + len(self.section_c)

    @property
    def citation_count(self) -> int:
        """Distinct claim_ids referenced across Section B questions."""
        seen: set[str] = set()
        for q in self.section_b:
            for cid in q.get("linked_claim_ids") or []:
                if cid:
                    seen.add(cid)
        return len(seen)

    @property
    def cited_claim_ids(self) -> list[str]:
        seen: list[str] = []
        for q in self.section_b:
            for cid in q.get("linked_claim_ids") or []:
                if cid and cid not in seen:
                    seen.append(cid)
        return seen

    def build_markdown(self) -> str:
        return _render_markdown(
            engagement_title=self.engagement_title or "Argus engagement",
            target_name=self.target_name,
            firm_name=self.firm_name,
            mode=self.mode,
            recommendation_text=str(payload_get(self._payload, "recommendation", default="") or ""),
            section_a=self.section_a,
            section_b=self.section_b,
            section_c=self.section_c,
            gap_report=self._gap_report,
        )

    # ------------------------------------------------------------------
    # Section A — gap_report → questions
    # ------------------------------------------------------------------

    def _build_section_a(self) -> list[Question]:
        missing = self._gap_report.get("missing_evidence") or []
        if not isinstance(missing, list) or not missing:
            return []

        out: list[Question] = []
        for raw in missing:
            text = _stringify_gap_item(raw)
            if not text:
                continue
            topic = _topic_from_gap(text)
            primary = _gap_to_primary_question(text, topic, self.mode)
            probe = _gap_to_probe_question(text, topic, self.mode)
            out.append(Question(
                text=primary,
                priority="high",  # gap items are by definition where we're thin
                time_estimate_minutes=5,
                topic=topic,
                linked_claim_ids=[],
                source="gap_report",
                why_asking=(
                    f"Evidence gap flagged in analysis: \"{_truncate(text, 110)}\". "
                    f"An expert answer here would meaningfully strengthen the file."
                ),
                follow_up_probe=probe,
            ))
            if len(out) >= _MAX_SECTION_A:
                break
        return out

    # ------------------------------------------------------------------
    # Section B — pressure-test the recommendation
    # ------------------------------------------------------------------

    def _build_section_b(self) -> list[Question]:
        reasons = payload_get(self._payload, "key_reasons", default=[]) or []
        risks = payload_get(self._payload, "risks", default=[]) or []
        out: list[Question] = []

        for r in (reasons if isinstance(reasons, list) else [])[:3]:
            text = _text_from_listish(r)
            if not text:
                continue
            claim_ids = _claim_ids_from_listish(r)
            out.append(Question(
                text=_reason_to_pressure_test(text),
                priority="high",
                time_estimate_minutes=4,
                topic="Recommendation: supporting reason",
                linked_claim_ids=claim_ids,
                source="recommendation_pressure_test",
                why_asking=(
                    f"Recommendation rests on: \"{_truncate(text, 110)}\". "
                    f"An external view would tell us if we've over-weighted it."
                ),
                follow_up_probe=(
                    "If this assumption proved softer than we think, what's the "
                    "first observable signal you'd expect?"
                ),
            ))

        for r in (risks if isinstance(risks, list) else [])[:2]:
            text = _text_from_listish(r)
            if not text:
                continue
            claim_ids = _claim_ids_from_listish(r)
            out.append(Question(
                text=_risk_to_pressure_test(text),
                priority="high",
                time_estimate_minutes=4,
                topic="Recommendation: identified risk",
                linked_claim_ids=claim_ids,
                source="recommendation_pressure_test",
                why_asking=(
                    f"Flagged risk: \"{_truncate(text, 110)}\". "
                    f"We want a calibration check on probability + impact from "
                    f"someone closer to the situation."
                ),
                follow_up_probe=(
                    "What early-warning indicator would tell us this risk is "
                    "moving from latent to material?"
                ),
            ))

        # Cap Section B.
        if len(out) > _MAX_SECTION_B:
            out = out[:_MAX_SECTION_B]
        return out

    # ------------------------------------------------------------------
    # Section C — mode-specific deep-dives
    # ------------------------------------------------------------------

    def _build_section_c(self) -> list[Question]:
        if self.mode == "m_and_a_diligence":
            return self._m_and_a_section_c()
        if self.mode == "growth_strategy":
            return self._growth_section_c()
        return self._general_section_c()

    def _m_and_a_section_c(self) -> list[Question]:
        target = self.target_name or "the target"
        # Try to extract a synergy magnitude / IT system / walk-away trigger
        # from the payload for richer questions.
        synergy_phrase = _synergy_phrase(self._payload)
        walkaway_phrase = _walkaway_phrase(self._payload)

        questions: list[Question] = [
            Question(
                text=(
                    f"What's the realistic timeline for integrating IT systems "
                    f"across {target} given their legacy infrastructure? Where do "
                    f"deals like this most often slip?"
                ),
                priority="high",
                time_estimate_minutes=5,
                topic="Integration: IT systems",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Integration risk is the single biggest source of post-close "
                    "value destruction in M&A. We want a calibrated view of the "
                    "IT-side timeline before we close."
                ),
                follow_up_probe=(
                    "Are there specific systems / data domains that we should "
                    "expect to fail integration testing?"
                ),
            ),
            Question(
                text=(
                    f"Of the {synergy_phrase} the model projects, which feel most "
                    f"achievable and which would you discount?"
                ),
                priority="high",
                time_estimate_minutes=5,
                topic="Synergy validation",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Synergy estimates are the easiest line to over-promise on. "
                    "We want an outside-in pressure test before we anchor the "
                    "Board on these figures."
                ),
                follow_up_probe=(
                    "What's the typical realisation curve you've seen for "
                    "deals of this shape — and how does ours compare?"
                ),
            ),
            Question(
                text=(
                    f"Our walk-away trigger is {walkaway_phrase}. From your seat, "
                    f"is that the right line in the sand — or are there other "
                    f"signals we should be watching for?"
                ),
                priority="high",
                time_estimate_minutes=4,
                topic="Walk-away validation",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Walk-away discipline is what protects the firm from "
                    "deal-fever. We want an external view on whether our "
                    "threshold is set in the right place."
                ),
                follow_up_probe="",
            ),
            Question(
                text=(
                    f"What's the realistic post-close talent attrition risk on "
                    f"{target}'s key technical roles, and what retention "
                    f"economics have you seen work for situations like this?"
                ),
                priority="medium",
                time_estimate_minutes=4,
                topic="People & retention",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Key-person dependency is undermodeled in standard diligence. "
                    "An expert with hiring-side visibility can tell us what to "
                    "expect."
                ),
                follow_up_probe="",
            ),
            Question(
                text=(
                    f"If you had to predict the single biggest unhappy surprise "
                    f"in year 1 post-close for {target}, what would it be?"
                ),
                priority="medium",
                time_estimate_minutes=3,
                topic="Year-1 surprise scan",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Open-ended closer that often surfaces a risk none of the "
                    "structured questions reached."
                ),
                follow_up_probe="",
            ),
        ]
        return questions[:_MAX_SECTION_C]

    def _growth_section_c(self) -> list[Question]:
        target = self.target_name or "the firm"
        competitor = _top_competitor_name(self._payload)
        geography = _geography_phrase(self._payload, self.engagement_title)
        return [
            Question(
                text=(
                    f"If {target} enters {geography} aggressively, how would "
                    f"{competitor} likely respond — pricing, channel, or "
                    f"product?"
                ),
                priority="high",
                time_estimate_minutes=5,
                topic="Competitive response",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Incumbent response is the variable we can least observe "
                    "from the outside. An expert with channel visibility can "
                    "calibrate it."
                ),
                follow_up_probe=(
                    "How quickly would that response materialise — weeks, "
                    "months, or a full annual cycle?"
                ),
            ),
            Question(
                text=(
                    f"What's the realistic channel mix you'd expect for "
                    f"{geography}? Direct, partner, marketplace — and in "
                    f"roughly what proportions?"
                ),
                priority="high",
                time_estimate_minutes=5,
                topic="Channel mix",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Channel economics drive the cost-to-serve and the "
                    "addressable margin. Outside-in calibration meaningfully "
                    "tightens the financial model."
                ),
                follow_up_probe="",
            ),
            Question(
                text=(
                    f"What customer behaviours in {geography} differ "
                    f"meaningfully from the firm's home market — and how do "
                    f"those differences typically show up in unit economics?"
                ),
                priority="high",
                time_estimate_minutes=5,
                topic="Customer behaviour delta",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Default-to-home-market assumptions are the most common "
                    "failure mode in market-entry projects. An expert tells "
                    "us where the underlying behaviours bend."
                ),
                follow_up_probe="",
            ),
            Question(
                text=(
                    f"If we were going to pilot before scaling, what's the "
                    f"smallest credible test in {geography} that would "
                    f"actually de-risk the decision?"
                ),
                priority="medium",
                time_estimate_minutes=4,
                topic="Pilot design",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Calibrates our recommended path against an expert's "
                    "experience-based instinct on what 'a real test' looks "
                    "like."
                ),
                follow_up_probe="",
            ),
            Question(
                text=(
                    f"What would you watch for in the first six months that "
                    f"would tell you whether {target} is winning or losing "
                    f"the entry play?"
                ),
                priority="medium",
                time_estimate_minutes=3,
                topic="Leading indicators",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Gives the consultant a concrete monitoring checklist "
                    "that's grounded in expert experience rather than "
                    "first-principles guessing."
                ),
                follow_up_probe="",
            ),
        ][:_MAX_SECTION_C]

    def _general_section_c(self) -> list[Question]:
        return [
            Question(
                text=(
                    "Which of the assumptions underpinning our recommendation "
                    "would you most want stress-tested before acting?"
                ),
                priority="high",
                time_estimate_minutes=5,
                topic="Assumption robustness",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Forces the expert to triage our assumption stack rather "
                    "than reacting to specific items."
                ),
                follow_up_probe="",
            ),
            Question(
                text=(
                    "If our recommended path were to fail, what's the most "
                    "likely failure mode you'd expect — and what would the "
                    "early signals look like?"
                ),
                priority="high",
                time_estimate_minutes=5,
                topic="Failure mode scan",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Pre-mortem question that consistently surfaces risks the "
                    "structured analysis missed."
                ),
                follow_up_probe="",
            ),
            Question(
                text=(
                    "What's the smallest, cheapest test that would meaningfully "
                    "de-risk the recommendation if it succeeded — and what "
                    "would we expect it to cost?"
                ),
                priority="medium",
                time_estimate_minutes=4,
                topic="Smallest credible test",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Forces a practical, falsifiable framing on top of the "
                    "directional recommendation."
                ),
                follow_up_probe="",
            ),
            Question(
                text=(
                    "Are there adjacent options we haven't considered that "
                    "would dominate the recommended path under realistic "
                    "scenarios?"
                ),
                priority="medium",
                time_estimate_minutes=4,
                topic="Option-set check",
                linked_claim_ids=[],
                source="mode_specific",
                why_asking=(
                    "Calibrates whether our option-generation step was wide "
                    "enough."
                ),
                follow_up_probe="",
            ),
        ][:_MAX_SECTION_C]

    # ------------------------------------------------------------------
    # Global cap enforcement
    # ------------------------------------------------------------------

    def _enforce_total_cap(self) -> None:
        """Trim from the lowest-priority section first so the global
        cap of 15 holds even when all three sections hit their local
        caps."""
        budget = _MAX_TOTAL - len(self.section_a) - len(self.section_b)
        if budget < 0:
            self.section_b = self.section_b[: max(0, _MAX_TOTAL - len(self.section_a))]
            self.section_c = []
            return
        if len(self.section_c) > budget:
            self.section_c = self.section_c[:max(0, budget)]


# ---------------------------------------------------------------------------
# Markdown render
# ---------------------------------------------------------------------------


def _render_markdown(
    *,
    engagement_title: str,
    target_name: str,
    firm_name: str,
    mode: str,
    recommendation_text: str,
    section_a: list[Question],
    section_b: list[Question],
    section_c: list[Question],
    gap_report: dict[str, Any],
) -> str:
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    total_minutes = sum(
        int(q.get("time_estimate_minutes") or 0)
        for q in (section_a + section_b + section_c)
    )
    total_minutes_low = max(45, total_minutes - 10)
    total_minutes_high = max(total_minutes, total_minutes_low + 15)

    rec_line = (
        recommendation_text.strip().split(".", 1)[0]
        if recommendation_text else "(see attached memo)"
    )

    key_uncertainty = ""
    missing = gap_report.get("missing_evidence") or []
    if isinstance(missing, list) and missing:
        key_uncertainty = _stringify_gap_item(missing[0])

    mode_label = {
        "m_and_a_diligence": "M&A deep-dive",
        "growth_strategy": "Market dynamics deep-dive",
    }.get(mode, "Deep-dive")

    lines: list[str] = []
    lines.append("# Expert Validation Interview Guide")
    lines.append("")
    if target_name:
        lines.append(f"**Engagement:** {engagement_title} — {target_name}")
    else:
        lines.append(f"**Engagement:** {engagement_title}")
    lines.append(f"**Prepared by:** {firm_name}")
    lines.append(f"**Date:** {today}")
    lines.append(f"**Estimated total time:** {total_minutes_low}–{total_minutes_high} minutes")
    lines.append("")
    lines.append("## Pre-call briefing")
    lines.append(f"- Recommendation: {rec_line or '(see attached memo)'}")
    if key_uncertainty:
        lines.append(f"- Key uncertainty: {key_uncertainty}")
    else:
        lines.append("- Key uncertainty: see Section B (no critical gaps flagged)")
    lines.append(
        "- Goal of this call: validate the load-bearing reasons under the "
        "recommendation and surface any failure modes our analysis missed."
    )
    lines.append("")

    # Section A.
    sec_a_minutes = sum(int(q.get("time_estimate_minutes") or 0) for q in section_a)
    lines.append(
        f"## Section A — Critical evidence gaps ({sec_a_minutes or 0} min)"
    )
    lines.append("")
    if not section_a:
        lines.append(
            "_No critical evidence gaps identified in the analyst's gap report. "
            "Section B's pressure-test questions cover the load-bearing items._"
        )
        lines.append("")
    else:
        for i, q in enumerate(section_a, start=1):
            _render_question(lines, f"A{i}", q)

    # Section B.
    sec_b_minutes = sum(int(q.get("time_estimate_minutes") or 0) for q in section_b)
    lines.append(
        f"## Section B — Pressure-test the recommendation ({sec_b_minutes or 0} min)"
    )
    lines.append("")
    if not section_b:
        lines.append("_No recommendation pressure-test items derivable from the payload._")
        lines.append("")
    else:
        for i, q in enumerate(section_b, start=1):
            _render_question(lines, f"B{i}", q)

    # Section C.
    sec_c_minutes = sum(int(q.get("time_estimate_minutes") or 0) for q in section_c)
    lines.append(f"## Section C — {mode_label} ({sec_c_minutes or 0} min)")
    lines.append("")
    for i, q in enumerate(section_c, start=1):
        _render_question(lines, f"C{i}", q)

    # Closing notes.
    lines.append("## Closing notes")
    lines.append(
        "- Most useful answer would be: a concrete failure scenario or a "
        "calibrated probability we can carry into the Board ask."
    )
    lines.append(
        "- Red flags to listen for: dismissals without specifics, sweeping "
        "generalisations, or answers that contradict published industry data."
    )
    lines.append(
        "- After the call: capture quotes against the linked claim_ids and "
        "flag any recommendation revision the expert input would imply."
    )
    lines.append("")

    return "\n".join(lines)


def _render_question(lines: list[str], anchor: str, q: Question) -> None:
    lines.append(f"### {anchor}. {q.get('text', '').strip()}")
    priority = (q.get("priority") or "medium").upper()
    minutes = int(q.get("time_estimate_minutes") or 0)
    lines.append(f"- **Priority:** {priority}")
    lines.append(f"- **Time:** ~{minutes} min")
    topic = (q.get("topic") or "").strip()
    if topic:
        lines.append(f"- **Topic:** {topic}")
    why = (q.get("why_asking") or "").strip()
    if why:
        lines.append(f"- **Why we're asking:** {why}")
    probe = (q.get("follow_up_probe") or "").strip()
    if probe:
        lines.append(f"- **Follow-up probe:** {probe}")
    cids = q.get("linked_claim_ids") or []
    if cids:
        joined = ", ".join(f"[claim_id: {c}]" for c in cids)
        lines.append(f"- **Linked claims:** {joined}")
    lines.append("")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, n: int) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _stringify_gap_item(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("description", "text", "title", "evidence_gap", "gap"):
            v = raw.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _topic_from_gap(text: str) -> str:
    """Pull a short noun-phrase topic from a gap statement.

    Examples:
      "Scotland-specific competitive landscape" → "Competitive landscape (Scotland)"
      "Customer concentration risk" → "Customer concentration"
      "Walk-away trigger validation" → "Walk-away trigger"
    """
    cleaned = re.sub(r"\s+", " ", text).strip().rstrip(".")
    # First 6 words as the topic — keeps it sub-line-length.
    parts = cleaned.split()
    if len(parts) <= 6:
        topic = cleaned
    else:
        topic = " ".join(parts[:6])
    # Capitalise just the first letter.
    return topic[:1].upper() + topic[1:]


def _gap_to_primary_question(text: str, topic: str, mode: str) -> str:
    """Turn a gap statement into a question.

    Heuristic patterns:
      - statements containing "landscape" / "market" → "What does {X} look like? Who are the dominant players?"
      - statements containing "concentration" / "exposure" → "How material is {X}, and what would change it?"
      - default → "What's your read on {topic} for this engagement?"
    """
    t = text.lower()
    short_topic = topic.lower()
    if "landscape" in t or "competitive" in t or "market" in t:
        return (
            f"What does {short_topic} look like in practice? Who are the dominant "
            f"players and how have shares moved over the last 12-24 months?"
        )
    if "concentration" in t or "exposure" in t or "dependency" in t:
        return (
            f"How material is {short_topic} when you've seen situations like "
            f"this — and what tends to change the answer?"
        )
    if "timing" in t or "timeline" in t:
        return (
            f"What's your realistic read on the timeline implied by {short_topic}? "
            f"Where do you most often see slippage?"
        )
    if "regulator" in t or "compliance" in t or "legal" in t:
        return (
            f"How would you size the regulatory exposure around {short_topic}? "
            f"What's the typical resolution path?"
        )
    return (
        f"What's your read on {short_topic} for this engagement? "
        f"Where is the analyst's coverage likely thin?"
    )


def _gap_to_probe_question(text: str, topic: str, mode: str) -> str:
    """Optional follow-up probe — empty string if no useful probe fits."""
    t = text.lower()
    if "competitive" in t or "landscape" in t:
        return (
            "Are there local players you'd watch that the big-name competitor "
            "tracker wouldn't catch?"
        )
    if "concentration" in t or "customer" in t:
        return (
            "What's the typical churn experience you've seen when a top-3 "
            "customer changes leadership on the buyer side?"
        )
    return ""


def _text_from_listish(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for k in ("text", "reason", "risk", "description"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _claim_ids_from_listish(item: Any) -> list[str]:
    """Pull claim_id references off a reason/risk dict if present.

    Tolerates: ``claim_ids`` (list), ``claim_id`` (single), ``source_citation``
    (single, as in W12 financial profile points)."""
    if not isinstance(item, dict):
        return []
    out: list[str] = []
    cids = item.get("claim_ids")
    if isinstance(cids, list):
        for c in cids:
            if isinstance(c, str) and c.strip():
                out.append(c.strip())
    for k in ("claim_id", "source_citation"):
        v = item.get(k)
        if isinstance(v, str) and v.strip() and v.strip() not in out:
            out.append(v.strip())
    return out


def _reason_to_pressure_test(text: str) -> str:
    """Convert a reason statement into a pressure-test question."""
    text = text.strip().rstrip(".")
    return (
        f"The recommendation rests on the view that {_lower_first(text)}. "
        f"How confident would you be in that — and what's the single piece of "
        f"data that would change your mind?"
    )


def _risk_to_pressure_test(text: str) -> str:
    text = text.strip().rstrip(".")
    return (
        f"We've flagged {_lower_first(text)} as a key risk. "
        f"From your seat, is that the right size of concern — overstated, "
        f"understated, or roughly right? What's the calibration data?"
    )


def _lower_first(s: str) -> str:
    if not s:
        return s
    return s[:1].lower() + s[1:]


def _synergy_phrase(payload: Any) -> str:
    """Best-effort string describing the synergy magnitude for M&A Section C."""
    syn = payload_get(payload, "synergy_estimate", default={}) or {}
    if isinstance(syn, dict):
        rev = syn.get("revenue_synergies") or []
        cost = syn.get("cost_synergies") or []
        if isinstance(rev, list) and isinstance(cost, list):
            rev_sum = sum(
                float(s.get("magnitude_gbp_m") or s.get("estimated_gbp_m") or 0)
                for s in rev if isinstance(s, dict)
            )
            cost_sum = sum(
                float(s.get("magnitude_gbp_m") or s.get("estimated_gbp_m") or 0)
                for s in cost if isinstance(s, dict)
            )
            if rev_sum or cost_sum:
                return f"~£{rev_sum + cost_sum:.0f}m in combined synergies"
    return "the synergies"


def _walkaway_phrase(payload: Any) -> str:
    ds = payload_get(payload, "deal_structure_implications", default={}) or {}
    if isinstance(ds, dict):
        wa = ds.get("walk_away_triggers") or []
        if isinstance(wa, list) and wa:
            first = wa[0]
            if isinstance(first, dict):
                first = first.get("description") or first.get("text") or ""
            if isinstance(first, str) and first.strip():
                return _truncate(first.strip().rstrip("."), 120)
    return "tied to the diligence findings in the memo"


def _top_competitor_name(payload: Any) -> str:
    """Pull a named competitor for growth_strategy Section C from
    ``competitive_landscape.competitors`` or the Porter's-five-forces
    block — falls back to "incumbent competitors"."""
    cl = payload_get(payload, "competitive_landscape", default={}) or {}
    if isinstance(cl, dict):
        comps = cl.get("competitors") or cl.get("named_competitors") or []
        if isinstance(comps, list):
            for c in comps:
                if isinstance(c, dict):
                    name = c.get("name") or c.get("company")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
                elif isinstance(c, str) and c.strip():
                    return c.strip()
    return "incumbent competitors"


def _geography_phrase(payload: Any, engagement_title: str) -> str:
    geo = payload_get(payload, "geography", "market_geography", default="")
    if isinstance(geo, str) and geo.strip():
        return geo.strip()
    # Pull from engagement title — e.g. "TargetCo Scotland".
    if engagement_title:
        for name in ("Scotland", "Ireland", "UK", "DACH", "Nordics", "Benelux",
                     "France", "Germany", "US", "USA", "Canada", "ANZ"):
            if name.lower() in engagement_title.lower():
                return name
    return "the target geography"


__all__ = [
    "InterviewGuideBuilder",
    "Question",
]
