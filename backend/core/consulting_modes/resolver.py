"""Phase 2 / Week 6 / Day 1 — layered consulting-mode resolver.

Resolution order at runtime: built-in <- firm_modes <- engagement_mode_overrides.
Each layer can supply an arbitrary subset of fields; the merge rules are
codified in `_merge` and exhaustively tested in
`backend/tests/test_consulting_modes_resolver.py`.

Caching: `(name, firm_id, engagement_id)` → resolved mode, TTL 60s.
Day 2 will add explicit invalidation on mode-write events; for today the
TTL is the only refresh signal.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

from .types import (
    LayerName,
    ModeConfigError,
    ModeNotFoundError,
    ResolvedConsultingMode,
)

# 2000-char per-layer overlay cap — combined writer overhead therefore caps
# at ~6000 chars (built-in + firm + engagement). Big enough to carry a
# meaningful style sheet, small enough not to bloat every LLM call.
OVERLAY_MAX_CHARS = 2000

# (name, firm_id_or_none, engagement_id_or_none) -> (expires_at, resolved)
_CACHE: dict[tuple[str, str | None, str | None], tuple[float, ResolvedConsultingMode]] = {}
CACHE_TTL_SECONDS = 60

# Fields whose "replace if present" semantics are list-shape.
_LIST_REPLACE_FIELDS = ("required_branches", "reasoning_slots", "source_priorities_default")
# Scalar replace-if-present fields.
_SCALAR_REPLACE_FIELDS = ("display_name", "description")
# Overlay fields — append, with cap enforced per layer.
_OVERLAY_FIELDS = ("writer_overlay", "planner_overlay")


# ---------------------------------------------------------------------------
# YAML loading (built-in modes)
# ---------------------------------------------------------------------------


def _yaml_path() -> Path:
    base = (
        Path(__file__).resolve().parent.parent.parent / "config" / "consulting_modes.yaml"
    )
    override = os.getenv("ARGUS_CONSULTING_MODES_PATH")
    return Path(override) if override else base


_YAML_CACHE: dict[str, Any] | None = None


def _load_yaml() -> dict[str, Any]:
    global _YAML_CACHE
    if _YAML_CACHE is not None:
        return _YAML_CACHE
    path = _yaml_path()
    if not path.is_file():
        _YAML_CACHE = {}
        return _YAML_CACHE
    with path.open(encoding="utf-8") as f:
        _YAML_CACHE = yaml.safe_load(f) or {}
    return _YAML_CACHE


def _yaml_reset() -> None:
    """Test hook — drop both YAML and resolution caches."""
    global _YAML_CACHE
    _YAML_CACHE = None
    _CACHE.clear()


def _built_in_to_resolved(name: str, row: dict[str, Any]) -> ResolvedConsultingMode:
    """Project a YAML mode row into a fully-populated ResolvedConsultingMode
    with provenance set to "built_in" for every field.

    YAML ``metadata:`` blocks are flattened into the dataclass's
    ``metadata`` dict directly. Any other unknown top-level YAML key
    falls into ``metadata`` too (forward-compat).
    """
    known_fields = (
        "label",
        "display_name",
        "description",
        "required_branches",
        "reasoning_slots",
        "source_priorities_default",
        "trust_tier_rules",
        "writer_overlay",
        "planner_overlay",
        "min_evidence_objects",
        "metadata",
        "model_overrides",
    )
    metadata: dict[str, Any] = {}
    raw_md = row.get("metadata")
    if isinstance(raw_md, dict):
        metadata.update(raw_md)
    # Forward-compat: any unknown top-level key gets folded in too.
    for k, v in row.items():
        if k not in known_fields:
            metadata[k] = v

    # model_overrides: dict of task_kind -> {param: value}
    raw_mo = row.get("model_overrides") or {}
    model_overrides: dict[str, dict[str, Any]] = {}
    if isinstance(raw_mo, dict):
        for tk, params in raw_mo.items():
            if isinstance(params, dict):
                model_overrides[str(tk)] = dict(params)

    return ResolvedConsultingMode(
        name=name,
        display_name=str(row.get("label") or row.get("display_name") or name),
        description=str(row.get("description") or ""),
        required_branches=list(row.get("required_branches") or []),
        reasoning_slots=list(row.get("reasoning_slots") or []),
        source_priorities_default=list(row.get("source_priorities_default") or []),
        trust_tier_rules=dict(row.get("trust_tier_rules") or {}),
        writer_overlay=str(row.get("writer_overlay") or ""),
        planner_overlay=str(row.get("planner_overlay") or ""),
        min_evidence_objects=int(row.get("min_evidence_objects") or 0),
        metadata=metadata,
        model_overrides=model_overrides,
        layer_provenance={
            "display_name": "built_in",
            "description": "built_in",
            "required_branches": "built_in",
            "reasoning_slots": "built_in",
            "source_priorities_default": "built_in",
            "trust_tier_rules": "built_in",
            "writer_overlay": "built_in",
            "planner_overlay": "built_in",
            "model_overrides": "built_in",
        },
    )


def _load_built_in(name: str) -> ResolvedConsultingMode | None:
    modes = _load_yaml()
    row = modes.get(name)
    if not isinstance(row, dict):
        return None
    return _built_in_to_resolved(name, row)


# ---------------------------------------------------------------------------
# Override loaders (DB-backed) — async because they may pool-acquire
# ---------------------------------------------------------------------------


async def _load_firm_override(name: str, firm_id: str | UUID) -> dict[str, Any] | None:
    """Return the active firm_modes.config for (firm_id, name), or None."""
    from db.connection import acquire  # noqa: WPS433 — avoid import-time cycle

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT config
            FROM firm_modes
            WHERE firm_id = $1::uuid
              AND name = $2
              AND retired_at IS NULL
            """,
            str(firm_id),
            name,
        )
    if not row:
        return None
    cfg = row["config"]
    if isinstance(cfg, str):
        import json as _json

        try:
            cfg = _json.loads(cfg)
        except Exception as e:
            raise ModeConfigError(
                f"firm_modes.config for {firm_id}:{name} is not valid JSON: {e}"
            ) from e
    if not isinstance(cfg, dict):
        raise ModeConfigError(
            f"firm_modes.config for {firm_id}:{name} must be an object, "
            f"got {type(cfg).__name__}"
        )
    return cfg


async def _load_engagement_override(
    engagement_id: str | UUID, name: str
) -> dict[str, Any] | None:
    """Return engagement_mode_overrides.config when (session_id, mode_name)
    matches, else None. Mismatched mode_name means the engagement override
    is for a DIFFERENT mode and shouldn't apply to this resolution.
    """
    from db.connection import acquire  # noqa: WPS433

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT mode_name, config
            FROM engagement_mode_overrides
            WHERE session_id = $1::uuid
            """,
            str(engagement_id),
        )
    if not row:
        return None
    if row["mode_name"] != name:
        return None
    cfg = row["config"]
    if isinstance(cfg, str):
        import json as _json

        try:
            cfg = _json.loads(cfg)
        except Exception as e:
            raise ModeConfigError(
                f"engagement_mode_overrides.config for {engagement_id} is not valid JSON: {e}"
            ) from e
    if not isinstance(cfg, dict):
        raise ModeConfigError(
            f"engagement_mode_overrides.config for {engagement_id} must be an object, "
            f"got {type(cfg).__name__}"
        )
    return cfg


# ---------------------------------------------------------------------------
# Merge engine
# ---------------------------------------------------------------------------


def _check_overlay_size(
    layer_name: LayerName, field_name: str, value: str
) -> None:
    if len(value) > OVERLAY_MAX_CHARS:
        raise ModeConfigError(
            f"{layer_name}.{field_name} is {len(value)} chars, "
            f"exceeds {OVERLAY_MAX_CHARS}-char per-layer cap"
        )


def _apply_layer(
    base: ResolvedConsultingMode,
    layer_cfg: dict[str, Any],
    layer_name: LayerName,
) -> ResolvedConsultingMode:
    """Apply one override layer onto `base` and return the merged result.

    Replace fields: replace if the layer key is present (even if value is
    the empty string / empty list — explicit override is meaningful).
    trust_tier_rules: deep-merge (layer keys take precedence).
    Overlays: append with two-newline separator.
    """
    new_provenance: dict[str, LayerName] = dict(base.layer_provenance)

    new_display_name = base.display_name
    new_description = base.description
    new_required_branches = list(base.required_branches)
    new_reasoning_slots = list(base.reasoning_slots)
    new_source_priorities = list(base.source_priorities_default)
    new_trust_rules = dict(base.trust_tier_rules)
    new_writer_overlay = base.writer_overlay
    new_planner_overlay = base.planner_overlay
    new_min_evidence = base.min_evidence_objects
    new_metadata = dict(base.metadata)
    new_model_overrides = {
        tk: dict(params) for tk, params in (base.model_overrides or {}).items()
    }

    for key in _SCALAR_REPLACE_FIELDS:
        if key in layer_cfg:
            v = layer_cfg[key]
            if not isinstance(v, str):
                raise ModeConfigError(
                    f"{layer_name}.{key} must be a string, got {type(v).__name__}"
                )
            if key == "display_name":
                new_display_name = v
            else:
                new_description = v
            new_provenance[key] = layer_name

    for key in _LIST_REPLACE_FIELDS:
        if key in layer_cfg:
            v = layer_cfg[key]
            if not isinstance(v, list):
                raise ModeConfigError(
                    f"{layer_name}.{key} must be a list, got {type(v).__name__}"
                )
            v = [str(x) for x in v]
            if key == "required_branches":
                new_required_branches = v
            elif key == "reasoning_slots":
                new_reasoning_slots = v
            else:
                new_source_priorities = v
            new_provenance[key] = layer_name

    if "trust_tier_rules" in layer_cfg:
        layer_rules = layer_cfg["trust_tier_rules"]
        if not isinstance(layer_rules, dict):
            raise ModeConfigError(
                f"{layer_name}.trust_tier_rules must be an object, "
                f"got {type(layer_rules).__name__}"
            )
        new_trust_rules.update({str(k): str(v) for k, v in layer_rules.items()})
        new_provenance["trust_tier_rules"] = layer_name

    for key in _OVERLAY_FIELDS:
        if key in layer_cfg:
            v = layer_cfg[key]
            if not isinstance(v, str):
                raise ModeConfigError(
                    f"{layer_name}.{key} must be a string, got {type(v).__name__}"
                )
            _check_overlay_size(layer_name, key, v)
            existing = (
                new_writer_overlay if key == "writer_overlay" else new_planner_overlay
            )
            merged = (existing + "\n\n" + v) if existing else v
            if key == "writer_overlay":
                new_writer_overlay = merged
            else:
                new_planner_overlay = merged
            new_provenance[key] = layer_name

    if "min_evidence_objects" in layer_cfg:
        v = layer_cfg["min_evidence_objects"]
        try:
            new_min_evidence = int(v)
        except (TypeError, ValueError) as e:
            raise ModeConfigError(
                f"{layer_name}.min_evidence_objects must be an int, got {v!r}"
            ) from e

    if "metadata" in layer_cfg:
        layer_md = layer_cfg["metadata"]
        if not isinstance(layer_md, dict):
            raise ModeConfigError(
                f"{layer_name}.metadata must be an object, got {type(layer_md).__name__}"
            )
        new_metadata.update(layer_md)

    # model_overrides: deep-merge by task_kind. Layer keys take
    # precedence within each task_kind; base keys not overridden stay.
    if "model_overrides" in layer_cfg:
        layer_mo = layer_cfg["model_overrides"]
        if not isinstance(layer_mo, dict):
            raise ModeConfigError(
                f"{layer_name}.model_overrides must be an object, got {type(layer_mo).__name__}"
            )
        for tk, params in layer_mo.items():
            if not isinstance(params, dict):
                raise ModeConfigError(
                    f"{layer_name}.model_overrides[{tk!r}] must be an object, "
                    f"got {type(params).__name__}"
                )
            base_params = new_model_overrides.get(str(tk), {})
            base_params.update(params)
            new_model_overrides[str(tk)] = base_params
        new_provenance["model_overrides"] = layer_name

    return ResolvedConsultingMode(
        name=base.name,
        display_name=new_display_name,
        description=new_description,
        required_branches=new_required_branches,
        reasoning_slots=new_reasoning_slots,
        source_priorities_default=new_source_priorities,
        trust_tier_rules=new_trust_rules,
        writer_overlay=new_writer_overlay,
        planner_overlay=new_planner_overlay,
        layer_provenance=new_provenance,
        min_evidence_objects=new_min_evidence,
        metadata=new_metadata,
        model_overrides=new_model_overrides,
    )


def _merge(
    base: ResolvedConsultingMode,
    firm_override: dict[str, Any] | None,
    engagement_override: dict[str, Any] | None,
) -> ResolvedConsultingMode:
    out = base
    if firm_override:
        out = _apply_layer(out, firm_override, "firm")
    if engagement_override:
        out = _apply_layer(out, engagement_override, "engagement")
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_mode(
    name: str,
    firm_id: str | UUID | None,
    engagement_id: str | UUID | None = None,
) -> ResolvedConsultingMode:
    """Resolve `name` against built-in YAML, firm-scoped overrides, and an
    optional engagement-level override. Cached at the (name, firm,
    engagement) tuple for `CACHE_TTL_SECONDS`.

    Raises ModeNotFoundError if no built-in row exists for `name` and no
    firm override defines it. Raises ModeConfigError on malformed
    overrides — the caller is expected to surface the error, not paper
    over it.
    """
    cache_key = (
        name,
        str(firm_id) if firm_id is not None else None,
        str(engagement_id) if engagement_id is not None else None,
    )
    cached = _CACHE.get(cache_key)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]

    base = _load_built_in(name)
    firm_cfg: dict[str, Any] | None = None
    eng_cfg: dict[str, Any] | None = None

    if firm_id is not None:
        firm_cfg = await _load_firm_override(name, firm_id)
    if engagement_id is not None:
        eng_cfg = await _load_engagement_override(engagement_id, name)

    # If there's no built-in, the firm override must define enough to
    # constitute a mode (at minimum: display_name). Otherwise fail loudly.
    if base is None:
        if firm_cfg is None:
            raise ModeNotFoundError(
                f"consulting mode {name!r} has no built-in row and no firm override"
            )
        synthetic_base = ResolvedConsultingMode(
            name=name,
            display_name=name,
            description="",
            required_branches=[],
            reasoning_slots=[],
            source_priorities_default=[],
            trust_tier_rules={},
            writer_overlay="",
            planner_overlay="",
            min_evidence_objects=0,
            metadata={},
            model_overrides={},
            layer_provenance={
                "display_name": "firm",
                "description": "firm",
                "required_branches": "firm",
                "reasoning_slots": "firm",
                "source_priorities_default": "firm",
                "trust_tier_rules": "firm",
                "writer_overlay": "firm",
                "planner_overlay": "firm",
                "model_overrides": "firm",
            },
        )
        merged = _apply_layer(synthetic_base, firm_cfg, "firm")
        if eng_cfg:
            merged = _apply_layer(merged, eng_cfg, "engagement")
    else:
        merged = _merge(base, firm_cfg, eng_cfg)

    _CACHE[cache_key] = (now + CACHE_TTL_SECONDS, merged)
    return merged


def load_mode_legacy(name: str) -> ResolvedConsultingMode:
    """Synchronous shim returning the built-in-only resolution.

    Used by code paths that haven't migrated to the (firm, engagement)
    aware `resolve_mode` yet. Functionally equal to `resolve_mode(name,
    firm_id=None, engagement_id=None)` — same merge result, no DB round
    trip — but synchronous so legacy callers don't have to thread async.
    """
    base = _load_built_in(name)
    if base is None:
        raise ModeNotFoundError(
            f"consulting mode {name!r} not present in built-in YAML"
        )
    return base


def _cache_clear() -> None:
    """Test hook — clear the resolution cache."""
    _CACHE.clear()


def invalidate_firm_mode(name: str, firm_id: str | UUID) -> int:
    """Drop every cache entry for (name, firm_id, *engagement_id*).

    Called from the service layer on create / update / retire / restore
    so the next resolve_mode() call re-reads the DB. Returns the number
    of entries dropped (handy for tests).
    """
    fid = str(firm_id)
    keys_to_drop = [k for k in _CACHE if k[0] == name and k[1] == fid]
    for k in keys_to_drop:
        del _CACHE[k]
    return len(keys_to_drop)


def invalidate_engagement(engagement_id: str | UUID) -> int:
    """Drop every cache entry that references this engagement.

    Called when the engagement-level override config is written/cleared.
    """
    eid = str(engagement_id)
    keys_to_drop = [k for k in _CACHE if k[2] == eid]
    for k in keys_to_drop:
        del _CACHE[k]
    return len(keys_to_drop)


def check_resolved_mode_satisfied(
    resolved: ResolvedConsultingMode,
    *,
    branch_ids_present: set[str],
    evidence_count: int,
) -> tuple[bool, list[str]]:
    """Same gap check as the legacy ``check_mode_satisfied(name, ...)`` but
    against an already-resolved mode. The orchestrator uses this so the
    firm's overridden ``required_branches`` and ``min_evidence_objects``
    drive the gate, not the flat YAML.
    """
    gaps: list[str] = []
    for b in resolved.required_branches:
        if b not in branch_ids_present:
            gaps.append(f"Missing research branch coverage: {b}")
    if evidence_count < resolved.min_evidence_objects:
        gaps.append(
            f"Mode '{resolved.name}' requires at least "
            f"{resolved.min_evidence_objects} evidence objects; "
            f"found {evidence_count}."
        )
    return len(gaps) == 0, gaps


# ---------------------------------------------------------------------------
# Trust-tier filtering — layered on top of retrieval results
# ---------------------------------------------------------------------------


_TRUST_RANK = {
    "contested": 0,
    "web_general": 1,
    "credible_external": 2,
    "firm_vetted": 3,
}


def chunk_passes_trust_rules(
    chunk: dict[str, Any], rules: dict[str, str]
) -> bool:
    """True if a chunk's ``trust_level`` meets the per-source-type minimum
    declared by ``rules`` (the resolved mode's ``trust_tier_rules``).

    Rules without an entry for the chunk's source_type are not enforced —
    the global policy applies. A chunk with no trust_level is treated as
    web_general.
    """
    if not rules:
        return True
    src = (chunk.get("source_type") or "").lower()
    required = rules.get(src)
    if not required:
        return True
    have = (chunk.get("trust_level") or "web_general").lower()
    return _TRUST_RANK.get(have, 1) >= _TRUST_RANK.get(required, 0)


def apply_trust_rules(
    chunks: list[dict[str, Any]], rules: dict[str, str]
) -> list[dict[str, Any]]:
    """Drop chunks that fail :func:`chunk_passes_trust_rules`. Identity
    pass when ``rules`` is empty (the common case)."""
    if not rules:
        return chunks
    return [c for c in chunks if chunk_passes_trust_rules(c, rules)]


# ---------------------------------------------------------------------------
# Config-payload validation (used by the service layer on create/update)
# ---------------------------------------------------------------------------


# Canonical trust-tier values from backend/api/sources.py / source_queries.py.
# Centralised here so future trust-tier additions only need updating in one
# place if the validator references it.
ALLOWED_TRUST_TIERS = ("firm_vetted", "credible_external", "web_general", "contested")
ALLOWED_SOURCE_TYPES = (
    "uploaded",
    "sec_filing",
    "transcript",
    "news",
    "ch_filing",
    "web",
    "firm_library",  # surfaced in citations as a first-class type since W5/D4
)

ALLOWED_CONFIG_KEYS = frozenset(
    {
        "display_name",
        "description",
        "required_branches",
        "reasoning_slots",
        "source_priorities_default",
        "trust_tier_rules",
        "writer_overlay",
        "planner_overlay",
        "min_evidence_objects",
        "metadata",
        "model_overrides",
    }
)

LIST_FIELD_MAX_ITEMS = 20


def _validate_overlay_payload(config: dict[str, Any]) -> None:
    """Validate a firm_modes / engagement override config dict.

    Raises :class:`ModeConfigError` with a clear, field-level message on
    any violation:

      * unknown top-level keys
      * required_branches / reasoning_slots / source_priorities_default
        not lists, or > 20 items, or non-string items
      * source_priorities_default contains a literal not in the allowed set
      * trust_tier_rules: keys not in source-type set, values not in
        trust-tier set
      * overlay strings > 2000 chars (also enforced again at merge time —
        belt-and-braces)
      * min_evidence_objects not coercible to int

    The validator is strict on purpose. Per Day 1 hard rule we don't
    silently fall back on a bad firm override.
    """
    if not isinstance(config, dict):
        raise ModeConfigError(
            f"config must be an object, got {type(config).__name__}"
        )

    extra = set(config.keys()) - ALLOWED_CONFIG_KEYS
    if extra:
        raise ModeConfigError(
            "config contains unknown keys: "
            + ", ".join(sorted(extra))
            + f" (allowed: {', '.join(sorted(ALLOWED_CONFIG_KEYS))})"
        )

    for key in ("display_name", "description"):
        if key in config and not isinstance(config[key], str):
            raise ModeConfigError(
                f"{key} must be a string, got {type(config[key]).__name__}"
            )

    for key in ("required_branches", "reasoning_slots", "source_priorities_default"):
        if key not in config:
            continue
        v = config[key]
        if not isinstance(v, list):
            raise ModeConfigError(
                f"{key} must be a list, got {type(v).__name__}"
            )
        if len(v) > LIST_FIELD_MAX_ITEMS:
            raise ModeConfigError(
                f"{key} has {len(v)} items, max {LIST_FIELD_MAX_ITEMS}"
            )
        for item in v:
            if not isinstance(item, str):
                raise ModeConfigError(
                    f"{key} items must be strings, got {type(item).__name__}"
                )
        if key == "source_priorities_default":
            bad = [x for x in v if x not in ALLOWED_SOURCE_TYPES]
            if bad:
                raise ModeConfigError(
                    f"source_priorities_default contains unknown source types: "
                    f"{', '.join(bad)} (allowed: {', '.join(ALLOWED_SOURCE_TYPES)})"
                )

    if "trust_tier_rules" in config:
        rules = config["trust_tier_rules"]
        if not isinstance(rules, dict):
            raise ModeConfigError(
                f"trust_tier_rules must be an object, got {type(rules).__name__}"
            )
        for k, v in rules.items():
            if k not in ALLOWED_SOURCE_TYPES:
                raise ModeConfigError(
                    f"trust_tier_rules key {k!r} is not a known source type "
                    f"(allowed: {', '.join(ALLOWED_SOURCE_TYPES)})"
                )
            if not isinstance(v, str) or v not in ALLOWED_TRUST_TIERS:
                raise ModeConfigError(
                    f"trust_tier_rules[{k!r}] = {v!r} is not a valid trust tier "
                    f"(allowed: {', '.join(ALLOWED_TRUST_TIERS)})"
                )

    for key in ("writer_overlay", "planner_overlay"):
        if key in config:
            v = config[key]
            if not isinstance(v, str):
                raise ModeConfigError(
                    f"{key} must be a string, got {type(v).__name__}"
                )
            if len(v) > OVERLAY_MAX_CHARS:
                raise ModeConfigError(
                    f"{key} is {len(v)} chars, exceeds {OVERLAY_MAX_CHARS}-char per-layer cap"
                )

    if "min_evidence_objects" in config:
        try:
            int(config["min_evidence_objects"])
        except (TypeError, ValueError) as e:
            raise ModeConfigError(
                f"min_evidence_objects must be an int, "
                f"got {config['min_evidence_objects']!r}"
            ) from e

    if "metadata" in config and not isinstance(config["metadata"], dict):
        raise ModeConfigError(
            f"metadata must be an object, got {type(config['metadata']).__name__}"
        )

    # model_overrides: dict[task_kind, dict[param_name, value]]. Today
    # we only inspect ``max_tokens`` deeply; other params pass through
    # so per-task tuning (temperature, top_p, etc.) is configurable
    # without schema churn.
    if "model_overrides" in config:
        mo = config["model_overrides"]
        if not isinstance(mo, dict):
            raise ModeConfigError(
                f"model_overrides must be an object, got {type(mo).__name__}"
            )
        for tk, params in mo.items():
            if not isinstance(params, dict):
                raise ModeConfigError(
                    f"model_overrides[{tk!r}] must be an object, "
                    f"got {type(params).__name__}"
                )
            mt = params.get("max_tokens")
            if mt is not None:
                try:
                    iv = int(mt)
                except (TypeError, ValueError) as e:
                    raise ModeConfigError(
                        f"model_overrides[{tk!r}].max_tokens must be an int, "
                        f"got {mt!r}"
                    ) from e
                # Sanity bounds — protect against runaway prompts.
                if iv < 256 or iv > 64000:
                    raise ModeConfigError(
                        f"model_overrides[{tk!r}].max_tokens={iv} out of range "
                        "[256, 64000]"
                    )


def is_known_built_in(name: str) -> bool:
    """Whether ``name`` matches a key in the built-in YAML."""
    return isinstance(_load_yaml().get(name), dict)


def list_built_in_names() -> list[str]:
    return sorted(k for k, v in _load_yaml().items() if isinstance(v, dict))
