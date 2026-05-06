import os

import pytest

import core.model_router as mr
from core.provider_family import assert_cross_family, family_of


def test_resolve_planner_defaults() -> None:
    mr.reload_config()
    cfg = mr.resolve("planner")
    assert cfg.model
    assert cfg.max_tokens > 0


def test_env_override_model(monkeypatch) -> None:
    mr.reload_config()
    monkeypatch.setenv("ARGUS_MODEL_PLANNER", "gpt-4o-mini")
    cfg = mr.resolve("planner")
    assert cfg.model == "gpt-4o-mini"
    monkeypatch.delenv("ARGUS_MODEL_PLANNER", raising=False)
    mr.reload_config()


# ---------------------------------------------------------------------------
# Cross-family verification wedge (Phase 1 / Week 1, Day 3)
# ---------------------------------------------------------------------------


def _startup_cross_family_check() -> None:
    """Mimic the import-time block in backend/main.py so we can drive it from
    a test without spinning up FastAPI. If main.py changes, update this too.
    """
    analyst_cfg = mr.resolve("analyst")
    verifier_cfg = mr.resolve("verifier")
    assert_cross_family(analyst_cfg.model, verifier_cfg.model)


def test_same_family_routing_fails_to_boot(monkeypatch) -> None:
    """Forcing analyst and verifier to both be OpenAI must crash the boot
    check — same-family verification is the failure mode the wedge exists
    to prevent.
    """
    monkeypatch.setenv("ARGUS_MODEL_ANALYST", "openai/gpt-4o")
    monkeypatch.setenv("ARGUS_MODEL_VERIFIER", "openai/gpt-4o-mini")
    mr.reload_config()
    with pytest.raises(RuntimeError, match=r"cross-family"):
        _startup_cross_family_check()
    monkeypatch.delenv("ARGUS_MODEL_ANALYST", raising=False)
    monkeypatch.delenv("ARGUS_MODEL_VERIFIER", raising=False)
    mr.reload_config()


def test_yaml_routing_satisfies_cross_family() -> None:
    """The committed models.yaml must already satisfy the cross-family rule;
    if a future edit puts analyst and verifier in the same family, this
    test fails alongside the boot crash.
    """
    mr.reload_config()
    # Should not raise.
    _startup_cross_family_check()


def _chain_models(task: str) -> list[str]:
    """Models a task may actually run on: primary first, then fallback.

    The router uses one fallback level (see core/inference/generate.py:
    completion_with_config). If we ever add deeper chains, extend this.
    """
    cfg = mr.resolve(task)
    chain: list[str] = [cfg.model]
    if cfg.fallback_model and cfg.fallback_model != cfg.model:
        chain.append(cfg.fallback_model)
    return chain


def test_no_fallback_chain_collides_with_verifier_family() -> None:
    """Walk the analyst and writer fallback chains and confirm no model in
    either chain shares a provider family with any model in the verifier's
    own chain (primary OR fallback).

    Why this matters: production calls use a single-level fallback. If the
    analyst falls back from anthropic to openai while the verifier stays on
    its openai primary, we silently lose cross-family verification — exactly
    the hole the boot-time check would NOT catch (because the boot check
    only sees primaries). This invariant is enforced statically against
    the YAML so a routing edit can't reintroduce it.
    """
    mr.reload_config()
    analyst_chain = _chain_models("analyst")
    writer_chain = _chain_models("writer")
    verifier_chain = _chain_models("verifier")

    verifier_families = {family_of(m) for m in verifier_chain}

    for label, chain in (("analyst", analyst_chain), ("writer", writer_chain)):
        chain_families = {family_of(m) for m in chain}
        collision = chain_families & verifier_families
        assert not collision, (
            f"{label} fallback chain {chain} (families={sorted(chain_families)}) "
            f"shares family/families {sorted(collision)} with the verifier chain "
            f"{verifier_chain} (families={sorted(verifier_families)}). "
            "On a fallback the verifier would be judging same-family output. "
            "Either narrow the verifier chain or move this task's fallback to "
            "an intra-family option that preserves the cross-family contract."
        )
