"""Assemble DeliverableDocument from API/report dict (no LLM)."""

import re
from typing import Any

from deliverables.models import ClaimMapRow, CriteriaRow, DeliverableDocument, FindingBlock

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _looks_like_uuid(token: str) -> bool:
    return bool(_UUID_RE.fullmatch(token.strip()))


def _evidence_ref_summary(ids: list[Any]) -> str:
    n = sum(1 for x in ids if str(x).strip())
    if n <= 0:
        return ""
    return f"{n} cited excerpt{'s' if n != 1 else ''}"


def _refs_without_uuids(cids: list[Any]) -> str:
    """Human-readable ref line for PDFs — no raw UUIDs."""
    if not cids:
        return ""
    nonempty = [x for x in cids if str(x).strip()]
    if nonempty and all(_looks_like_uuid(str(x)) for x in nonempty):
        return f" ({_evidence_ref_summary(list(cids))})"
    parts = [str(x).strip() for x in cids[:4] if str(x).strip() and not _looks_like_uuid(str(x))]
    return f" ({', '.join(parts)})" if parts else ""


def build_deliverable_document(
    *,
    report: dict[str, Any],
    session_query: str,
    session_title: str,
) -> DeliverableDocument:
    cp = report.get("consulting_payload") if isinstance(report.get("consulting_payload"), dict) else {}
    rg = report.get("reasoning_graph") if isinstance(report.get("reasoning_graph"), dict) else {}

    exec_insights: list[str] = []
    ei = cp.get("executive_insights") if isinstance(cp, dict) else None
    if isinstance(ei, list):
        for row in ei[:5]:
            if isinstance(row, dict) and str(row.get("text", "")).strip():
                cids = row.get("claim_ids") if isinstance(row.get("claim_ids"), list) else []
                suffix = _refs_without_uuids(list(cids))
                exec_insights.append(str(row.get("text", "")).strip() + suffix)
    if len(exec_insights) < 3:
        for r in (report.get("key_reasons") or [])[: 5 - len(exec_insights)]:
            if isinstance(r, str) and r.strip():
                exec_insights.append(r.strip())

    exec_risks: list[str] = []
    krs = cp.get("key_risks_structured") if isinstance(cp, dict) else None
    if isinstance(krs, list):
        for row in krs[:2]:
            if isinstance(row, dict) and str(row.get("text", "")).strip():
                exec_risks.append(str(row.get("text", "")).strip())
    for r in (report.get("risks") or [])[: 2]:
        if isinstance(r, str) and r.strip() and len(exec_risks) < 2:
            exec_risks.append(r.strip())

    findings: list[FindingBlock] = []
    slots = rg.get("reasoning_slots") if isinstance(rg.get("reasoning_slots"), list) else []
    for s in slots[:12]:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("slot_id", "")).replace("_", " ").title() or "Finding"
        summ = str(s.get("summary", "")).strip()
        cids = s.get("claim_ids") if isinstance(s.get("claim_ids"), list) else []
        nonempty_c = [x for x in cids if str(x).strip()]
        if nonempty_c and all(_looks_like_uuid(str(x)) for x in nonempty_c):
            ref = _evidence_ref_summary(list(cids))
        else:
            ref = ", ".join(str(x) for x in cids[:6] if str(x).strip() and not _looks_like_uuid(str(x)))
        findings.append(
            FindingBlock(
                title=sid,
                explanation=summ[:2000],
                evidence_refs=ref,
                mini_conclusion=summ[:280] + ("…" if len(summ) > 280 else ""),
            )
        )
    if not findings:
        for i, r in enumerate((report.get("key_reasons") or [])[:6]):
            if isinstance(r, str) and r.strip():
                findings.append(
                    FindingBlock(
                        title=f"Insight {i + 1}",
                        explanation=r.strip()[:1500],
                        evidence_refs="",
                        mini_conclusion=r.strip()[:200],
                    )
                )

    criteria_rows: list[CriteriaRow] = []
    dc = cp.get("decision_criteria") if isinstance(cp.get("decision_criteria"), list) else []
    for row in dc[:20]:
        if not isinstance(row, dict):
            continue
        criteria_rows.append(
            CriteriaRow(
                criterion=str(row.get("criterion", ""))[:500],
                score=str(row.get("weight", ""))[:80],
                notes=str(row.get("how_met", ""))[:1500],
            )
        )

    appendix_claim_map: list[ClaimMapRow] = []
    csup = report.get("claim_support") if isinstance(report.get("claim_support"), list) else []
    for row in csup[:40]:
        if not isinstance(row, dict):
            continue
        ct = str(row.get("claim_text", ""))[:500]
        eids = row.get("evidence_object_ids") if isinstance(row.get("evidence_object_ids"), list) else []
        ev_line = _evidence_ref_summary(list(eids)) or "—"
        appendix_claim_map.append(ClaimMapRow(claim=ct, evidence=ev_line))

    appendix_sources: list[str] = []
    for s in report.get("sources") or []:
        if isinstance(s, dict):
            appendix_sources.append(f"{s.get('title', '')} ({s.get('type', '')})")
        elif isinstance(s, str):
            appendix_sources.append(s)

    return DeliverableDocument(
        cover_title=session_title[:200] or "Argus Decision Deliverable",
        cover_subtitle=(session_query[:180] + "…") if len(session_query) > 180 else session_query,
        cover_date=DeliverableDocument.default_date(),
        cover_project=session_title[:120] or "Project",
        exec_insights=exec_insights[:5],
        exec_recommendation=str(report.get("recommendation", ""))[:2000],
        exec_risks=exec_risks[:2],
        key_question=session_query[:4000],
        findings=findings,
        criteria_rows=criteria_rows,
        recommendation_body=str(report.get("recommendation", ""))[:3000],
        risks_body=[str(x) for x in (report.get("risks") or []) if str(x).strip()][:20],
        appendix_sources=appendix_sources[:50],
        appendix_claim_map=appendix_claim_map,
        caveats=str(report.get("caveats", ""))[:4000],
    )
