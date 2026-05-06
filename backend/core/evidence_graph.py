"""Evidence graph builders.

`build_evidence_graph_v1` produces the internal entities/edges shape persisted
to JSONB and consumed by exports.

`build_ui_evidence_graph` produces the normalized claim/evidence/source graph
consumed by the workspace UI tab — color-codable nodes, simple edges, stats.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

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


# -----------------------------------------------------------------------------
# UI graph: claim ↔ evidence ↔ source. Color-codable by verifier verdict.
# -----------------------------------------------------------------------------

_SOURCE_NODE_PREFIX = "src::"


def _slugify_source(title: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
    return base[:60] or "unknown"


def _str(x: Any) -> str:
    return str(x) if x is not None else ""


def _norm_verdict(v: Any) -> str:
    s = _str(v).strip().lower()
    if s in ("supported", "weak", "unsupported", "overstates", "contradicts"):
        return s
    return ""


def _ensure_list(x: Any) -> list[Any]:
    return x if isinstance(x, list) else []


def build_ui_evidence_graph(
    *,
    reasoning_graph: dict[str, Any] | None,
    evidence_objects: Iterable[dict[str, Any]] | None,
    claim_support_rows: Iterable[dict[str, Any]] | None,
    consulting_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine persisted artifacts into a single normalized graph for the UI.

    Output:
      {
        "nodes": [{"id", "type": "claim|evidence|source", "label",
                    "verifier_verdict"?, "confidence"?, "support_type"?, ...}],
        "edges": [{"from", "to", "kind": "cites|supports|contradicts"}],
        "stats": {"claims", "evidence", "sources", "supported", "weak", "unsupported"},
      }
    """
    rg = reasoning_graph or {}
    cs_list = list(claim_support_rows or [])
    cp = consulting_payload or {}

    evidence_by_id: dict[str, dict[str, Any]] = {}
    for e in evidence_objects or []:
        eid = _str(e.get("id"))
        if eid:
            evidence_by_id[eid] = e

    cs_by_claim: dict[str, dict[str, Any]] = {}
    for row in cs_list:
        cid = _str(row.get("claim_id")).strip()
        if cid:
            cs_by_claim[cid] = row

    rg_claims = _ensure_list(rg.get("claims"))
    claims: list[dict[str, Any]] = []
    seen_claim_ids: set[str] = set()

    for c in rg_claims:
        if not isinstance(c, dict):
            continue
        cid = _str(c.get("claim_id")).strip()
        if not cid or cid in seen_claim_ids:
            continue
        seen_claim_ids.add(cid)
        eids = [_str(x) for x in _ensure_list(c.get("evidence_object_ids")) if _str(x)]
        claims.append({"id": cid, "text": _str(c.get("text")), "evidence_ids": eids})

    for cid, row in cs_by_claim.items():
        if cid in seen_claim_ids:
            continue
        seen_claim_ids.add(cid)
        eids = [_str(x) for x in _ensure_list(row.get("evidence_object_ids")) if _str(x)]
        claims.append({"id": cid, "text": _str(row.get("claim_text")), "evidence_ids": eids})

    recommended = {
        _str(x).strip()
        for x in _ensure_list(cp.get("recommendation_claim_ids"))
        if _str(x).strip()
    }

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    referenced_evidence_ids: set[str] = set()
    sources_seen: dict[str, dict[str, Any]] = {}

    # Day 3: when ARGUS_USE_ENSEMBLE_VERDICT is on this returns the ensemble
    # verdict (mapped to legacy vocabulary); otherwise the raw LLM verdict.
    from core.feature_flags import effective_verdict as _effective_verdict

    for c in claims:
        cid = c["id"]
        cs_row = cs_by_claim.get(cid) or {}
        verdict = _norm_verdict(_effective_verdict(cs_row))
        support_type = _str(cs_row.get("support_type")) or "inference"
        weak = bool(cs_row.get("weak_or_unsupported")) or verdict in ("weak", "unsupported")
        nodes.append(
            {
                "id": cid,
                "type": "claim",
                "label": (c["text"] or cid)[:160],
                "verifier_verdict": verdict or "unknown",
                "support_type": support_type,
                "weak": weak,
                "in_recommendation": cid in recommended,
                "evidence_count": len(c["evidence_ids"]),
            }
        )
        for eid in c["evidence_ids"]:
            referenced_evidence_ids.add(eid)
            edges.append({"from": cid, "to": eid, "kind": "cites"})

    for eid in referenced_evidence_ids:
        e = evidence_by_id.get(eid)
        if not e:
            nodes.append(
                {
                    "id": eid,
                    "type": "evidence",
                    "label": "(missing evidence)",
                    "confidence": "unknown",
                    "is_inference": False,
                }
            )
            continue
        title = _str(e.get("source_title")) or "Untitled source"
        nodes.append(
            {
                "id": eid,
                "type": "evidence",
                "label": (_str(e.get("quote")) or _str(e.get("claim")) or title)[:200],
                "confidence": _str(e.get("confidence")) or "medium",
                "is_inference": bool(e.get("is_inference")),
                "source_title": title,
                "source_url": _str(e.get("source_url")),
                "source_type": _str(e.get("source_type")) or "web",
                "quote": _str(e.get("quote"))[:600],
            }
        )
        src_id = f"{_SOURCE_NODE_PREFIX}{_slugify_source(title)}"
        if src_id not in sources_seen:
            sources_seen[src_id] = {
                "id": src_id,
                "type": "source",
                "label": title[:120],
                "url": _str(e.get("source_url")),
                "source_type": _str(e.get("source_type")) or "web",
                "evidence_count": 0,
            }
        sources_seen[src_id]["evidence_count"] += 1
        edges.append({"from": eid, "to": src_id, "kind": "cites"})

    nodes.extend(sources_seen.values())

    supported = sum(
        1 for c in claims if _norm_verdict(_effective_verdict(cs_by_claim.get(c["id"], {}))) == "supported"
    )
    weak = sum(
        1 for c in claims if _norm_verdict(_effective_verdict(cs_by_claim.get(c["id"], {}))) == "weak"
    )
    unsupported = sum(
        1 for c in claims if _norm_verdict(_effective_verdict(cs_by_claim.get(c["id"], {}))) == "unsupported"
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "claims": len(claims),
            "evidence": len(referenced_evidence_ids),
            "sources": len(sources_seen),
            "supported": supported,
            "weak": weak,
            "unsupported": unsupported,
        },
    }
