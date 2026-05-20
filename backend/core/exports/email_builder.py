"""EmailBuilder — composes the client cover email body.

Mode-aware: M&A emails reference the valuation range and a walk-away
condition; growth_strategy emails reference market context and the top
competitive risk; general mode falls back to a generic structure.

Brevity is the wedge: the body is held to ~250 words. The signature
block, sources line, and confidentiality footer don't count toward
that budget — the body is the lede + recommendation paragraph + caveat
paragraph + attached bundle + next-step line.

Citations are not surfaced inline (partners don't want footnote
markers in client-facing prose). The builder still tracks which claim
ids the lede/recommendation/caveat reference so the artifact row carries
a non-zero ``claim_citation_count``; the "Sources" line at the bottom
points the reader at the attached memo for the full registry.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ._base import ClaimCitation, payload_get
from .one_pager_renderer import classify_recommendation, get_recommendation_text

_TEMPLATE_DIR = Path(__file__).parent / "email_templates"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,  # markdown output — autoescape would mangle ** and #
    trim_blocks=True,
    lstrip_blocks=True,
)

_MODE_TEMPLATES = {
    "m_and_a_diligence": "_m_and_a.md.j2",
    "growth_strategy":   "_growth_strategy.md.j2",
}
_DEFAULT_TEMPLATE = "_general.md.j2"

# Default attachment bundle when the payload doesn't specify
# ``_attached_artifacts``. Tracks the four W10–W12 artifact families.
_DEFAULT_ATTACHMENTS: dict[str, list[str]] = {
    "m_and_a_diligence": [
        "Diligence memo (PDF)",
        "Executive 1-pager (PDF)",
        "Deck (PPTX, 11 slides)",
        "Financial model (XLSX, 10 sheets — DCF, comparables, sensitivity, synergies)",
    ],
    "growth_strategy": [
        "Strategy memo (PDF)",
        "Executive 1-pager (PDF)",
        "Deck (PPTX, 9 slides — market landscape, Porter's Five Forces, options)",
        "Financial model (XLSX, 5 sheets)",
    ],
    "general": [
        "Memo (PDF)",
        "Executive 1-pager (PDF)",
        "Deck (PPTX)",
        "Financial model (XLSX)",
    ],
}

_VERDICT_PHRASE = {
    "green":   "to proceed",
    "amber":   "to proceed with conditions",
    "red":     "to walk away",
    "neutral": "the path forward",
}

_ARTIFACT_LABELS: dict[str, str] = {
    "memo":          "Diligence memo",
    "one_pager":     "Executive 1-pager",
    "deck":          "Deck",
    "excel_model":   "Financial model",
    "email":         "Cover email",
}


def _relative_age(generated_at: Any) -> str:
    """Render a generated_at timestamp as a relative phrase.
    Accepts datetimes, ISO strings, or anything else (returns ""
    for unparseable input)."""
    from datetime import datetime, timezone

    dt: datetime | None = None
    if isinstance(generated_at, datetime):
        dt = generated_at
    elif isinstance(generated_at, str):
        try:
            dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - dt
    days = delta.days
    if days >= 1:
        return f"{days} day{'s' if days != 1 else ''} ago"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return "just now"


class EmailBuilder:
    """Pure builder — produces subject, markdown body, and the context
    dict that drives the Jinja template. The exporter wraps this and
    turns the markdown into an HTML render for the html format.
    """

    def __init__(
        self,
        payload: Any,
        firm_branding: dict[str, Any] | None,
        citations: list[ClaimCitation] | None,
        available_artifacts: list[dict[str, Any]] | None = None,
    ) -> None:
        self._payload = payload
        self._branding = dict(firm_branding or {})
        self._citations = list(citations or [])
        self._cited_ids: list[str] = []  # populated during build_*
        # W13/D2: the service layer passes the list of already-generated
        # ready artifacts for the same session. Callers from tests can
        # pass an explicit list; the builder will also fall back to a
        # ``_available_artifacts`` payload key for fixture convenience.
        # Tracking whether the caller / payload explicitly set this
        # lets us distinguish "use service truth (possibly empty)" from
        # "no service truth provided — use mode default".
        if available_artifacts is not None:
            self._available_artifacts: list[dict[str, Any]] = list(available_artifacts)
            self._available_artifacts_explicit: bool = True
        else:
            # ``payload_get`` treats empty lists as missing — but the
            # spec needs an empty list to mean "service confirmed zero
            # ready artifacts" (omit the section), distinct from "key
            # absent" (use the W13/D1 default bundle). Use direct dict
            # / attr access here to preserve that distinction.
            if isinstance(payload, dict):
                payload_av = payload.get("_available_artifacts", None)
            else:
                payload_av = getattr(payload, "_available_artifacts", None)
            if payload_av is not None:
                self._available_artifacts = list(payload_av)
                self._available_artifacts_explicit = True
            else:
                self._available_artifacts = []
                self._available_artifacts_explicit = False

        # Mode resolution mirrors the one_pager/excel builders.
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
        self.partner_name: str = str(
            self._branding.get("_partner_name")
            or payload_get(payload, "_partner_name", default="[Partner name]")
            or "[Partner name]"
        )
        self.partner_title: str = str(
            self._branding.get("_partner_title")
            or payload_get(payload, "_partner_title", default="Partner")
            or "Partner"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def citation_count(self) -> int:
        return len(self._cited_ids)

    @property
    def cited_claim_ids(self) -> list[str]:
        return list(self._cited_ids)

    def build_subject(self) -> str:
        """Subject line — separate from body so the mail client / API
        client can populate the subject field directly."""
        subject_target = self.target_name or self.engagement_title or "Engagement"
        if self.mode == "m_and_a_diligence":
            return f"{subject_target} diligence — recommendation and supporting materials"
        if self.mode == "growth_strategy":
            return f"{subject_target} — strategy review and supporting materials"
        return f"{subject_target} — findings and supporting materials"

    def build_context(self) -> dict[str, Any]:
        """Build the Jinja context dict. Resets ``_cited_ids`` so
        repeated calls don't double-count."""
        self._cited_ids = []

        rec_text = get_recommendation_text(self._payload)
        verdict = classify_recommendation(rec_text)
        verdict_phrase = _VERDICT_PHRASE.get(verdict, _VERDICT_PHRASE["neutral"])

        # Lede paragraph — 1-2 sentences.
        target_for_lede = self.target_name or self.engagement_title or "this engagement"
        lede = (
            f"Please find attached our diligence package on **{target_for_lede}**. "
            f"On the headline question, our recommendation is **{verdict_phrase}** — "
            f"the supporting analysis, valuation, and risk register are in the materials below."
        )
        if self.mode == "growth_strategy":
            lede = (
                f"Please find attached our strategy review on **{target_for_lede}**. "
                f"On the headline question of {verdict_phrase}, our position and the "
                f"supporting market and competitive analysis are in the materials below."
            )

        # Recommendation paragraph — 3-4 sentences, mode-aware content.
        recommendation_paragraph = self._build_recommendation_paragraph(rec_text, verdict)

        # Critical caveat paragraph — 2-3 sentences, mode-aware.
        caveat_paragraph = self._build_caveat_paragraph()

        # Attached bundle — payload override, service truth, or mode default.
        attachments = self._resolve_attachments()
        has_attachments = bool(attachments)

        # Suggested next step.
        next_step = (
            "Happy to discuss any of this — "
            "I have time **Tuesday or Thursday next week** for a call if helpful."
        )

        # Signature block.
        signature = {
            "partner_name": self.partner_name,
            "title": self.partner_title,
            "firm_name": self.firm_name,
        }

        # Sources / confidentiality lines.
        n_claims = len(self._citations)
        sources_line = (
            f"_Backed by {n_claims} verified claim{'s' if n_claims != 1 else ''} "
            f"with traceable sources — full citations in the attached memo._"
        )
        confidentiality_footer = (
            f"_Confidential — prepared by {self.firm_name} for the named addressee. "
            f"Do not forward without written permission._"
        )

        return {
            "subject": self.build_subject(),
            "lede": lede,
            "recommendation_paragraph": recommendation_paragraph,
            "caveat_paragraph": caveat_paragraph,
            "attachments": attachments,
            "has_attachments": has_attachments,
            "next_step": next_step,
            "signature": signature,
            "sources_line": sources_line,
            "confidentiality_footer": confidentiality_footer,
            "verdict": verdict,
            "mode": self.mode,
        }

    def build_markdown(self) -> str:
        """Render the email body as markdown."""
        ctx = self.build_context()
        template_name = _MODE_TEMPLATES.get(self.mode, _DEFAULT_TEMPLATE)
        tmpl = _ENV.get_template(template_name)
        return tmpl.render(**ctx)

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_recommendation_paragraph(self, rec_text: str, verdict: str) -> str:
        """3-4 sentence recommendation expansion. M&A references the
        valuation range + structure; growth references the strategic
        direction; general mode pulls the top reason."""
        top_reason = self._top_reason()
        if top_reason:
            self._note_claim_for(top_reason_source := self._reason_source_id(top_reason))
            del top_reason_source

        if self.mode == "m_and_a_diligence":
            v_low, v_base, v_high, methodology = self._valuation_range_fields()
            self._note_claim_for("valuation")  # citation bucket marker
            parts = [
                f"On valuation: our base-case range is £{v_low}–£{v_high}m "
                f"with a central estimate of £{v_base}m{(' (' + methodology + ')') if methodology else ''}."
            ]
            if top_reason:
                parts.append(f"The thesis rests on {top_reason.rstrip('.').lower()}.")
            parts.append(
                "The memo lays out the supporting financial trajectory, "
                "diligence findings, and integration approach in full."
            )
            return " ".join(parts)

        if self.mode == "growth_strategy":
            direction = self._strategic_direction()
            parts = []
            if direction:
                parts.append(f"On strategic direction: {direction}.")
            if top_reason:
                parts.append(f"The case rests on {top_reason.rstrip('.').lower()}.")
            parts.append(
                "The deck walks through the market landscape, competitive position, "
                "and the option set we'd prioritise."
            )
            return " ".join(parts) if parts else (
                "The strategy review lays out the recommended direction, supporting "
                "market analysis, and the option set we'd prioritise."
            )

        # General mode.
        parts = []
        if top_reason:
            parts.append(f"The recommendation rests on {top_reason.rstrip('.').lower()}.")
        parts.append(
            "The attached memo lays out the supporting evidence, alternatives "
            "considered, and the conditions under which our recommendation would change."
        )
        return " ".join(parts)

    def _build_caveat_paragraph(self) -> str:
        """2-3 sentences naming the most important risk or condition.
        Mode-aware: M&A names a walk-away trigger; growth names the top
        competitive risk (Porter's-derived if available); general mode
        names the top risk."""
        top_risk = self._top_risk()
        if top_risk:
            self._note_claim_for(self._risk_source_id(top_risk))

        if self.mode == "m_and_a_diligence":
            if top_risk:
                return (
                    f"**Critical caveat:** {top_risk.rstrip('.').rstrip()}. "
                    f"This is the walk-away trigger — if diligence on this point doesn't hold up, "
                    f"the base-case valuation needs to come down materially before we'd close."
                )
            return (
                "**Critical caveat:** there is no single deal-breaker in the file, but the "
                "valuation is sensitive to working-capital assumptions. The sensitivity tab "
                "in the model lays out the band you should be comfortable across."
            )

        if self.mode == "growth_strategy":
            competitive_force = self._top_competitive_force()
            if competitive_force:
                self._note_claim_for("competitive")
                return (
                    f"**Critical caveat:** the top competitive risk is {competitive_force.lower()}. "
                    f"Our recommendation holds only if monitoring on this front is in place; "
                    f"if it shifts adversely, the strategic direction should be revisited."
                )
            if top_risk:
                return (
                    f"**Critical caveat:** {top_risk.rstrip('.').rstrip()}. "
                    f"This is the watch-item — if it materialises, the recommended path needs revisiting."
                )
            return (
                "**Critical caveat:** market conditions can shift the recommended direction. "
                "We'd suggest a six-month review cadence against the indicators flagged in the deck."
            )

        if top_risk:
            return (
                f"**Critical caveat:** {top_risk.rstrip('.').rstrip()}. "
                f"This is the watch-item — if it materialises, the recommendation should be revisited."
            )
        return (
            "**Critical caveat:** the recommendation holds under the assumptions laid out in the memo. "
            "If any of them change materially, the conclusion needs a fresh look."
        )

    # ------------------------------------------------------------------
    # Field extractors
    # ------------------------------------------------------------------

    def _top_reason(self) -> str:
        reasons = payload_get(self._payload, "key_reasons", default=[]) or []
        if isinstance(reasons, list) and reasons:
            first = reasons[0]
            if isinstance(first, dict):
                return str(first.get("text") or first.get("reason") or "")
            return str(first)
        return ""

    def _top_risk(self) -> str:
        risks = payload_get(self._payload, "risks", default=[]) or []
        if isinstance(risks, list) and risks:
            first = risks[0]
            if isinstance(first, dict):
                return str(first.get("text") or first.get("risk") or "")
            return str(first)
        return ""

    def _reason_source_id(self, reason: Any) -> str:
        if isinstance(reason, dict):
            return str(reason.get("source_citation") or reason.get("claim_id") or "reasons")
        return "reasons"

    def _risk_source_id(self, risk: Any) -> str:
        if isinstance(risk, dict):
            return str(risk.get("source_citation") or risk.get("claim_id") or "risks")
        return "risks"

    def _valuation_range_fields(self) -> tuple[str, str, str, str]:
        vr = payload_get(self._payload, "valuation_range", default={}) or {}
        if not isinstance(vr, dict):
            return ("?", "?", "?", "")
        def _num(d: Any, key: str = "gbp_m") -> str:
            if isinstance(d, dict):
                v = d.get(key)
                if isinstance(v, (int, float)):
                    return f"{v:.0f}"
            return "?"
        low = _num(vr.get("low"))
        base = _num(vr.get("base"))
        high = _num(vr.get("high"))
        methodology = ""
        base_block = vr.get("base") if isinstance(vr.get("base"), dict) else {}
        if isinstance(base_block, dict):
            methodology = str(base_block.get("methodology") or "")
        return (low, base, high, methodology)

    def _strategic_direction(self) -> str:
        # Growth-mode payloads sometimes carry a "recommended_direction" or
        # "strategic_recommendation" field; otherwise we pull from the summary.
        for key in ("recommended_direction", "strategic_recommendation"):
            v = payload_get(self._payload, key, default="")
            if isinstance(v, str) and v.strip():
                return v.strip().rstrip(".")
        summary = payload_get(self._payload, "summary", default="")
        if isinstance(summary, str) and summary.strip():
            # Use only the first sentence to keep the email tight.
            first_sentence = re.split(r"(?<=[.!?])\s+", summary.strip())[0]
            return first_sentence.rstrip(".")
        return ""

    def _top_competitive_force(self) -> str:
        # Porter's-derived if available. Looks at consulting_payload.frameworks.porters
        # or directly at the payload's competitive_forces block.
        for key in ("top_competitive_force", "competitive_force"):
            v = payload_get(self._payload, key, default="")
            if isinstance(v, str) and v.strip():
                return v.strip()
        frameworks = payload_get(self._payload, "frameworks", default={}) or {}
        porters = (frameworks or {}).get("porters_five_forces") if isinstance(frameworks, dict) else None
        if isinstance(porters, dict):
            forces = porters.get("forces") or []
            if isinstance(forces, list):
                # Pick the highest-intensity force named in the block.
                ranked: list[tuple[int, str]] = []
                intensity_order = {"high": 3, "medium": 2, "low": 1}
                for f in forces:
                    if not isinstance(f, dict):
                        continue
                    name = str(f.get("name") or f.get("force") or "").strip()
                    intensity = str(f.get("intensity") or "").lower().strip()
                    if name:
                        ranked.append((intensity_order.get(intensity, 0), name))
                if ranked:
                    ranked.sort(reverse=True)
                    return ranked[0][1]
        return ""

    def _resolve_attachments(self) -> list[str]:
        # Priority 1: caller-supplied (or payload-supplied) hardcoded list
        # — used by tests and one-off engagements that want a custom bundle.
        explicit = payload_get(self._payload, "_attached_artifacts", default=None)
        if isinstance(explicit, list) and explicit:
            out: list[str] = []
            for item in explicit:
                if isinstance(item, dict):
                    label = item.get("label") or item.get("name") or ""
                    if not label:
                        continue
                    detail = item.get("detail") or item.get("format") or ""
                    out.append(f"{label} ({detail})" if detail else str(label))
                elif isinstance(item, str):
                    out.append(item)
            if out:
                return out

        # Priority 2: service-layer / fixture-provided ``available_artifacts``
        # — derives the bundle from what actually exists in the engagement.
        # Order is logical (memo → 1-pager → deck → excel_model), not
        # generation-order — partners expect the memo first regardless of
        # when each piece was rendered.
        #
        # If the caller explicitly passed an empty list, we honour it
        # (the email omits the attachment section entirely — see
        # ``build_context`` where ``attachments=[]`` flips the
        # ``has_attachments`` flag the template branches on).
        if self._available_artifacts_explicit:
            return self._render_available_artifacts()

        # Priority 3: mode-default placeholder text — used when the
        # service layer hasn't been wired yet OR the caller passed
        # nothing explicit. This is the W13/D1 behaviour.
        return list(_DEFAULT_ATTACHMENTS.get(self.mode, _DEFAULT_ATTACHMENTS["general"]))

    def _render_available_artifacts(self) -> list[str]:
        """Turn the service-layer artifact rows into the numbered bundle.

        Each row carries: ``artifact_type``, ``format``, ``metadata``,
        ``generated_at`` (optional), ``is_stale`` (optional bool already
        computed by the service), and ``stale_reason`` (optional).

        We render in the logical order memo → 1-pager → deck →
        excel_model regardless of generation order, and annotate stale
        artifacts with "(may need refresh)".
        """
        order = ["memo", "one_pager", "deck", "excel_model"]
        by_type: dict[str, list[dict[str, Any]]] = {}
        for art in self._available_artifacts:
            t = str(art.get("artifact_type") or "").strip()
            if t and t != "email":
                by_type.setdefault(t, []).append(art)

        out: list[str] = []
        for t in order:
            for art in by_type.get(t, []):
                out.append(self._format_artifact_line(art))
        # Surface any artifact types we didn't list explicitly (forward-
        # compat for future formats — they land at the end so the logical
        # order above isn't disturbed).
        for t, rows in by_type.items():
            if t in order:
                continue
            for art in rows:
                out.append(self._format_artifact_line(art))
        return out

    def _format_artifact_line(self, art: dict[str, Any]) -> str:
        """One bullet for the numbered list. Format mirrors the W13/D1
        default strings: ``<Label> (<format/detail>)`` with an optional
        stale annotation at the end."""
        atype = str(art.get("artifact_type") or "").strip()
        fmt = str(art.get("format") or "").strip()
        md = art.get("metadata") or {}
        label = _ARTIFACT_LABELS.get(atype, atype.replace("_", " ").title() or "Artifact")
        # Pull a useful detail string from metadata when available.
        detail_bits: list[str] = []
        if fmt:
            detail_bits.append(fmt.upper())
        if isinstance(md, dict):
            slide_count = md.get("slide_count")
            sheet_count = md.get("sheet_count")
            page_count = md.get("page_count")
            if slide_count:
                detail_bits.append(f"{slide_count} slides")
            if sheet_count:
                detail_bits.append(f"{sheet_count} sheets")
            if page_count and atype != "email":
                detail_bits.append(f"{page_count} page" + ("s" if page_count != 1 else ""))
        line = label
        if detail_bits:
            line += " (" + ", ".join(detail_bits) + ")"

        if art.get("is_stale"):
            age_phrase = ""
            generated_at = art.get("generated_at")
            if generated_at is not None:
                age_phrase = _relative_age(generated_at)
                if age_phrase:
                    age_phrase = f", generated {age_phrase}"
            line += f" — may need refresh{age_phrase}"

        return line

    # ------------------------------------------------------------------
    # Citation bookkeeping
    # ------------------------------------------------------------------

    def _note_claim_for(self, source_token: str) -> None:
        """Record a citation tied to a payload section. The mapping is
        deliberately coarse: a "valuation" token counts as one cited
        claim for the artifact row even though valuation involves
        multiple claim_ids in the underlying memo — partners don't
        want inline markers, and the artifact-row count is a coverage
        proxy, not an exhaustive list.
        """
        if not source_token:
            return
        # If the token matches a real claim_id, prefer that; else use
        # the token verbatim as a synthetic id so we have stable
        # bookkeeping for the artifact row.
        for c in self._citations:
            if c.claim_id == source_token:
                if c.claim_id not in self._cited_ids:
                    self._cited_ids.append(c.claim_id)
                return
        if source_token not in self._cited_ids:
            self._cited_ids.append(source_token)


__all__ = ["EmailBuilder"]
