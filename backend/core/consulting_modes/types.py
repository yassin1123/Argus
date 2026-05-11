"""Phase 2 / Week 6 / Day 1 — type definitions for the layered consulting-
mode resolver.

`ResolvedConsultingMode` is the final, post-merge view a planner / writer /
verifier sees. The `layer_provenance` map records which layer (built-in,
firm, or engagement) was the *topmost* contributor to each field — when a
prompt looks weird in production, this is the one-line "where did that
come from" answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LayerName = Literal["built_in", "firm", "engagement"]

# The built-in YAML allows these source_type literals; firm overrides are
# free to set the same set. Validated at merge time.
SourceTypeLiteral = Literal[
    "uploaded", "sec_filing", "transcript", "news", "ch_filing", "web"
]

# W8/D4: framework slot identifiers. Mirrors the keys on
# ``FrameworksPayload`` in ``agents/writer/schemas/frameworks/__init__.py``
# — kept as a closed Literal so the resolver can reject typos at
# config-load time instead of letting an "untwo_by_two" silently
# disable the requirement.
FrameworkSlotLiteral = Literal["two_by_two", "porters_five_forces", "value_chain"]


@dataclass(frozen=True)
class FrameworksModeConfig:
    """Per-mode declaration of which structured frameworks the writer
    is required to populate and which are merely available.

    Resolver merge semantics: full-replace on both lists (same shape
    as ``required_branches`` in W6 — a firm or engagement layer that
    declares ``frameworks:`` REPLACES the built-in lists, it does
    not append). Empty defaults mean "no opinion": built-in modes
    without a ``frameworks:`` block resolve to
    ``FrameworksModeConfig(required=[], optional=[])`` and the
    critic check is a no-op.
    """

    required: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedConsultingMode:
    """Final view of a consulting mode after merging built-in + firm +
    engagement layers."""

    name: str
    display_name: str
    description: str
    required_branches: list[str]
    reasoning_slots: list[str]
    source_priorities_default: list[str]
    trust_tier_rules: dict[str, str]
    writer_overlay: str
    planner_overlay: str
    layer_provenance: dict[str, LayerName]

    # Existing built-in YAML carries `min_evidence_objects` (used by
    # `check_mode_satisfied`). Kept on the dataclass so callers that
    # migrate off the legacy dict shape don't lose a field.
    min_evidence_objects: int = 0

    # Free-form bag for forward-compatible per-mode hints we haven't
    # promoted to first-class fields yet (e.g. report shape weights).
    metadata: dict[str, object] = field(default_factory=dict)

    # W7/D5 iterate: per-mode LLM-config overrides keyed by task_kind.
    # Shape: {"writer": {"max_tokens": 16384}, "analyst": {...}, ...}.
    # Empty for built-ins that don't need them. Overlay-able by firm /
    # engagement layers via the same merge semantics as
    # ``trust_tier_rules`` (deep-merge: layer keys take precedence
    # within each task_kind, base keys not overridden stay).
    model_overrides: dict[str, dict[str, object]] = field(default_factory=dict)

    # W8/D4: per-mode framework requirement config. ``None`` (default)
    # means the mode makes no claim — the writer is free to emit
    # frameworks but isn't required to, and the critic does nothing.
    # An empty config (``FrameworksModeConfig()``) is equivalent.
    frameworks: FrameworksModeConfig | None = None


class ModeNotFoundError(LookupError):
    """Raised when `resolve_mode(name)` is asked for a name with neither a
    built-in YAML row nor a firm override."""


class ModeConfigError(ValueError):
    """Raised when a firm or engagement override violates the resolver's
    contract (oversize overlay, malformed config, etc).

    Per the Day 1 spec we DO NOT silently fall back to the built-in on a
    malformed override — surface the error so the firm admin sees it.
    """
