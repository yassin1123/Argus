"""Deep research: query expansion, parallel web search, triage, extraction → EvidenceObject rows."""

import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

from core.json_util import parse_llm_json
from core.llm import llm_call_for_task
from core.research_utils import (
    merge_source_score,
    normalize_url,
    parse_preferred_domains,
    preferred_domain_boost,
    recency_boost,
    research_v2_enabled,
)
from core.retrieval import retrieve_evidence
from core.web_fetch import fetch_page_text
from core.web_search import SERPAPI_KEY, search_web_parallel, search_web_structured
from db.queries import insert_evidence_objects
from models.evidence import EvidenceObject, RetrievedChunk

logger = logging.getLogger(__name__)

QUERY_PLANNER_SYSTEM = """
You expand a research task into 2–4 distinct web search queries.
Output ONLY valid JSON: {"queries": ["query1", "query2"]}
Keep queries short and specific. No prose outside JSON.
"""

EXTRACTOR_SYSTEM = """
You extract citeable factual claims from a web search result.
Inputs may include:
- title, url, snippet (always)
- page_excerpt (optional): longer fetched page text — prefer quotes as verbatim substrings from page_excerpt when present, else from snippet.

For each claim: short "claim", "quote" as verbatim or near-verbatim from excerpt/snippet,
confidence high|medium|low, is_inference true only if the claim is not directly supported by quoted text.
Output ONLY valid JSON: {"items": [{"claim": "", "quote": "", "confidence": "medium", "is_inference": false}]}
Max 4 items. If no usable text, return {"items": []}.
"""

SYNTH_SYSTEM = """
You write one research finding paragraph for a task using ONLY the numbered evidence objects (id + quote).
Output ONLY valid JSON: {"finding": "...", "confidence": "high|medium|low", "gaps": "what is still unknown"}
"""

TENSION_SYSTEM = """
You compare independent web sources (different domains). List factual tensions or contradictions between them, if any.
If sources align, return empty tensions. Output ONLY JSON: {"tensions": ["short bullet", ...]}
Max 4 tensions. No prose outside JSON.
"""

BRANCH_PLANNER_SYSTEM = """
You split research into named branches (parallel tracks) for coverage.
Output ONLY valid JSON: {"branches": [{"id": "snake_case_id", "questions": ["q1", "q2"]}]}
Rules:
- 2-4 branches; each branch must have exactly 2 short search questions.
- If required_ids is non-empty, include one branch per required id using that exact id string.
- Otherwise infer branches from the plan objective and tasks.
No prose outside JSON.
"""


def _task_id(task: dict) -> int:
    raw = task.get("id")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    raw = task.get("task_id")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return 0


def _triage_score(query: str, item: dict[str, Any]) -> float:
    q_terms = set(re.findall(r"\w+", query.lower())) - {"the", "a", "an", "and", "or", "for", "to", "of", "in"}
    blob = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    hits = sum(1 for t in q_terms if len(t) > 2 and t in blob)
    pos = float(item.get("position") or 10)
    return hits * 2.0 + len(blob) * 0.01 - pos * 0.05


def _chunk_to_evidence(session_id: str, task_id: int, hit: RetrievedChunk) -> EvidenceObject:
    quote = (hit.text or "")[:2000]
    title = hit.filename or "Document"
    url = hit.source_url or ""
    claim_bits = [f"chunk {hit.chunk_index}"]
    if hit.page is not None:
        claim_bits.append(f"page {hit.page}")
    if hit.section_hint:
        claim_bits.append(hit.section_hint.replace("_", " "))
    return EvidenceObject(
        session_id=session_id,
        task_id=task_id,
        claim=f"Retrieved passage relevant to research task ({', '.join(claim_bits)})",
        quote=quote,
        source_title=title,
        source_url=url or "",
        source_date=None,
        source_type="document",
        source_score=float(hit.similarity),
        confidence="high" if hit.similarity >= 0.35 else "medium",
        is_inference=False,
    )


async def _planned_queries(task_question: str) -> list[str]:
    base = task_question.strip()
    if not base:
        return []
    try:
        user = f"Task: {base}"
        raw = await llm_call_for_task(
            "research_subagent",
            QUERY_PLANNER_SYSTEM,
            user,
            temperature=0.2,
        )
        data = parse_llm_json(raw)
        qs = data.get("queries") if isinstance(data, dict) else None
        if isinstance(qs, list):
            out = [str(q).strip() for q in qs if str(q).strip()]
            if base.lower() not in [x.lower() for x in out]:
                out.insert(0, base)
            return out[:5]
    except Exception:
        logger.exception("query planner failed; using task question only")
    return [base]


async def _extract_from_web_result(
    session_id: str,
    task_id: int,
    task_question: str,
    result: dict[str, Any],
    *,
    page_text: str | None = None,
) -> list[EvidenceObject]:
    payload: dict[str, Any] = {
        "task": task_question,
        "title": result.get("title"),
        "url": result.get("url"),
        "snippet": result.get("snippet"),
    }
    if page_text:
        payload["page_excerpt"] = page_text[:10000]
    user = json.dumps(payload, ensure_ascii=False)
    try:
        raw = await llm_call_for_task(
            "research_subagent",
            EXTRACTOR_SYSTEM,
            user,
            temperature=0.1,
        )
        data = parse_llm_json(raw)
    except Exception:
        logger.exception("web evidence extractor failed")
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: list[EvidenceObject] = []
    host = ""
    try:
        host = urlparse(str(result.get("url") or "").strip()).hostname or ""
    except Exception:
        host = ""
    base_score = merge_source_score(_triage_score(task_question, result), result)
    score = min(1.0, float(base_score) + preferred_domain_boost(host, parse_preferred_domains()))
    for it in items[:4]:
        if not isinstance(it, dict):
            continue
        claim = str(it.get("claim", "")).strip()[:2000]
        quote = str(it.get("quote", "")).strip()[:2000]
        if not quote:
            continue
        conf = str(it.get("confidence", "medium")).lower()
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        out.append(
            EvidenceObject(
                session_id=session_id,
                task_id=task_id,
                claim=claim or task_question[:500],
                quote=quote,
                source_title=str(result.get("title", ""))[:500],
                source_url=str(result.get("url", ""))[:2000],
                source_date=None,
                source_type="web",
                source_score=max(0.0, float(score)),
                confidence=conf,
                is_inference=bool(it.get("is_inference")),
            )
        )
    return out


async def _synthesize_finding(task_question: str, objs: list[EvidenceObject]) -> dict[str, str]:
    if not objs:
        return {"finding": "No evidence objects for this task.", "confidence": "low", "gaps": "No indexed evidence."}
    catalog = []
    for i, o in enumerate(objs[:20]):
        catalog.append(
            {
                "n": i + 1,
                "id": o.id,
                "quote": (o.quote or "")[:800],
                "source": o.source_title,
            }
        )
    user = f"Task: {task_question}\nEvidence:\n{json.dumps(catalog, ensure_ascii=False)}"
    try:
        raw = await llm_call_for_task(
            "research_subagent",
            SYNTH_SYSTEM,
            user,
            temperature=0.2,
        )
        data = parse_llm_json(raw)
        if isinstance(data, dict):
            return {
                "finding": str(data.get("finding", ""))[:4000],
                "confidence": str(data.get("confidence", "medium")),
                "gaps": str(data.get("gaps", ""))[:2000],
            }
    except Exception:
        logger.exception("synthesiser failed")
    return {
        "finding": "Evidence collected; synthesis unavailable.",
        "confidence": "low",
        "gaps": "Synthesis step failed.",
    }


async def _plan_research_branches(plan: dict, required_ids: list[str]) -> list[dict[str, Any]]:
    obj = str(plan.get("objective", ""))[:1200]
    req_list = [str(x).strip().lower().replace(" ", "_") for x in required_ids if str(x).strip()]
    user = json.dumps(
        {"required_ids": req_list, "objective": obj, "tasks": plan.get("tasks") or []},
        ensure_ascii=False,
    )[:8000]
    try:
        raw = await llm_call_for_task(
            "research_subagent",
            BRANCH_PLANNER_SYSTEM,
            user,
            temperature=0.2,
        )
        data = parse_llm_json(raw)
    except Exception:
        logger.exception("branch planner failed")
        data = {}
    branches = data.get("branches") if isinstance(data, dict) else None
    out: list[dict[str, Any]] = []
    if isinstance(branches, list):
        for b in branches:
            if not isinstance(b, dict):
                continue
            bid = str(b.get("id", "")).strip().lower().replace(" ", "_")[:64]
            qs = b.get("questions")
            ql: list[str] = []
            if isinstance(qs, list):
                ql = [str(x).strip() for x in qs if str(x).strip()][:2]
            if bid and ql:
                out.append({"id": bid, "questions": ql})
    if req_list:
        have = {b["id"] for b in out}
        for rid in req_list:
            if rid not in have:
                out.append(
                    {
                        "id": rid,
                        "questions": [
                            f"{obj[:140]} — focus on {rid.replace('_', ' ')}",
                            f"Data and risks for {rid.replace('_', ' ')} segment",
                        ],
                    }
                )
    return out[:6]


async def _append_web_extractions(
    session_id: str,
    task_id: int,
    task_question: str,
    web_hits: list[dict[str, Any]],
    fetch_budget: list[int],
    seen_norm_urls: set[str],
    task_objs: list[EvidenceObject],
    *,
    limit: int = 6,
) -> None:
    ranked = sorted(
        web_hits,
        key=lambda x: _triage_score(task_question, x) + recency_boost(x) * 0.5,
        reverse=True,
    )
    for wh in ranked[:limit]:
        u = str(wh.get("url") or "").strip()
        if not u:
            continue
        nk = normalize_url(u)
        if nk and nk in seen_norm_urls:
            continue
        if fetch_budget[0] <= 0:
            break
        fetch_budget[0] -= 1
        text, _err = await fetch_page_text(u)
        page_text = text if text else None
        extracted = await _extract_from_web_result(
            session_id, task_id, task_question, wh, page_text=page_text
        )
        if nk:
            seen_norm_urls.add(nk)
        task_objs.extend(extracted)


async def _detect_evidence_tensions(objs: list[EvidenceObject]) -> list[str]:
    webs = [o for o in objs if o.source_type == "web" and (o.quote or "").strip() and (o.source_url or "").strip()]
    by_host: dict[str, EvidenceObject] = {}
    for o in webs:
        try:
            host = (urlparse(o.source_url or "").netloc or "").lower()
        except Exception:
            host = ""
        if host and host not in by_host:
            by_host[host] = o
        if len(by_host) >= 5:
            break
    if len(by_host) < 2:
        return []
    pack = [
        {"domain": urlparse(o.source_url or "").netloc, "quote": (o.quote or "")[:700]}
        for o in list(by_host.values())[:5]
    ]
    user = json.dumps({"sources": pack}, ensure_ascii=False)
    try:
        raw = await llm_call_for_task(
            "research_subagent",
            TENSION_SYSTEM,
            user,
            temperature=0.0,
        )
        data = parse_llm_json(raw)
    except Exception:
        logger.exception("tension detector failed")
        return []
    t = data.get("tensions") if isinstance(data, dict) else None
    if not isinstance(t, list):
        return []
    return [str(x).strip() for x in t if str(x).strip()][:4]


def _dedupe_web_evidence_best_url(objs: list[EvidenceObject]) -> list[EvidenceObject]:
    """Keep highest source_score EvidenceObject per normalized URL (web only)."""
    from collections import defaultdict

    groups: dict[str, list[EvidenceObject]] = defaultdict(list)
    rest: list[EvidenceObject] = []
    for o in objs:
        if o.source_type == "web" and (o.source_url or "").strip():
            nk = normalize_url(o.source_url)
            if nk:
                groups[nk].append(o)
                continue
        rest.append(o)
    picked: list[EvidenceObject] = []
    for group in groups.values():
        group.sort(key=lambda x: float(x.source_score or 0.0), reverse=True)
        picked.append(group[0])
    return rest + picked


class ResearchOrchestrator:
    async def run(
        self,
        session_id: str,
        plan: dict,
        context: str,
        *,
        report_mode: str = "general",
    ) -> dict[str, Any]:
        """
        Persist EvidenceObject rows and return research dict compatible with analyst (findings + evidence_ids).
        """
        _ = context  # reserved for future grounding against uploads
        all_pending: list[EvidenceObject] = []
        tasks = plan.get("tasks") or []
        if not isinstance(tasks, list):
            tasks = []

        retrieval_snapshots: list[dict[str, Any]] = []
        fetch_budget = [8]
        seen_norm_urls: set[str] = set()
        max_followups = int(os.getenv("ARGUS_RESEARCH_MAX_FOLLOWUPS", "6"))
        followups_used = 0
        followup_query_count = 0

        for task in tasks:
            if not isinstance(task, dict):
                continue
            tid = _task_id(task)
            q = str(task.get("question", "") or "")

            task_objs: list[EvidenceObject] = []

            hits = await retrieve_evidence(session_id, q, top_k=8)
            retrieval_snapshots.append(
                {
                    "task_id": tid,
                    "question": q,
                    "hits": [h.model_dump(mode="json") for h in hits],
                }
            )
            for h in hits:
                task_objs.append(_chunk_to_evidence(session_id, tid, h))

            if SERPAPI_KEY:
                queries = await _planned_queries(q)
                web_hits = await search_web_parallel(queries, num_results=4)
                await _append_web_extractions(
                    session_id, tid, q, web_hits, fetch_budget, seen_norm_urls, task_objs, limit=6
                )

                if len([x for x in task_objs if x.source_type == "web"]) == 0:
                    extra = await search_web_structured(f"{q} facts", num_results=3)
                    extra.sort(
                        key=lambda x: _triage_score(q, x) + recency_boost(x) * 0.5,
                        reverse=True,
                    )
                    await _append_web_extractions(
                        session_id, tid, q, extra, fetch_budget, seen_norm_urls, task_objs, limit=3
                    )

            synth = await _synthesize_finding(q, task_objs)
            if (
                SERPAPI_KEY
                and str(synth.get("confidence", "")).lower() == "low"
                and len([x for x in task_objs if x.source_type == "web"]) == 0
            ):
                fill = await search_web_structured(f"{q} industry data statistics benchmark", num_results=6)
                await _append_web_extractions(
                    session_id, tid, q, fill, fetch_budget, seen_norm_urls, task_objs, limit=5
                )
                synth = await _synthesize_finding(q, task_objs)
            if SERPAPI_KEY and followups_used < max_followups:
                gaps = (synth.get("gaps") or "").strip()
                web_n = len([x for x in task_objs if x.source_type == "web"])
                if len(gaps) > 20 or web_n < 1:
                    gap_queries = await _planned_queries(f"{q}. Gaps to fill: {gaps[:400]}")
                    followup_query_count += min(2, len(gap_queries))
                    for gq in gap_queries[:2]:
                        wh2 = await search_web_structured(gq.strip(), num_results=4)
                        await _append_web_extractions(
                            session_id, tid, q, wh2, fetch_budget, seen_norm_urls, task_objs, limit=4
                        )
                    followups_used += 1

            all_pending.extend(task_objs)

        branch_trace: list[dict[str, Any]] = []
        from core.consulting_modes import get_mode_config

        req_branches = list(get_mode_config(report_mode).get("required_branches") or [])
        if req_branches or report_mode != "general":
            branch_defs = await _plan_research_branches(plan, req_branches)
            tid_base = 9000
            for bi, bdef in enumerate(branch_defs):
                bid = str(bdef.get("id", f"branch_{bi}")).strip().lower().replace(" ", "_")[:64] or f"branch_{bi}"
                tid = tid_base + bi
                qs = bdef.get("questions") if isinstance(bdef.get("questions"), list) else []
                qs = [str(x).strip() for x in qs if str(x).strip()][:2]
                if not qs:
                    qs = [f"{str(plan.get('objective', ''))[:180]} — {bid.replace('_', ' ')}"]
                added = 0
                for bq in qs:
                    bhits = await retrieve_evidence(session_id, bq, top_k=6)
                    retrieval_snapshots.append(
                        {
                            "task_id": tid,
                            "branch_id": bid,
                            "question": bq,
                            "hits": [h.model_dump(mode="json") for h in bhits],
                        }
                    )
                    for h in bhits:
                        eo = _chunk_to_evidence(session_id, tid, h)
                        eo.claim = f"[branch:{bid}] {eo.claim}"
                        all_pending.append(eo)
                        added += 1
                    if SERPAPI_KEY:
                        b_queries = await _planned_queries(bq)
                        web_hits = await search_web_parallel(b_queries, num_results=3)
                        branch_bucket: list[EvidenceObject] = []
                        await _append_web_extractions(
                            session_id, tid, bq, web_hits, fetch_budget, seen_norm_urls, branch_bucket, limit=4
                        )
                        for o in branch_bucket:
                            o.claim = f"[branch:{bid}] {o.claim or bq}"
                            all_pending.append(o)
                        added += len(branch_bucket)
                branch_trace.append({"id": bid, "questions": qs, "evidence_added_count": added})

        if research_v2_enabled():
            all_pending = _dedupe_web_evidence_best_url(all_pending)

        inserted = await insert_evidence_objects(all_pending)
        research_contradictions = await _detect_evidence_tensions(inserted)
        by_task: dict[int, list[EvidenceObject]] = {}
        for o in inserted:
            k = o.task_id if o.task_id is not None else 0
            by_task.setdefault(k, []).append(o)

        findings: list[dict[str, Any]] = []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            tid = _task_id(task)
            q = str(task.get("question", "") or "")
            objs = by_task.get(tid, [])
            synth = await _synthesize_finding(q, objs)
            eids = [x.id for x in objs if x.id]
            findings.append(
                {
                    "task_id": tid,
                    "question": q,
                    "finding": synth["finding"],
                    "confidence": synth["confidence"],
                    "gaps": synth["gaps"],
                    "evidence_ids": eids,
                    "evidence": [],
                    "web_citations": [
                        {"title": o.source_title, "url": o.source_url, "snippet": o.quote[:500]}
                        for o in objs
                        if o.source_type == "web"
                    ][:10],
                }
            )

        if not findings and not inserted:
            findings.append(
                {
                    "task_id": 0,
                    "question": str(plan.get("summary", "Research")),
                    "finding": "No research tasks or no evidence retrieved.",
                    "confidence": "low",
                    "gaps": "Add documents or configure web search.",
                    "evidence_ids": [],
                    "evidence": [],
                    "web_citations": [],
                }
            )

        tid_base = 9000
        for bi, trace in enumerate(branch_trace):
            tid = tid_base + bi
            bid = trace.get("id", f"branch_{bi}")
            objs = by_task.get(tid, [])
            synth = await _synthesize_finding(f"Branch: {bid}", objs)
            eids = [x.id for x in objs if x.id]
            findings.append(
                {
                    "task_id": tid,
                    "branch_id": bid,
                    "question": " / ".join(trace.get("questions") or [])[:500],
                    "finding": synth["finding"],
                    "confidence": synth["confidence"],
                    "gaps": synth["gaps"],
                    "evidence_ids": eids,
                    "evidence": [],
                    "web_citations": [
                        {"title": o.source_title, "url": o.source_url, "snippet": o.quote[:500]}
                        for o in objs
                        if o.source_type == "web"
                    ][:8],
                }
            )

        return {
            "findings": findings,
            "_evidence_objects_count": len(inserted),
            "_retrieval_hits": retrieval_snapshots,
            "_research_branches": branch_trace,
            "_research_contradictions": research_contradictions,
            "_followup_query_count": followup_query_count,
        }
