import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from agents.analyst import AnalystAgent
from agents.critic import CriticAgent
from agents.planner import PlannerAgent
from agents.research import ResearchOrchestrator
from agents.verifier import VerifierAgent
from agents.writer import WriterAgent
from core.claim_linkage import validate_writer_claim_linkage
from core.claim_support import build_claim_support
from core.contradiction_policy import (
    apply_confidence_cap,
    build_contradiction_caveat,
    compute_contradiction_severity,
    merge_contradiction_into_caveats,
)
from core.consulting_modes import branch_ids_from_evidence_claims, check_mode_satisfied
from core.entailment import enrich_claim_rows_with_entailment
from core.evidence_graph import build_evidence_graph_v1
from core.eval_rubric import score_pipeline_artifacts
from core.evidence_gates import validate_analyst_evidence_gates
from core.reasoning_skeleton import validate_reasoning_skeleton
from core.trust_labels import build_trust_labels
from core.verification_validate import sanitize_verification_assessments, verification_assessments_usable
from db.queries import (
    append_pipeline_trace_events,
    get_session_row,
    get_uploaded_context_text,
    insert_pipeline_event,
    list_evidence_objects,
    merge_session_metadata,
    replace_claim_support_rows,
    save_agent_output,
    save_claim_evidence_links,
    save_evaluation,
    save_report,
    update_pipeline_state,
    update_session_gap_report,
    update_session_status,
)
from models.evidence import EvidenceObject
from models.reasoning import build_reasoning_graph, merge_verifier_and_research_into_graph
from models.report import WriterReportPayload
from models.trust import TrustObject

logger = logging.getLogger(__name__)

MAX_EVIDENCE_GATE_RETRIES = 2


def _intake_context_block(questions: list[Any], answers: list[Any]) -> str:
    """Format stored intake Q&A for the planner."""
    by_id: dict[str, str] = {}
    for a in answers or []:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id") or "").strip()
        if aid:
            by_id[aid] = str(a.get("answer") or "").strip()
    lines: list[str] = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or "").strip()
        qt = str(q.get("question") or "").strip()
        ans = by_id.get(qid, "")
        if qt or ans:
            lines.append(f"- Q: {qt}\n  A: {ans or '(no answer)'}")
    return "\n".join(lines)


async def _pipeline_trace(session_id: str, event: str, detail: str = "") -> None:
    await append_pipeline_trace_events(
        session_id,
        [
            {
                "event": event,
                "detail": detail[:500],
                "at": datetime.now(timezone.utc).isoformat(),
            }
        ],
    )
    await insert_pipeline_event(
        session_id,
        event_type="trace",
        stage=event,
        status="info",
        payload={"detail": detail[:500]},
    )
MAX_SKELETON_RETRIES = 2


def _verifier_invalid_strip_total(stats: dict[str, Any]) -> int:
    t = int(stats.get("invalid_id_strips", 0))
    r = stats.get("retry")
    if isinstance(r, dict):
        t += int(r.get("invalid_id_strips", 0))
    return t


def build_evidence_bundle(
    research: dict,
    evidence_objects: list[EvidenceObject] | None = None,
) -> list[dict[str, Any]]:
    """Flatten research findings + normalized evidence objects for API/report storage."""
    out: list[dict[str, Any]] = []
    for f in research.get("findings") or []:
        if not isinstance(f, dict):
            continue
        tid = f.get("task_id")
        finding_text = (f.get("finding") or "")[:500]
        for e in f.get("evidence") or []:
            if isinstance(e, dict):
                row = dict(e)
                row["kind"] = "document_chunk"
                row["task_id"] = tid
                row["finding_summary"] = finding_text
                out.append(row)
        for w in f.get("web_citations") or []:
            if isinstance(w, dict) and (w.get("url") or w.get("title")):
                out.append(
                    {
                        "kind": "web",
                        "task_id": tid,
                        "title": w.get("title", ""),
                        "url": w.get("url", ""),
                        "snippet": w.get("snippet", ""),
                    }
                )
    for o in evidence_objects or []:
        if not o.id:
            continue
        out.append(
            {
                "kind": "evidence_object",
                "evidence_id": o.id,
                "task_id": o.task_id,
                "quote": o.quote[:1500],
                "source_title": o.source_title,
                "url": o.source_url,
                "source_type": o.source_type,
                "confidence": o.confidence,
                "chunk_id": o.id,
                "evidence_id": o.id,
                "filename": o.source_title,
            }
        )
    return out[:120]


def _count_unsupported(verification: dict[str, Any]) -> int:
    n = 0
    for a in verification.get("claim_assessments") or []:
        if not isinstance(a, dict):
            continue
        v = str(a.get("verdict", "")).lower()
        if v in ("unsupported", "overstates"):
            n += 1
    return n


def _claim_links_from_verification(report_id: str, verification: dict[str, Any]) -> list[tuple[str, str, str]]:
    links: list[tuple[str, str, str]] = []
    for a in verification.get("claim_assessments") or []:
        if not isinstance(a, dict):
            continue
        claim = str(a.get("claim", ""))[:2000]
        verdict = str(a.get("verdict", "supports"))
        lt = "contradicts" if verdict == "unsupported" else "supports"
        for eid in a.get("evidence_ids") or []:
            eid_s = str(eid).strip()
            if eid_s:
                links.append((claim, eid_s, lt))
    return links


async def _timed_agent(
    session_id: str,
    agent_name: str,
    input_preview: str | None,
    coro,
) -> Any:
    t0 = time.perf_counter()
    try:
        out = await coro
        ms = int((time.perf_counter() - t0) * 1000)
        output_str = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        await save_agent_output(session_id, agent_name, input_preview, output_str, duration_ms=ms)
        return out
    except Exception:
        ms = int((time.perf_counter() - t0) * 1000)
        raise


async def run_pipeline(session_id: str, query: str) -> WriterReportPayload | None:
    context = await get_uploaded_context_text(session_id)
    sess = await get_session_row(session_id)
    report_mode = str(sess.get("report_mode") or "general") if sess else "general"
    research_contradictions_list: list[str] = []
    research_followup_queries = 0
    verifier_sanitize_stats: dict[str, Any] = {}
    try:
        await update_session_status(session_id, "processing")
        await _pipeline_trace(session_id, "pipeline_start", "status=processing")

        intake_block = ""
        if sess:
            intake_block = _intake_context_block(
                sess.get("intake_questions") or [],
                sess.get("intake_answers") or [],
            )
        planner = PlannerAgent()
        plan = await _timed_agent(
            session_id,
            "planner",
            query,
            planner.run(
                query=query,
                context=context,
                report_mode=report_mode,
                intake_block=intake_block,
            ),
        )
        await update_pipeline_state(session_id, "plan_ready")
        n_tasks = len(plan.get("tasks") or []) if isinstance(plan, dict) else 0
        await _pipeline_trace(session_id, "plan_ready", f"tasks={n_tasks}")

        research_orch = ResearchOrchestrator()
        research = await _timed_agent(
            session_id,
            "researcher",
            json.dumps(plan, ensure_ascii=False)[:8000],
            research_orch.run(
                session_id=session_id, plan=plan, context=context, report_mode=report_mode
            ),
        )
        if isinstance(research, dict):
            meta_patch: dict[str, Any] = {}
            rh = research.pop("_retrieval_hits", [])
            rb = research.pop("_research_branches", None)
            rc = research.pop("_research_contradictions", None)
            fc = research.pop("_followup_query_count", None)
            research.pop("_evidence_objects_count", None)
            if isinstance(rc, list):
                research_contradictions_list[:] = [str(x) for x in rc if str(x).strip()]
            if fc is not None:
                try:
                    research_followup_queries = int(fc)
                except (TypeError, ValueError):
                    research_followup_queries = 0
            if rh:
                meta_patch["retrieval_hits"] = rh
            if rb is not None:
                meta_patch["research_branches"] = rb
            if research_contradictions_list:
                meta_patch["research_contradictions"] = research_contradictions_list
            meta_patch["followup_query_count"] = research_followup_queries
            if meta_patch:
                await merge_session_metadata(session_id, meta_patch)

        evidence_objects = await list_evidence_objects(session_id)
        await update_pipeline_state(session_id, "research_gathered")
        await _pipeline_trace(
            session_id,
            "research_gathered",
            f"evidence_objects={len(evidence_objects)}",
        )
        branch_ids = branch_ids_from_evidence_claims(evidence_objects)
        ok_mode, mode_gaps = check_mode_satisfied(
            report_mode,
            branch_ids_present=branch_ids,
            evidence_count=len(evidence_objects),
        )
        if not ok_mode:
            await update_session_gap_report(
                session_id,
                {
                    "title": "Consulting mode requirements not met",
                    "missing_evidence": mode_gaps,
                    "suggested_searches": [],
                    "contradictions": [],
                    "notes": f"Report mode '{report_mode}' requires additional research coverage or evidence depth.",
                },
            )
            await update_session_status(session_id, "insufficient")
            await update_pipeline_state(session_id, "evidence_insufficient")
            await save_evaluation(
                session_id,
                {
                    "outcome": "insufficient",
                    "reason": "consulting_mode",
                    "report_mode": report_mode,
                    "evidence_count": len(evidence_objects),
                    **score_pipeline_artifacts(
                        report_payload={},
                        verification={},
                        evidence_count=len(evidence_objects),
                        gate_passed=True,
                        report_mode=report_mode,
                        branch_ids_present=branch_ids,
                        research_followup_queries=research_followup_queries,
                    ),
                },
            )
            return None

        gate_passed_final = True

        analyst = AnalystAgent()
        analysis = await _timed_agent(
            session_id,
            "analyst",
            json.dumps(research, ensure_ascii=False)[:8000],
            analyst.run(
                query=query,
                plan=plan,
                research=research,
                evidence_objects=evidence_objects,
                report_mode=report_mode,
                session_id=session_id,
                trace_id=session_id,
            ),
        )
        await update_pipeline_state(session_id, "analysis_v1_done")

        critic = CriticAgent()
        critique = await _timed_agent(
            session_id,
            "critic",
            json.dumps(analysis, ensure_ascii=False)[:8000],
            critic.run(
                query=query,
                analysis=analysis,
                research=research,
                session_id=session_id,
                trace_id=session_id,
            ),
        )
        await update_pipeline_state(session_id, "critique_done")

        analysis_rev = await _timed_agent(
            session_id,
            "analyst_revision",
            json.dumps(critique, ensure_ascii=False)[:8000],
            analyst.revise(
                query=query,
                plan=plan,
                research=research,
                analysis=analysis,
                critique=critique,
                evidence_objects=evidence_objects,
                report_mode=report_mode,
                session_id=session_id,
                trace_id=session_id,
            ),
        )
        await update_pipeline_state(session_id, "analysis_v2_done")

        ok_gates, gate_errors = validate_analyst_evidence_gates(analysis_rev, evidence_objects)
        gate_attempts = 0
        while not ok_gates and gate_attempts < MAX_EVIDENCE_GATE_RETRIES:
            gate_attempts += 1
            logger.warning(
                "Evidence gates failed (attempt %s/%s): %s",
                gate_attempts,
                MAX_EVIDENCE_GATE_RETRIES,
                gate_errors[:5],
            )
            analysis_rev = await _timed_agent(
                session_id,
                "analyst_revision",
                json.dumps({"gate_errors": gate_errors}, ensure_ascii=False)[:8000],
                analyst.revise(
                    query=query,
                    plan=plan,
                    research=research,
                    analysis=analysis_rev,
                    critique=critique,
                    evidence_objects=evidence_objects,
                    gate_feedback=gate_errors,
                    draft_label="Current analyst draft",
                    report_mode=report_mode,
                    session_id=session_id,
                    trace_id=session_id,
                ),
            )
            ok_gates, gate_errors = validate_analyst_evidence_gates(analysis_rev, evidence_objects)

        if not ok_gates:
            gate_passed_final = False
            await update_pipeline_state(session_id, "evidence_insufficient")
            gap_report = {
                "title": "Evidence gate failure — claims not tied to catalog",
                "missing_evidence": gate_errors,
                "suggested_searches": [
                    "Add primary documents to the session",
                    "Ensure each analytical claim cites evidence_object UUIDs from the catalog",
                ],
                "contradictions": [],
                "notes": "Hard validation failed: key_claims must cite persisted evidence ids.",
            }
            await update_session_gap_report(session_id, gap_report)
            await update_session_status(session_id, "insufficient")
            await save_evaluation(
                session_id,
                {
                    "outcome": "insufficient",
                    "reason": "evidence_gates",
                    "report_mode": report_mode,
                    "evidence_count": len(evidence_objects),
                    **score_pipeline_artifacts(
                        report_payload={},
                        verification={},
                        evidence_count=len(evidence_objects),
                        gate_passed=False,
                        report_mode=report_mode,
                        branch_ids_present=branch_ids,
                        research_followup_queries=research_followup_queries,
                    ),
                },
            )
            return None

        ok_skel, skel_errors = validate_reasoning_skeleton(analysis_rev, report_mode)
        sk_attempts = 0
        while not ok_skel and sk_attempts < MAX_SKELETON_RETRIES:
            sk_attempts += 1
            logger.warning(
                "Reasoning skeleton failed (attempt %s/%s): %s",
                sk_attempts,
                MAX_SKELETON_RETRIES,
                skel_errors[:5],
            )
            analysis_rev = await _timed_agent(
                session_id,
                "analyst_revision",
                json.dumps({"skeleton_errors": skel_errors}, ensure_ascii=False)[:8000],
                analyst.revise(
                    query=query,
                    plan=plan,
                    research=research,
                    analysis=analysis_rev,
                    critique=critique,
                    evidence_objects=evidence_objects,
                    gate_feedback=skel_errors,
                    draft_label="Current analyst draft (reasoning skeleton)",
                    report_mode=report_mode,
                    session_id=session_id,
                    trace_id=session_id,
                ),
            )
            ok_gates, gate_errors = validate_analyst_evidence_gates(analysis_rev, evidence_objects)
            if not ok_gates:
                analysis_rev = await _timed_agent(
                    session_id,
                    "analyst_revision",
                    json.dumps({"gate_errors": gate_errors}, ensure_ascii=False)[:8000],
                    analyst.revise(
                        query=query,
                        plan=plan,
                        research=research,
                        analysis=analysis_rev,
                        critique=critique,
                        evidence_objects=evidence_objects,
                        gate_feedback=gate_errors,
                        draft_label="Current analyst draft",
                        report_mode=report_mode,
                        session_id=session_id,
                        trace_id=session_id,
                    ),
                )
                ok_gates, gate_errors = validate_analyst_evidence_gates(analysis_rev, evidence_objects)
            if not ok_gates:
                gate_passed_final = False
                await update_pipeline_state(session_id, "evidence_insufficient")
                await update_session_gap_report(
                    session_id,
                    {
                        "title": "Evidence gate failure after skeleton revision",
                        "missing_evidence": gate_errors,
                        "suggested_searches": [],
                        "contradictions": [],
                        "notes": "Skeleton fix pass broke evidence grounding.",
                    },
                )
                await update_session_status(session_id, "insufficient")
                await save_evaluation(
                    session_id,
                    {
                        "outcome": "insufficient",
                        "reason": "evidence_gates_after_skeleton",
                        "report_mode": report_mode,
                        "evidence_count": len(evidence_objects),
                        **score_pipeline_artifacts(
                            report_payload={},
                            verification={},
                            evidence_count=len(evidence_objects),
                            gate_passed=False,
                            report_mode=report_mode,
                            branch_ids_present=branch_ids,
                            research_followup_queries=research_followup_queries,
                        ),
                    },
                )
                return None
            ok_skel, skel_errors = validate_reasoning_skeleton(analysis_rev, report_mode)

        if not ok_skel:
            gate_passed_final = False
            await update_pipeline_state(session_id, "evidence_insufficient")
            await update_session_gap_report(
                session_id,
                {
                    "title": "Reasoning skeleton incomplete",
                    "missing_evidence": skel_errors,
                    "suggested_searches": [],
                    "contradictions": [],
                    "notes": f"Report mode '{report_mode}' requires all configured reasoning slots with summaries and claim links.",
                },
            )
            await update_session_status(session_id, "insufficient")
            await save_evaluation(
                session_id,
                {
                    "outcome": "insufficient",
                    "reason": "reasoning_skeleton",
                    "report_mode": report_mode,
                    "evidence_count": len(evidence_objects),
                    **score_pipeline_artifacts(
                        report_payload={},
                        verification={},
                        evidence_count=len(evidence_objects),
                        gate_passed=True,
                        report_mode=report_mode,
                        branch_ids_present=branch_ids,
                        research_followup_queries=research_followup_queries,
                    ),
                },
            )
            return None

        await update_pipeline_state(session_id, "gates_validated")
        critique_post = await _timed_agent(
            session_id,
            "critic_post_revision",
            json.dumps(analysis_rev, ensure_ascii=False)[:8000],
            critic.run(
                query=query,
                analysis=analysis_rev,
                research=research,
                session_id=session_id,
                trace_id=session_id,
            ),
        )
        await update_pipeline_state(session_id, "critic_post_done")
        if isinstance(critique_post, dict) and str(critique_post.get("verdict", "")).lower() == "reject":
            analysis_rev = await _timed_agent(
                session_id,
                "analyst_revision",
                json.dumps(critique_post, ensure_ascii=False)[:8000],
                analyst.revise(
                    query=query,
                    plan=plan,
                    research=research,
                    analysis=analysis_rev,
                    critique=critique_post,
                    evidence_objects=evidence_objects,
                    draft_label="Current analyst draft (second critic)",
                    report_mode=report_mode,
                    session_id=session_id,
                    trace_id=session_id,
                ),
            )
            ok_gates, gate_errors = validate_analyst_evidence_gates(analysis_rev, evidence_objects)
            if not ok_gates and gate_errors:
                analysis_rev = await _timed_agent(
                    session_id,
                    "analyst_revision",
                    json.dumps({"gate_errors": gate_errors}, ensure_ascii=False)[:8000],
                    analyst.revise(
                        query=query,
                        plan=plan,
                        research=research,
                        analysis=analysis_rev,
                        critique=critique_post,
                        evidence_objects=evidence_objects,
                        gate_feedback=gate_errors,
                        draft_label="Current analyst draft",
                        report_mode=report_mode,
                        session_id=session_id,
                        trace_id=session_id,
                    ),
                )
                ok_gates, gate_errors = validate_analyst_evidence_gates(analysis_rev, evidence_objects)
            if not ok_gates:
                gate_passed_final = False
                await update_pipeline_state(session_id, "evidence_insufficient")
                gap_report = {
                    "title": "Evidence gate failure after second critic revision",
                    "missing_evidence": gate_errors,
                    "suggested_searches": [],
                    "contradictions": [],
                    "notes": "Critic rejected prior draft; revised output still failed evidence gates.",
                }
                await update_session_gap_report(session_id, gap_report)
                await update_session_status(session_id, "insufficient")
                await save_evaluation(
                    session_id,
                    {
                        "outcome": "insufficient",
                        "reason": "evidence_gates_post_critic",
                        "report_mode": report_mode,
                        "evidence_count": len(evidence_objects),
                        **score_pipeline_artifacts(
                            report_payload={},
                            verification={},
                            evidence_count=len(evidence_objects),
                            gate_passed=False,
                            report_mode=report_mode,
                            branch_ids_present=branch_ids,
                            research_followup_queries=research_followup_queries,
                        ),
                    },
                )
                return None

        crit_for_skel = critique_post if isinstance(critique_post, dict) else critique
        ok_skel_final, skel_err_final = validate_reasoning_skeleton(analysis_rev, report_mode)
        if not ok_skel_final:
            analysis_rev = await _timed_agent(
                session_id,
                "analyst_revision",
                json.dumps({"skeleton_errors_post_critic": skel_err_final}, ensure_ascii=False)[:8000],
                analyst.revise(
                    query=query,
                    plan=plan,
                    research=research,
                    analysis=analysis_rev,
                    critique=crit_for_skel if isinstance(crit_for_skel, dict) else {},
                    evidence_objects=evidence_objects,
                    gate_feedback=skel_err_final,
                    draft_label="Current analyst draft (skeleton after critic)",
                    report_mode=report_mode,
                    session_id=session_id,
                    trace_id=session_id,
                ),
            )
            ok_gates, gate_errors = validate_analyst_evidence_gates(analysis_rev, evidence_objects)
            if not ok_gates:
                gate_passed_final = False
                await update_pipeline_state(session_id, "evidence_insufficient")
                await update_session_gap_report(
                    session_id,
                    {
                        "title": "Evidence gates failed after post-critic skeleton fix",
                        "missing_evidence": gate_errors,
                        "suggested_searches": [],
                        "contradictions": [],
                        "notes": "",
                    },
                )
                await update_session_status(session_id, "insufficient")
                await save_evaluation(
                    session_id,
                    {
                        "outcome": "insufficient",
                        "reason": "evidence_gates_post_skeleton_repair",
                        "report_mode": report_mode,
                        "evidence_count": len(evidence_objects),
                        **score_pipeline_artifacts(
                            report_payload={},
                            verification={},
                            evidence_count=len(evidence_objects),
                            gate_passed=False,
                            report_mode=report_mode,
                            branch_ids_present=branch_ids,
                            research_followup_queries=research_followup_queries,
                        ),
                    },
                )
                return None
            ok_skel_final, skel_err_final = validate_reasoning_skeleton(analysis_rev, report_mode)
        if not ok_skel_final:
            gate_passed_final = False
            await update_pipeline_state(session_id, "evidence_insufficient")
            await update_session_gap_report(
                session_id,
                {
                    "title": "Reasoning skeleton incomplete after critic pass",
                    "missing_evidence": skel_err_final,
                    "suggested_searches": [],
                    "contradictions": [],
                    "notes": "Re-check required reasoning slots and claim_ids.",
                },
            )
            await update_session_status(session_id, "insufficient")
            await save_evaluation(
                session_id,
                {
                    "outcome": "insufficient",
                    "reason": "reasoning_skeleton_post_critic",
                    "report_mode": report_mode,
                    "evidence_count": len(evidence_objects),
                    **score_pipeline_artifacts(
                        report_payload={},
                        verification={},
                        evidence_count=len(evidence_objects),
                        gate_passed=True,
                        report_mode=report_mode,
                        branch_ids_present=branch_ids,
                        research_followup_queries=research_followup_queries,
                    ),
                },
            )
            return None

        force_rev = int(os.getenv("ARGUS_CONTRADICTION_FORCE_REVISION_MIN", "3"))
        if len(research_contradictions_list) >= force_rev:
            tension_fb = [
                f"Research flagged cross-source tension — address in analysis: {t}"
                for t in research_contradictions_list[:6]
            ]
            crit_ref = critique_post if isinstance(critique_post, dict) else critique
            analysis_rev = await _timed_agent(
                session_id,
                "analyst_revision",
                json.dumps({"research_tensions": research_contradictions_list}, ensure_ascii=False)[:8000],
                analyst.revise(
                    query=query,
                    plan=plan,
                    research=research,
                    analysis=analysis_rev,
                    critique=crit_ref if isinstance(crit_ref, dict) else {},
                    evidence_objects=evidence_objects,
                    gate_feedback=tension_fb,
                    draft_label="Current analyst draft (tension reconciliation)",
                    report_mode=report_mode,
                    session_id=session_id,
                    trace_id=session_id,
                ),
            )
            ok_gates_t, gate_errors_t = validate_analyst_evidence_gates(analysis_rev, evidence_objects)
            if not ok_gates_t:
                gate_passed_final = False
                await update_pipeline_state(session_id, "evidence_insufficient")
                await update_session_gap_report(
                    session_id,
                    {
                        "title": "Evidence gates failed after tension reconciliation",
                        "missing_evidence": gate_errors_t,
                        "suggested_searches": [],
                        "contradictions": research_contradictions_list,
                        "notes": "",
                    },
                )
                await update_session_status(session_id, "insufficient")
                await save_evaluation(
                    session_id,
                    {
                        "outcome": "insufficient",
                        "reason": "evidence_gates_after_tension_revision",
                        "report_mode": report_mode,
                        "evidence_count": len(evidence_objects),
                        **score_pipeline_artifacts(
                            report_payload={},
                            verification={},
                            evidence_count=len(evidence_objects),
                            gate_passed=False,
                            report_mode=report_mode,
                            branch_ids_present=branch_ids,
                            research_followup_queries=research_followup_queries,
                        ),
                    },
                )
                return None
            ok_skel_t, skel_errors_t = validate_reasoning_skeleton(analysis_rev, report_mode)
            if not ok_skel_t:
                gate_passed_final = False
                await update_pipeline_state(session_id, "evidence_insufficient")
                await update_session_gap_report(
                    session_id,
                    {
                        "title": "Reasoning skeleton failed after tension reconciliation",
                        "missing_evidence": skel_errors_t,
                        "suggested_searches": [],
                        "contradictions": research_contradictions_list,
                        "notes": "",
                    },
                )
                await update_session_status(session_id, "insufficient")
                await save_evaluation(
                    session_id,
                    {
                        "outcome": "insufficient",
                        "reason": "reasoning_skeleton_after_tension_revision",
                        "report_mode": report_mode,
                        "evidence_count": len(evidence_objects),
                        **score_pipeline_artifacts(
                            report_payload={},
                            verification={},
                            evidence_count=len(evidence_objects),
                            gate_passed=True,
                            report_mode=report_mode,
                            branch_ids_present=branch_ids,
                            research_followup_queries=research_followup_queries,
                        ),
                    },
                )
                return None

        verifier = VerifierAgent()
        allowed_ev = {str(o.id) for o in evidence_objects if o.id}
        kc_n = len(analysis_rev.get("key_claims")) if isinstance(analysis_rev.get("key_claims"), list) else 0
        try:
            verification = await _timed_agent(
                session_id,
                "verifier",
                json.dumps(analysis_rev, ensure_ascii=False)[:8000],
                verifier.run(
                    analysis_rev,
                    evidence_objects,
                    session_id=session_id,
                    trace_id=session_id,
                ),
            )
        except Exception:
            logger.exception("Verifier failed for session %s", session_id)
            verification = {
                "overall": "insufficient",
                "gap_summary": "Verification step could not be completed.",
                "claim_assessments": [],
                "suggested_searches": [],
                "contradictions": [],
            }

        if not isinstance(verification, dict):
            verification = {
                "overall": "insufficient",
                "gap_summary": "Invalid verification output.",
                "claim_assessments": [],
            }

        verification, vstats = sanitize_verification_assessments(verification, allowed_ev)
        verifier_sanitize_stats = dict(vstats)
        ok_v, _vreason = verification_assessments_usable(verification, key_claims_count=kc_n)
        if not ok_v and kc_n > 0:
            try:
                verification_retry = await _timed_agent(
                    session_id,
                    "verifier_retry",
                    json.dumps(analysis_rev, ensure_ascii=False)[:8000],
                    verifier.run(
                        analysis_rev,
                        evidence_objects,
                        repair_hint="Previous JSON had missing or invalid claim_assessments. "
                        "Emit one assessment per key claim; evidence_ids MUST be UUIDs from the catalog only.",
                        session_id=session_id,
                        trace_id=session_id,
                    ),
                )
                if isinstance(verification_retry, dict):
                    verification, vstats2 = sanitize_verification_assessments(verification_retry, allowed_ev)
                    verifier_sanitize_stats["retry"] = vstats2
            except Exception:
                logger.exception("Verifier retry failed for session %s", session_id)

        if kc_n > 0:
            ca = verification.get("claim_assessments")
            n_ca = len([x for x in (ca if isinstance(ca, list) else []) if isinstance(x, dict)])
            if n_ca == 0:
                verification["overall"] = "insufficient"
                verification.setdefault("gap_summary", "")
                verification["gap_summary"] = (
                    (verification.get("gap_summary") or "")
                    + " Programmatic check: no valid claim_assessments after catalog sanitization."
                ).strip()

        insufficient = False
        if isinstance(verification, dict):
            if str(verification.get("overall", "")).lower() == "insufficient":
                insufficient = True
        if len(evidence_objects) == 0:
            insufficient = True

        await update_pipeline_state(session_id, "verification_done")
        if insufficient:
            await update_pipeline_state(session_id, "evidence_insufficient")
            gap_report = {
                "title": "Insufficient evidence for a full decision memo",
                "missing_evidence": verification.get("missing_evidence")
                if isinstance(verification, dict)
                else [],
                "suggested_searches": verification.get("suggested_searches")
                if isinstance(verification, dict)
                else [],
                "contradictions": verification.get("contradictions")
                if isinstance(verification, dict)
                else [],
                "notes": (verification.get("gap_summary") if isinstance(verification, dict) else "")
                or "Not enough grounded evidence to support a confident recommendation.",
            }
            if isinstance(critique, dict) and critique.get("missing_evidence"):
                gap_report["missing_evidence"] = list(
                    dict.fromkeys(
                        list(gap_report.get("missing_evidence") or [])
                        + list(critique.get("missing_evidence") or [])
                    )
                )
            await update_session_gap_report(session_id, gap_report)
            await update_session_status(session_id, "insufficient")
            await save_evaluation(
                session_id,
                {
                    "outcome": "insufficient",
                    "report_mode": report_mode,
                    "evidence_count": len(evidence_objects),
                    "unsupported_claim_count": _count_unsupported(verification if isinstance(verification, dict) else {}),
                    **score_pipeline_artifacts(
                        report_payload={},
                        verification=verification if isinstance(verification, dict) else {},
                        evidence_count=len(evidence_objects),
                        gate_passed=gate_passed_final,
                        report_mode=report_mode,
                        branch_ids_present=branch_ids,
                        verifier_invalid_id_strips=_verifier_invalid_strip_total(verifier_sanitize_stats),
                        research_followup_queries=research_followup_queries,
                    ),
                },
            )
            return None

        critique_for_writer: dict[str, Any] = (
            {**critique, "critic_post_revision": critique_post} if isinstance(critique, dict) else {"critic_post_revision": critique_post}
        )

        ver_dict = verification if isinstance(verification, dict) else {}
        reasoning_graph = build_reasoning_graph(analysis_rev).to_json_dict()
        reasoning_graph["verification_overall"] = str(ver_dict.get("overall", ""))
        merge_verifier_and_research_into_graph(reasoning_graph, ver_dict, research_contradictions_list)
        claim_support = build_claim_support(analysis_rev, evidence_objects, ver_dict)
        by_ev = {str(o.id): o for o in evidence_objects if o.id}
        await enrich_claim_rows_with_entailment(claim_support, by_ev)
        reasoning_graph["evidence_graph_v1"] = build_evidence_graph_v1(
            analysis=analysis_rev,
            verification=ver_dict,
            claim_support=claim_support,
            evidence_objects=evidence_objects,
        )

        writer = WriterAgent()
        report = await writer.run(
            query=query,
            analysis=analysis_rev,
            critique=critique_for_writer,
            research=research,
            prior_analysis=analysis,
            verification=ver_dict,
            reasoning_graph=reasoning_graph,
            claim_support=claim_support,
            session_id=session_id,
            trace_id=session_id,
        )
        ok_wl, wl_errors = validate_writer_claim_linkage(report, analysis_rev)
        if not ok_wl:
            report = await writer.run(
                query=query,
                analysis=analysis_rev,
                critique=critique_for_writer,
                research=research,
                prior_analysis=analysis,
                verification=ver_dict,
                reasoning_graph=reasoning_graph,
                claim_support=claim_support,
                repair_hint="Fix claim linkage errors:\n" + "\n".join(wl_errors),
                session_id=session_id,
                trace_id=session_id,
            )
            ok_wl, wl_errors = validate_writer_claim_linkage(report, analysis_rev)
        if not ok_wl:
            await update_pipeline_state(session_id, "evidence_insufficient")
            await update_session_gap_report(
                session_id,
                {
                    "title": "Writer output failed claim-ID validation",
                    "missing_evidence": wl_errors,
                    "suggested_searches": [],
                    "contradictions": [],
                    "notes": "The writer must tie executive_insights, recommendation_claim_ids, and key_risks_structured to analyst key_claims.claim_id values.",
                },
            )
            await update_session_status(session_id, "insufficient")
            await save_evaluation(
                session_id,
                {
                    "outcome": "insufficient",
                    "reason": "writer_claim_linkage",
                    "report_mode": report_mode,
                    "evidence_count": len(evidence_objects),
                    **score_pipeline_artifacts(
                        report_payload={},
                        verification=ver_dict,
                        evidence_count=len(evidence_objects),
                        gate_passed=gate_passed_final,
                        report_mode=report_mode,
                        branch_ids_present=branch_ids,
                        verifier_invalid_id_strips=_verifier_invalid_strip_total(verifier_sanitize_stats),
                        research_followup_queries=research_followup_queries,
                    ),
                },
            )
            return None

        contra_sev = compute_contradiction_severity(
            research_contradictions=research_contradictions_list,
            verification=ver_dict,
            claim_support=claim_support,
        )
        apply_confidence_cap(report, contra_sev)
        merge_contradiction_into_caveats(
            report,
            build_contradiction_caveat(contra_sev, research_contradictions_list, ver_dict),
        )
        if contra_sev > 0:
            await merge_session_metadata(session_id, {"contradiction_severity": contra_sev})

        raw_writer = json.dumps(report.model_dump(), ensure_ascii=False)
        await save_agent_output(
            session_id,
            "writer",
            json.dumps(critique, ensure_ascii=False)[:8000],
            raw_writer,
        )

        evidence_bundle = build_evidence_bundle(research, evidence_objects)
        unsupported_n = _count_unsupported(ver_dict)
        report_id = await save_report(
            session_id,
            report,
            raw_output=raw_writer,
            evidence_bundle=evidence_bundle,
            verification=ver_dict,
            evidence_count=len(evidence_objects),
            unsupported_claim_count=unsupported_n,
            consulting_payload=report.consulting_payload_dict(),
            reasoning_graph=reasoning_graph,
            claim_support=claim_support,
        )
        if report_id:
            await save_claim_evidence_links(report_id, _claim_links_from_verification(report_id, ver_dict))
            await replace_claim_support_rows(session_id, report_id, claim_support)
            # Phase 7: structured grounder runs as a post-write step.
            # Phase 8 + Batch 1: NLI verifier streams per-claim — we save the
            # answer EARLY (state="pending") so the frontend renders citations
            # as `verifying...`, then patch in NLI results as each claim resolves.
            try:
                from agents.nli_verifier import verify_structured_answer
                from agents.structured_grounder import ground_writer_payload
                from db.queries import save_structured_answer
                from storage.chunk_queries import list_chunks_for_session

                grounded = await ground_writer_payload(session_id=session_id, payload=report)

                # Save the grounder's output IMMEDIATELY (NLI hasn't started).
                # Frontend will see citations as `verifying` until NLI fills in.
                grounded.verification_state = "pending"
                await save_structured_answer(report_id, grounded.model_dump(mode="json"))

                chunks_list = await list_chunks_for_session(session_id, limit=200)
                chunks_by_id = {c["id"]: c for c in chunks_list}

                # Persist after each claim's NLI pairs resolve.
                async def _persist_progress(answer):
                    await save_structured_answer(report_id, answer.model_dump(mode="json"))

                grounded = await verify_structured_answer(
                    grounded, chunks_by_id, on_progress=_persist_progress
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("structured grounder / NLI skipped: %s", e)

        trust_payload = build_trust_labels(
            report=report.model_dump(),
            verification=ver_dict,
            evidence_objects=[e.model_dump() for e in evidence_objects],
            contradiction_severity=contra_sev,
        )
        ca_list = ver_dict.get("claim_assessments") if isinstance(ver_dict.get("claim_assessments"), list) else []
        n_assess = len([x for x in ca_list if isinstance(x, dict)])
        trust_payload["claims_verified_hint"] = f"{n_assess} verifier assessments recorded"
        trust_obj = TrustObject(
            confidence_level=report.confidence_level,
            confidence_display=report.confidence_level,
            evidence_strength_label=str(trust_payload.get("evidence_strength_label") or ""),
            verification_overall_label=str(trust_payload.get("verification_overall_label") or ""),
            contradiction_severity_label=str(trust_payload.get("contradiction_severity_label") or ""),
            unsupported_claims_count=int(trust_payload.get("unsupported_claims_count") or 0),
            what_capped_confidence=str(trust_payload.get("what_capped_confidence") or ""),
            claims_verified_hint=str(trust_payload.get("claims_verified_hint") or ""),
        )
        await merge_session_metadata(session_id, {"trust_object": trust_obj.model_dump()})

        nli_vals = [float(r["nli_confidence"]) for r in claim_support if "nli_confidence" in r]
        mean_nli = sum(nli_vals) / len(nli_vals) if nli_vals else None
        rubric = score_pipeline_artifacts(
            report_payload=report.model_dump(),
            verification=ver_dict,
            evidence_count=len(evidence_objects),
            gate_passed=gate_passed_final,
            consulting_payload=report.consulting_payload_dict(),
            report_mode=report_mode,
            branch_ids_present=branch_ids,
            verifier_invalid_id_strips=_verifier_invalid_strip_total(verifier_sanitize_stats),
            mean_entailment_score=mean_nli,
            research_followup_queries=research_followup_queries,
        )
        await save_evaluation(
            session_id,
            {
                "outcome": "complete",
                "report_mode": report_mode,
                "evidence_count": len(evidence_objects),
                "unsupported_claim_count": unsupported_n,
                **rubric,
            },
        )
        await update_pipeline_state(session_id, "deliverable_ready")
        await update_session_status(session_id, "complete")
        await _pipeline_trace(
            session_id,
            "complete",
            f"unsupported_claims={unsupported_n} contradiction_severity={contra_sev}",
        )
        return report
    except Exception as e:
        logger.exception("Pipeline failed for session %s: %s", session_id, e)
        try:
            await _pipeline_trace(session_id, "failed", str(e)[:400])
        except Exception:
            logger.exception("Could not append pipeline trace for %s", session_id)
        await update_session_status(session_id, "failed")
        try:
            await update_pipeline_state(session_id, "failed")
        except Exception:
            logger.exception("Could not persist failed pipeline_state for %s", session_id)
        raise
