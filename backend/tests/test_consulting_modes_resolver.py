"""Phase 2 / Week 6 / Day 1 — tests for the layered consulting-mode
resolver. Hermetic: monkey-patches the firm + engagement loaders so the
tests don't need a live Postgres."""

from __future__ import annotations

import pathlib
import textwrap
from typing import Any

import pytest

from core.consulting_modes import (
    ModeConfigError,
    ModeNotFoundError,
    ResolvedConsultingMode,
    load_mode_legacy,
    resolve_mode,
)
from core.consulting_modes import resolver as resolver_mod
from core.consulting_modes.resolver import OVERLAY_MAX_CHARS

FIRM_A = "11111111-1111-1111-1111-111111111111"
ENG_X = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _yaml_and_cache_reset(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Each test starts with a known YAML and an empty resolver cache.
    Many tests write a temp YAML and point the resolver at it via
    ARGUS_CONSULTING_MODES_PATH. _yaml_reset clears the YAML memo and the
    resolution cache.
    """
    resolver_mod._yaml_reset()
    yield
    resolver_mod._yaml_reset()


def _write_yaml(tmp_path: pathlib.Path, body: str, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "consulting_modes.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setenv("ARGUS_CONSULTING_MODES_PATH", str(p))
    resolver_mod._yaml_reset()


def _patch_loaders(
    monkeypatch: pytest.MonkeyPatch,
    *,
    firm: dict[str, Any] | None = None,
    engagement: tuple[str, dict[str, Any]] | None = None,
) -> None:
    """Replace the DB-backed firm + engagement loaders with in-memory stubs.

    `engagement` is a (mode_name, config) tuple — the resolver only
    applies an engagement override when its mode_name matches the
    resolution name, and we want the tests to exercise that gate.
    """

    async def _firm_stub(name: str, firm_id: Any) -> dict[str, Any] | None:
        return firm

    async def _eng_stub(eng_id: Any, name: str) -> dict[str, Any] | None:
        if engagement is None:
            return None
        if engagement[0] != name:
            return None
        return engagement[1]

    monkeypatch.setattr(resolver_mod, "_load_firm_override", _firm_stub)
    monkeypatch.setattr(resolver_mod, "_load_engagement_override", _eng_stub)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_built_in_only(tmp_path, monkeypatch):
    _write_yaml(
        tmp_path,
        """
        focused_review:
          label: Focused review
          required_branches: [signal, contradiction]
          min_evidence_objects: 3
          writer_overlay: "Stay quantitative."
        """,
        monkeypatch,
    )
    _patch_loaders(monkeypatch)

    m = await resolve_mode("focused_review", firm_id=FIRM_A)
    assert isinstance(m, ResolvedConsultingMode)
    assert m.name == "focused_review"
    assert m.display_name == "Focused review"
    assert m.required_branches == ["signal", "contradiction"]
    assert m.min_evidence_objects == 3
    assert m.writer_overlay == "Stay quantitative."
    # Every field's provenance is built_in when no firm/engagement override.
    assert all(v == "built_in" for v in m.layer_provenance.values()), m.layer_provenance


@pytest.mark.asyncio
async def test_firm_override_replaces_lists(tmp_path, monkeypatch):
    _write_yaml(
        tmp_path,
        """
        playbook:
          label: Playbook
          required_branches: [a, b, c]
        """,
        monkeypatch,
    )
    _patch_loaders(monkeypatch, firm={"required_branches": ["X", "Y"]})

    m = await resolve_mode("playbook", firm_id=FIRM_A)
    assert m.required_branches == ["X", "Y"]
    assert m.layer_provenance["required_branches"] == "firm"


@pytest.mark.asyncio
async def test_firm_override_appends_writer_overlay(tmp_path, monkeypatch):
    _write_yaml(
        tmp_path,
        """
        review:
          label: Review
          writer_overlay: "Stay quantitative."
        """,
        monkeypatch,
    )
    _patch_loaders(monkeypatch, firm={"writer_overlay": "End with a 90-day plan."})

    m = await resolve_mode("review", firm_id=FIRM_A)
    assert m.writer_overlay == "Stay quantitative.\n\nEnd with a 90-day plan."
    assert m.layer_provenance["writer_overlay"] == "firm"


@pytest.mark.asyncio
async def test_firm_override_deep_merges_trust_rules(tmp_path, monkeypatch):
    _write_yaml(
        tmp_path,
        """
        review:
          label: Review
          trust_tier_rules:
            news: general
        """,
        monkeypatch,
    )
    _patch_loaders(
        monkeypatch,
        firm={"trust_tier_rules": {"sec_filing": "firm_vetted"}},
    )

    m = await resolve_mode("review", firm_id=FIRM_A)
    assert m.trust_tier_rules == {"news": "general", "sec_filing": "firm_vetted"}
    assert m.layer_provenance["trust_tier_rules"] == "firm"


@pytest.mark.asyncio
async def test_engagement_override_layers_on_top(tmp_path, monkeypatch):
    _write_yaml(
        tmp_path,
        """
        review:
          label: Review
          writer_overlay: "Built-in style."
        """,
        monkeypatch,
    )
    _patch_loaders(
        monkeypatch,
        firm={"writer_overlay": "Firm voice."},
        engagement=("review", {"writer_overlay": "Engagement-specific note."}),
    )

    m = await resolve_mode("review", firm_id=FIRM_A, engagement_id=ENG_X)
    assert m.writer_overlay == (
        "Built-in style.\n\nFirm voice.\n\nEngagement-specific note."
    )
    assert m.layer_provenance["writer_overlay"] == "engagement"


@pytest.mark.asyncio
async def test_layer_provenance_records_correctly(tmp_path, monkeypatch):
    _write_yaml(
        tmp_path,
        """
        review:
          label: Review
          description: "Built-in description."
          required_branches: [a]
          writer_overlay: "Base."
        """,
        monkeypatch,
    )
    # firm sets description + required_branches; engagement sets writer_overlay.
    # display_name is untouched -> stays built_in.
    _patch_loaders(
        monkeypatch,
        firm={"description": "Firm description.", "required_branches": ["b", "c"]},
        engagement=("review", {"writer_overlay": "Eng overlay."}),
    )

    m = await resolve_mode("review", firm_id=FIRM_A, engagement_id=ENG_X)
    assert m.layer_provenance["display_name"] == "built_in"
    assert m.layer_provenance["description"] == "firm"
    assert m.layer_provenance["required_branches"] == "firm"
    assert m.layer_provenance["writer_overlay"] == "engagement"
    # planner_overlay never touched anywhere -> built_in
    assert m.layer_provenance["planner_overlay"] == "built_in"


@pytest.mark.asyncio
async def test_overlay_size_cap_rejects(tmp_path, monkeypatch):
    _write_yaml(
        tmp_path,
        """
        review:
          label: Review
        """,
        monkeypatch,
    )
    big = "x" * (OVERLAY_MAX_CHARS + 1)
    _patch_loaders(monkeypatch, firm={"writer_overlay": big})

    with pytest.raises(ModeConfigError, match=r"writer_overlay is \d+ chars"):
        await resolve_mode("review", firm_id=FIRM_A)


@pytest.mark.asyncio
async def test_unknown_mode_name_raises(tmp_path, monkeypatch):
    _write_yaml(
        tmp_path,
        """
        general:
          label: General
        """,
        monkeypatch,
    )
    _patch_loaders(monkeypatch)

    with pytest.raises(ModeNotFoundError):
        await resolve_mode("does_not_exist", firm_id=FIRM_A)


def test_load_mode_legacy_matches_builtin_yaml():
    """For every mode in the production YAML, load_mode_legacy returns a
    ResolvedConsultingMode whose required_branches and min_evidence_objects
    match the YAML row. This locks the legacy shim's contract: existing
    callers reading get_mode_config() and migrating to load_mode_legacy()
    see the same numbers."""
    # Reset to use the production YAML (no env override).
    resolver_mod._yaml_reset()
    raw = resolver_mod._load_yaml()
    assert raw, "production consulting_modes.yaml should not be empty"

    for name, row in raw.items():
        m = load_mode_legacy(name)
        assert m.name == name
        assert m.required_branches == list(row.get("required_branches") or [])
        assert m.min_evidence_objects == int(row.get("min_evidence_objects") or 0)
        # And the layer_provenance is purely built-in.
        assert all(v == "built_in" for v in m.layer_provenance.values())


# ---------------------------------------------------------------------------
# W7/D2 — m_and_a_diligence built-in mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_loads_m_and_a_mode(monkeypatch):
    """resolve_mode for the new built-in returns the full mode shape:
    6 required branches, 6 reasoning slots, 4 source priorities,
    trust-tier rules for uploaded/sec_filing/transcript/news, and the
    metadata block flattened to top level."""
    # Use the production YAML (no env override).
    resolver_mod._yaml_reset()
    _patch_loaders(monkeypatch)  # no firm/engagement override

    m = await resolve_mode("m_and_a_diligence", firm_id=FIRM_A)

    assert m.name == "m_and_a_diligence"
    assert m.display_name == "M&A diligence"
    assert len(m.required_branches) == 6
    assert "synergy_quantification" in m.required_branches
    assert "valuation_triangulation" in m.required_branches
    assert len(m.reasoning_slots) == 6
    assert "deal_breakers" in m.reasoning_slots
    assert m.source_priorities_default == ["uploaded", "sec_filing", "transcript", "news"]
    assert m.trust_tier_rules.get("uploaded") == "firm_vetted"
    assert m.trust_tier_rules.get("news") == "web_general"
    assert m.metadata.get("schema_version") == "1.0"
    assert m.metadata.get("writer_payload_class") == "MAndADiligenceReportPayload"
    # All provenance is built_in (no firm/engagement override applied).
    assert all(v == "built_in" for v in m.layer_provenance.values())


def test_m_and_a_mode_in_load_mode_legacy():
    """Legacy synchronous shim returns the new built-in too."""
    resolver_mod._yaml_reset()
    m = load_mode_legacy("m_and_a_diligence")
    assert m.name == "m_and_a_diligence"
    assert "synergy_quantification" in m.required_branches
    assert "deal_breakers" in m.reasoning_slots
