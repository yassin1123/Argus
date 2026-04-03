"""Lightweight evidence graph (v1) derived from claims, verification, and evidence objects."""

from __future__ import annotations

from typing import Any

from models.evidence import EvidenceObject


def build_evidence_graph_v1(
    *,
    analysis: dict[str, Any],
    verification: dict[str, Any],
    claim_support: list[dict[str, Any]],
    evidence_objects: list[EvidenceObject],
) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    trust_scores: dict[str, Any] = {}
    seen: set[str] = set()

    def add_entity(eid: str, kind: str, label: str) -> None:
        if eid in seen:
            return
        seen.add(eid)
        entities.append({"id": eid, "kind": kind, "label": label[:280]})

    rec = str(analysis.get("recommendation") or "").strip()
    if rec:
        add_entity("recommendation:main", "recommendation", rec)

    for o in evidence_objects:
        if not o.id:
            continue
        eid = str(o.id)
        add_entity(eid, "evidence", (o.quote or o.source_title or eid)[:200])
        sc = float(o.source_score or 0.0)
        tier = "high" if sc >= 0.55 else "medium" if sc >= 0.3 else "low"
        trust_scores[eid] = {"source_score": sc, "tier": tier, "source_type": o.source_type or ""}

    for row in claim_support or []:
        cid = str(row.get("claim_id") or "").strip()
        ct = str(row.get("claim_text") or "").strip()
        ce = cid if cid else (f"claim:h{abs(hash(ct)) % 10_000_000}" if ct else "")
        if not ce:
            continue
        add_entity(ce, "claim", (ct or ce)[:200])
        st = str(row.get("support_type") or "")
        if rec:
            edges.append({"from": "recommendation:main", "to": ce, "rel": "informs", "support_type": st})
        for eid in row.get("evidence_object_ids") or []:
            sid = str(eid).strip()
            if sid:
                edges.append({"from": ce, "to": sid, "rel": "supported_by"})

    for a in verification.get("claim_assessments") or []:
        if not isinstance(a, dict):
            continue
        claim_txt = str(a.get("claim", ""))[:120]
        verdict = str(a.get("verdict", "")).lower()
        vce = f"verifier:h{abs(hash(claim_txt)) % 10_000_000}"
        add_entity(vce, "verifier_assessment", f"{verdict}: {claim_txt}")
        for eid in a.get("evidence_ids") or []:
            sid = str(eid).strip()
            if sid:
                rel = "contradicts" if verdict in ("unsupported", "overstates") else "supports"
                edges.append({"from": vce, "to": sid, "rel": rel, "verdict": verdict})

    for t in verification.get("contradictions") or []:
        if str(t).strip():
            tid = f"tension:h{abs(hash(str(t))) % 10_000_000}"
            add_entity(tid, "tension", str(t)[:200])
            if rec:
                edges.append({"from": tid, "to": "recommendation:main", "rel": "weakens"})

    return {
        "version": 1,
        "entities": entities[:100],
        "edges": edges[:250],
        "trust_scores": trust_scores,
    }
