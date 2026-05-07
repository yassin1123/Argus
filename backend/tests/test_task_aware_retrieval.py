"""Task-aware retrieval routing tests (Phase 1 / Week 3 / Day 4).

Verify the planner→researcher contract:
  - PlannerTask.source_priorities is parsed and normalised by the schema.
  - When set, the orchestrator routes through `hybrid_search` with a
    source_type filter, walks the priority list, and spills into the next
    kind if the first source returns < MIN_RESULTS.
  - Web search is gated behind "web" being explicitly in source_priorities;
    tasks without "web" do not trigger SerpAPI calls even when
    SERPAPI_KEY is configured.
  - Tasks without any source_priorities use the legacy retrieve_evidence
    path (backward compatibility).

Tests 2-4 monkeypatch all network/DB dependencies of the orchestrator so
they run hermetically. Test 1 is a pure schema test.
"""

from __future__ import annotations

from typing import Any

import pytest

from agents.planner import PlannerTask
from agents.research import orchestrator as orch_mod
from models.evidence import EvidenceObject


# ---------------------------------------------------------------------------
# Test 1 — schema: PlannerTask.source_priorities parsing
# ---------------------------------------------------------------------------


def test_planner_task_source_priorities_parsing() -> None:
    """Coercion accepts valid kinds (case-insensitive, hyphen-tolerant),
    drops unknown ones, dedupes, and treats missing as None for backward
    compat with plans the planner emitted before Day 4.
    """
    # Valid list, preserved in order:
    t = PlannerTask.model_validate(
        {
            "id": 1,
            "question": "q",
            "type": "factual",
            "priority": "high",
            "why_it_matters": "x",
            "source_priorities": ["sec_filing", "uploaded", "web"],
        }
    )
    assert t.source_priorities == ["sec_filing", "uploaded", "web"]

    # Mixed cases, hyphens, dupes, unknowns: normalise + drop + dedupe.
    t2 = PlannerTask.model_validate(
        {"source_priorities": ["sec-filing", "Uploaded", "twitter", "web", "web"]}
    )
    assert t2.source_priorities == ["sec_filing", "uploaded", "web"]

    # Omitted → None (backward compat sentinel).
    t3 = PlannerTask.model_validate({"id": 2})
    assert t3.source_priorities is None

    # Empty list collapses to None — same semantics as omitted.
    t4 = PlannerTask.model_validate({"source_priorities": []})
    assert t4.source_priorities is None

    # Non-list input → None (lenient parser, don't fail the whole task).
    t5 = PlannerTask.model_validate({"source_priorities": "sec_filing"})
    assert t5.source_priorities is None


# ---------------------------------------------------------------------------
# Shared monkeypatch helpers for the orchestrator-level tests.
# ---------------------------------------------------------------------------


class _Recorder:
    """Capture all calls to a stubbed coroutine so the test can assert on them."""

    def __init__(self, return_value: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.return_value = return_value

    async def __call__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"args": args, "kwargs": kwargs})
        rv = self.return_value
        if callable(rv):
            return rv(*args, **kwargs)
        return rv


def _stub_synth_finding(_q: str, _objs: list[EvidenceObject]) -> dict[str, str]:
    return {"finding": "synthetic", "confidence": "high", "gaps": ""}


async def _stub_synth_finding_async(q: str, objs: list[EvidenceObject]) -> dict[str, str]:
    return _stub_synth_finding(q, objs)


async def _stub_planned_queries(q: str) -> list[str]:
    return [q]


async def _stub_insert_evidence_objects(objs: list[EvidenceObject]) -> list[EvidenceObject]:
    """Hand back the same objects with synthetic IDs, no DB hit."""
    out: list[EvidenceObject] = []
    for i, o in enumerate(objs):
        o.id = f"id-{i}"
        out.append(o)
    return out


async def _stub_detect_tensions(_objs: list[EvidenceObject]) -> list[str]:
    return []


def _make_chunks(source_type: str, n: int, base: int = 0) -> list[dict[str, Any]]:
    out = []
    for i in range(n):
        out.append(
            {
                "id": f"{source_type}-{base + i}",
                "session_id": None,
                "content": f"{source_type} body {i}",
                "source_type": source_type,
                "position": i,
                "page": None,
                "slide": None,
                "timestamp_str": None,
                "speaker": None,
                "section_heading": f"{source_type} sec {i}",
                "source_filename": f"{source_type}_doc_{i}.txt",
                "source_url": f"https://example.test/{source_type}/{i}",
                "trust_level": "firm_vetted",
                "metadata": {"form": "10-K", "filing_date": "2025-09-30"},
                "score": 0.5 - 0.01 * i,
                "fused_score": 0.5 - 0.01 * i,
            }
        )
    return out


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the LLM/DB/web side-effects we don't want a unit test to hit."""
    monkeypatch.setattr(orch_mod, "_synthesize_finding", _stub_synth_finding_async)
    monkeypatch.setattr(orch_mod, "_planned_queries", _stub_planned_queries)
    monkeypatch.setattr(orch_mod, "insert_evidence_objects", _stub_insert_evidence_objects)
    monkeypatch.setattr(orch_mod, "_detect_evidence_tensions", _stub_detect_tensions)


# ---------------------------------------------------------------------------
# Test 2 — orchestrator filters by single source_priority
# ---------------------------------------------------------------------------


async def test_orchestrator_routes_to_sec_filing_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task with source_priorities=["sec_filing"] queries hybrid_search with
    source_types=["sec_filing"] and never falls back to retrieve_evidence
    or web search.
    """
    _patch_common(monkeypatch)

    hybrid_calls: list[dict[str, Any]] = []

    async def _hybrid(*, engagement_id, query, k, candidate_k, mode, source_types):
        hybrid_calls.append(
            {"query": query, "source_types": source_types, "k": k}
        )
        # Plenty of hits — no spillover should fire.
        return {"results": _make_chunks("sec_filing", 6), "vector_count": 6, "keyword_count": 6}

    monkeypatch.setattr(orch_mod, "hybrid_search", _hybrid)

    legacy_calls: list[Any] = []

    async def _legacy_retrieve(*args, **kwargs):
        legacy_calls.append((args, kwargs))
        return []

    monkeypatch.setattr(orch_mod, "retrieve_evidence", _legacy_retrieve)

    web_parallel = _Recorder(return_value=[])
    web_struct = _Recorder(return_value=[])
    monkeypatch.setattr(orch_mod, "search_web_parallel", web_parallel)
    monkeypatch.setattr(orch_mod, "search_web_structured", web_struct)
    monkeypatch.setattr(orch_mod, "SERPAPI_KEY", "fake-key-for-test")

    plan = {
        "objective": "test",
        "tasks": [
            {
                "id": 1,
                "question": "Apple iPhone segment revenue trend",
                "type": "factual",
                "priority": "high",
                "why_it_matters": "x",
                "source_priorities": ["sec_filing"],
            }
        ],
    }
    result = await orch_mod.ResearchOrchestrator().run(
        session_id="00000000-0000-0000-0000-000000000001",
        plan=plan,
        context="",
    )

    # Filter was applied:
    assert len(hybrid_calls) == 1
    assert hybrid_calls[0]["source_types"] == ["sec_filing"]
    # Legacy path skipped:
    assert legacy_calls == []
    # Web skipped (no "web" in priorities):
    assert web_parallel.calls == []
    assert web_struct.calls == []
    # Result includes the SEC-only retrieval snapshot.
    snap = result["_retrieval_hits"][0]
    assert snap["source_priorities"] == ["sec_filing"]
    assert snap["sources_consulted"] == ["sec_filing"]
    assert all(h["source_type"] == "sec_filing" for h in snap["hits"])


# ---------------------------------------------------------------------------
# Test 3 — spillover when first priority returns < MIN_RESULTS
# ---------------------------------------------------------------------------


async def test_orchestrator_spills_into_next_priority_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Priority list ["uploaded", "sec_filing"]: if uploaded returns
    fewer than _TASK_AWARE_MIN_RESULTS hits, the orchestrator should
    also query sec_filing and merge results.
    """
    _patch_common(monkeypatch)

    n_under = orch_mod._TASK_AWARE_MIN_RESULTS - 1
    hybrid_calls: list[list[str] | None] = []

    async def _hybrid(*, engagement_id, query, k, candidate_k, mode, source_types):
        hybrid_calls.append(source_types)
        if source_types == ["uploaded"]:
            return {"results": _make_chunks("uploaded", n_under)}
        if source_types == ["sec_filing"]:
            return {"results": _make_chunks("sec_filing", 4, base=100)}
        return {"results": []}

    monkeypatch.setattr(orch_mod, "hybrid_search", _hybrid)

    async def _legacy_retrieve(*args, **kwargs):
        return []

    monkeypatch.setattr(orch_mod, "retrieve_evidence", _legacy_retrieve)
    monkeypatch.setattr(orch_mod, "SERPAPI_KEY", "")  # web off
    monkeypatch.setattr(orch_mod, "search_web_parallel", _Recorder(return_value=[]))
    monkeypatch.setattr(orch_mod, "search_web_structured", _Recorder(return_value=[]))

    plan = {
        "objective": "test",
        "tasks": [
            {
                "id": 1,
                "question": "What does the CIM say about iPhone segment revenue?",
                "type": "factual",
                "priority": "medium",
                "why_it_matters": "...",
                "source_priorities": ["uploaded", "sec_filing"],
            }
        ],
    }
    result = await orch_mod.ResearchOrchestrator().run(
        session_id="00000000-0000-0000-0000-000000000001",
        plan=plan,
        context="",
    )

    # We saw both priorities consulted, in the right order.
    assert hybrid_calls == [["uploaded"], ["sec_filing"]]
    snap = result["_retrieval_hits"][0]
    assert snap["sources_consulted"] == ["uploaded", "sec_filing"]
    types_seen = {h["source_type"] for h in snap["hits"]}
    assert types_seen == {"uploaded", "sec_filing"}
    # Hits from both sources are present (n_under + 4).
    assert len(snap["hits"]) == n_under + 4


# ---------------------------------------------------------------------------
# Test 4 — web gating: presence/absence of "web" in priorities
# ---------------------------------------------------------------------------


async def test_orchestrator_web_gated_by_priorities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When source_priorities omits "web", search_web_parallel is never
    called even with SERPAPI_KEY set. When "web" is included, it IS
    called. This is the replacement for the legacy
    `if priority == "high": search_web` heuristic.
    """
    _patch_common(monkeypatch)

    async def _hybrid(*, engagement_id, query, k, candidate_k, mode, source_types):
        return {"results": _make_chunks(source_types[0] if source_types else "uploaded", 6)}

    async def _legacy_retrieve(*args, **kwargs):
        return []

    monkeypatch.setattr(orch_mod, "hybrid_search", _hybrid)
    monkeypatch.setattr(orch_mod, "retrieve_evidence", _legacy_retrieve)
    monkeypatch.setattr(orch_mod, "SERPAPI_KEY", "fake-key-for-test")

    web_parallel = _Recorder(return_value=[])
    web_struct = _Recorder(return_value=[])
    monkeypatch.setattr(orch_mod, "search_web_parallel", web_parallel)
    monkeypatch.setattr(orch_mod, "search_web_structured", web_struct)
    # _append_web_extractions calls fetch_page_text + LLM extractor; stub
    # both so any web call would actually consume them.
    monkeypatch.setattr(orch_mod, "_append_web_extractions", _Recorder(return_value=None))

    # --- (a) No "web" in priorities → no web calls.
    plan_no_web = {
        "objective": "test",
        "tasks": [
            {
                "id": 1,
                "question": "Risk factors in the latest 10-K",
                "type": "qualitative",
                "priority": "high",  # NB: legacy heuristic would have web-searched.
                "why_it_matters": "...",
                "source_priorities": ["sec_filing"],
            }
        ],
    }
    await orch_mod.ResearchOrchestrator().run(
        session_id="00000000-0000-0000-0000-000000000002",
        plan=plan_no_web,
        context="",
    )
    assert web_parallel.calls == [], (
        "search_web_parallel must NOT fire when 'web' is absent from source_priorities"
    )
    assert web_struct.calls == []

    # --- (b) "web" in priorities → search_web_parallel IS called.
    plan_with_web = {
        "objective": "test",
        "tasks": [
            {
                "id": 1,
                "question": "Recent analyst chatter on the deal",
                "type": "factual",
                "priority": "low",
                "why_it_matters": "...",
                "source_priorities": ["news", "web"],
            }
        ],
    }
    await orch_mod.ResearchOrchestrator().run(
        session_id="00000000-0000-0000-0000-000000000003",
        plan=plan_with_web,
        context="",
    )
    assert len(web_parallel.calls) == 1, (
        "search_web_parallel must fire exactly once when 'web' is in source_priorities"
    )

    # --- (c) Backward compat: no source_priorities → web fires (legacy).
    web_parallel.calls.clear()
    plan_legacy = {
        "objective": "test",
        "tasks": [
            {
                "id": 1,
                "question": "Some question",
                "type": "factual",
                "priority": "medium",
                "why_it_matters": "...",
                # source_priorities omitted on purpose
            }
        ],
    }
    await orch_mod.ResearchOrchestrator().run(
        session_id="00000000-0000-0000-0000-000000000004",
        plan=plan_legacy,
        context="",
    )
    assert len(web_parallel.calls) == 1, (
        "Tasks without source_priorities must keep legacy always-on web behavior"
    )
