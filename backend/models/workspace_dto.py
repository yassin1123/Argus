"""Presentation-layer DTOs for the session workspace UI (labels and summaries, not raw agent internals)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.trust_labels import build_trust_labels, evidence_quality_mix_label


class WorkspaceMetaDTO(BaseModel):
    title: str = ""
    status_label: str = ""
    report_mode_label: str = ""
    pipeline_stage_label: str = ""
    source_count: int = 0
    file_count: int = 0


class AnswerCanvasDTO(BaseModel):
    headline: str = ""
    summary: str = ""
    confidence_display: str = ""
    next_steps_count: int = 0
    key_points: list[str] = Field(default_factory=list)


class TrustRailDTO(BaseModel):
    confidence_label: str = ""
    verification_summary: str = ""
    evidence_strength_label: str = ""
    caveats_preview: str = ""
    unsupported_claims_count: int = 0
    verification_overall_label: str = ""
    contradiction_severity_label: str = ""
    what_capped_confidence: str = ""
    claims_verified_hint: str = ""


class EvidenceItemDTO(BaseModel):
    ordinal: int = 0
    source_label: str = ""
    excerpt: str = ""
    kind_label: str = ""


class EvidenceRailDTO(BaseModel):
    total: int = 0
    items: list[EvidenceItemDTO] = Field(default_factory=list)


class WorkspacePresentationDTO(BaseModel):
    meta: WorkspaceMetaDTO
    answer: AnswerCanvasDTO | None = None
    trust: TrustRailDTO | None = None
    evidence: EvidenceRailDTO


def _mode_label(mode: str | None) -> str:
    if not mode:
        return "General"
    return " ".join(w[:1].upper() + w[1:] for w in mode.replace("-", "_").split("_") if w)


def _pipeline_label(state: str | None, status: str) -> str:
    if status == "complete":
        return "Ready"
    if status == "failed":
        return "Failed"
    if status == "insufficient":
        return "Needs more evidence"
    if status == "draft":
        return "Draft"
    mapping = {
        "plan_ready": "Planning",
        "analysis_v1_done": "Analysis",
        "critique_done": "Review",
        "analysis_v2_done": "Refining",
        "gates_validated": "Validating",
        "critic_post_done": "Review",
        "verification_done": "Verification",
        "evidence_insufficient": "Blocked",
    }
    if state and state in mapping:
        return mapping[state]
    if status == "processing":
        return "Running"
    return status.replace("_", " ").title()


def _verification_sentence(ver: dict[str, Any] | None) -> str:
    if not ver:
        return ""
    overall = str(ver.get("overall", "")).strip()
    gap = str(ver.get("gap_summary", "")).strip()
    if overall and gap:
        return f"{overall.capitalize()}: {gap[:280]}"
    return overall or gap or ""


def _strength_from_scores(evidence_objects: list[dict[str, Any]]) -> str:
    return evidence_quality_mix_label(evidence_objects)


def build_presentation_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """Derive presentation DTOs from a `get_session_detail` dict."""
    status = str(detail.get("status") or "")
    report_mode = detail.get("report_mode")
    pipeline_state = detail.get("pipeline_state")
    report = detail.get("report") if isinstance(detail.get("report"), dict) else None
    ev_objs = detail.get("evidence_objects") if isinstance(detail.get("evidence_objects"), list) else []
    files = detail.get("uploaded_files") if isinstance(detail.get("uploaded_files"), list) else []
    ver = report.get("verification") if report and isinstance(report.get("verification"), dict) else None

    meta = WorkspaceMetaDTO(
        title=str(detail.get("title") or ""),
        status_label=status.replace("_", " ").title() if status else "",
        report_mode_label=_mode_label(str(report_mode) if report_mode else None),
        pipeline_stage_label=_pipeline_label(
            str(pipeline_state) if pipeline_state else None,
            status,
        ),
        source_count=len(ev_objs),
        file_count=len(files),
    )

    answer: AnswerCanvasDTO | None = None
    if report:
        kr = report.get("key_reasons") or []
        key_points = [str(x) for x in kr[:8]] if isinstance(kr, list) else []
        ns = report.get("next_steps") or []
        answer = AnswerCanvasDTO(
            headline=str(report.get("recommendation") or ""),
            summary=str(report.get("summary") or ""),
            confidence_display=str(report.get("confidence_level") or ""),
            next_steps_count=len(ns) if isinstance(ns, list) else 0,
            key_points=key_points,
        )

    meta = detail.get("metadata") if isinstance(detail.get("metadata"), dict) else {}
    sev = meta.get("contradiction_severity")
    try:
        sev_f = float(sev) if sev is not None else None
    except (TypeError, ValueError):
        sev_f = None
    ev_dicts = [dict(x) for x in ev_objs if isinstance(x, dict)]
    labels = build_trust_labels(
        report=report,
        verification=ver,
        evidence_objects=ev_dicts,
        contradiction_severity=sev_f,
    )

    trust: TrustRailDTO | None = None
    if report:
        to = meta.get("trust_object") if isinstance(meta.get("trust_object"), dict) else None
        trust = TrustRailDTO(
            confidence_label=str(
                (to.get("confidence_display") or to.get("confidence_level")) if to else report.get("confidence_level")
                or ""
            ),
            verification_summary=_verification_sentence(ver),
            evidence_strength_label=str(
                to.get("evidence_strength_label") if to else labels.get("evidence_strength_label") or ""
            )
            or _strength_from_scores(ev_dicts),
            caveats_preview=str(report.get("caveats") or "")[:400],
            unsupported_claims_count=int(
                to.get("unsupported_claims_count")
                if to and to.get("unsupported_claims_count") is not None
                else report.get("unsupported_claim_count") or 0
            ),
            verification_overall_label=str(
                to.get("verification_overall_label") if to else labels.get("verification_overall_label") or ""
            ),
            contradiction_severity_label=str(
                to.get("contradiction_severity_label") if to else labels.get("contradiction_severity_label") or ""
            ),
            what_capped_confidence=str(
                to.get("what_capped_confidence") if to else labels.get("what_capped_confidence") or ""
            ),
            claims_verified_hint=str(to.get("claims_verified_hint") or "") if to else "",
        )

    items: list[EvidenceItemDTO] = []
    for i, row in enumerate(ev_objs[:24]):
        if not isinstance(row, dict):
            continue
        st = str(row.get("source_type") or "source")
        kind = "Web page" if st.lower() == "web" else "Document"
        items.append(
            EvidenceItemDTO(
                ordinal=i + 1,
                source_label=str(row.get("source_title") or "Source")[:120],
                excerpt=str(row.get("quote") or row.get("claim") or "")[:500],
                kind_label=kind,
            )
        )

    evidence = EvidenceRailDTO(total=len(ev_objs), items=items)

    dto = WorkspacePresentationDTO(meta=meta, answer=answer, trust=trust, evidence=evidence)
    return dto.model_dump(mode="json")
