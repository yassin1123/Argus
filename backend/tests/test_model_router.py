import os

import core.model_router as mr


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
