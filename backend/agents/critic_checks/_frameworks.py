"""Framework-requirement critic check — Phase 2 / Week 8 / Day 4.

Mode-driven, not mode-name-driven: this check fires for EVERY mode
based on what its ``frameworks`` config declares. M&A diligence
requires ``two_by_two``; growth_strategy requires
``porters_five_forces``; modes without a frameworks declaration
(``general``, ``market_entry``, ``due_diligence``) get no findings
because their config is ``None``.

``required`` framework missing → ``error``-level CriticIssue.
``optional`` framework missing → no finding (advisory, not enforced).
"""

from __future__ import annotations

from typing import Any

from core.consulting_modes import FrameworksModeConfig

from .types import CriticIssue


def check_required_frameworks(
    payload: Any,
    mode_config: FrameworksModeConfig | None,
) -> list[CriticIssue]:
    """Return one ``error`` CriticIssue per required framework slot
    that is missing or null on the payload.

    ``payload`` may be a Pydantic ``WriterReportBase`` or a dict
    (orchestrator passes the model; tests sometimes pass a dump).
    Both shapes are handled.
    """
    if mode_config is None or not mode_config.required:
        return []

    frameworks_obj = _read_frameworks(payload)

    issues: list[CriticIssue] = []
    for slot in mode_config.required:
        if frameworks_obj is None:
            issues.append(
                CriticIssue(
                    level="error",
                    field=f"frameworks.{slot}",
                    message=(
                        f"Mode requires {slot!r} framework but the writer payload "
                        f"has no frameworks block at all."
                    ),
                )
            )
            continue
        value = _read_slot(frameworks_obj, slot)
        if value is None:
            issues.append(
                CriticIssue(
                    level="error",
                    field=f"frameworks.{slot}",
                    message=(
                        f"Mode requires {slot!r} framework but the writer left "
                        f"frameworks.{slot} null."
                    ),
                )
            )
    return issues


def _read_frameworks(payload: Any) -> Any:
    if payload is None:
        return None
    if hasattr(payload, "frameworks"):
        return getattr(payload, "frameworks", None)
    if isinstance(payload, dict):
        return payload.get("frameworks")
    return None


def _read_slot(frameworks_obj: Any, slot: str) -> Any:
    if hasattr(frameworks_obj, slot):
        return getattr(frameworks_obj, slot, None)
    if isinstance(frameworks_obj, dict):
        return frameworks_obj.get(slot)
    return None
