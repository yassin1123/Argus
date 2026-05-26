"""Aggregator threshold configuration — Phase 5 / Week 21 / Day 3.

Pulls the previously-baked-in tuning constants out of
:mod:`core.nli.aggregator` into a dataclass that can be loaded
from YAML, swept by the Day 3 tuning harness, and persisted as
the production calibration.

Backward-compat: when :func:`core.nli.aggregator.aggregate` is
called without a config, :func:`default_threshold_config` is used.
Its defaults match the pre-W21/D3 constants exactly so the
existing pipeline behaviour is unchanged.

Three knobs today:

  - ``deberta_high_conf``           — at/above this DeBERTa
    entailment confidence is "high confidence" enough to ratify
    an LLM-supported verdict to ``supported_high``. Was 0.7.
  - ``numeric_drift_below``         — below this numeric overlap
    score, the lexical layer signals drift even when the LLM and
    DeBERTa agree. Was 0.95.
  - ``borderline_band``             — NEW W21/D3 knob enforcing
    the **conservative-default principle**. If the DeBERTa
    entailment confidence is within ``[high - band, high)`` AND
    numeric overlap is borderline (between ``drift_below`` and
    ``drift_below + band``), the aggregator downgrades a would-be
    ``supported_low`` to ``weak``. Resolves uncertainty toward
    review, not toward trust. Default 0.0 (no downgrade), so an
    untuned system behaves like W2/D3.

The config also carries an ``id`` + ``rationale`` field so the
production YAML can record which tuning run produced the active
thresholds and why (e.g. "FP-rate-on-supported dropped from 60%
to 0% on the W21/D2 cached scores").
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Default config path — the YAML file is the production source of truth.
# When absent (e.g. fresh checkout), :func:`default_threshold_config` is
# used.  The Day 3 tuning harness writes its best config back to this path.
# ---------------------------------------------------------------------------


_CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "config" / "verification_thresholds.yaml"
)


@dataclass
class ThresholdConfig:
    """Aggregator tuning constants. Pure data — no behaviour."""

    # Active thresholds.
    deberta_high_conf: float = 0.7
    numeric_drift_below: float = 0.95
    borderline_band: float = 0.0
    # Provenance — fills in when loaded from YAML / written by the
    # Day 3 tuner.
    id: str = "default_w2d3"
    rationale: str = (
        "Pre-W21/D3 defaults. The aggregator constants as locked in "
        "Phase 1 / Week 2 / Day 3 before any calibration data existed."
    )
    source: str = "code_default"

    def __post_init__(self) -> None:
        # Hard bounds — the harness can't tune these out of plausible
        # ranges. Anything that violates these is a config error.
        if not (0.0 <= self.deberta_high_conf <= 1.0):
            raise ValueError(
                f"deberta_high_conf={self.deberta_high_conf!r} outside [0,1]"
            )
        if not (0.0 <= self.numeric_drift_below <= 1.0):
            raise ValueError(
                f"numeric_drift_below={self.numeric_drift_below!r} outside [0,1]"
            )
        if not (0.0 <= self.borderline_band <= 0.5):
            raise ValueError(
                f"borderline_band={self.borderline_band!r} outside [0, 0.5]"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_threshold_config() -> ThresholdConfig:
    """The W2/D3 baked-in defaults. Used when no YAML override is
    present + as the fall-back for tests that don't supply one."""
    return ThresholdConfig()


def load_threshold_config(
    path: str | os.PathLike[str] | None = None,
) -> ThresholdConfig:
    """Load the YAML override if present; otherwise the
    code-default. We import yaml lazily so a missing pyyaml
    dependency doesn't break the aggregator import path."""
    p = Path(path) if path else _CONFIG_PATH
    if not p.exists():
        return default_threshold_config()
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    except ImportError:
        # Fall back to JSON parse — operators sometimes drop a json file
        # in the same location for portable envs.
        import json
        data = json.loads(text)
    if not isinstance(data, dict):
        return default_threshold_config()
    return ThresholdConfig(
        deberta_high_conf=float(
            data.get("deberta_high_conf", 0.7),
        ),
        numeric_drift_below=float(
            data.get("numeric_drift_below", 0.95),
        ),
        borderline_band=float(data.get("borderline_band", 0.0)),
        id=str(data.get("id", "yaml_loaded")),
        rationale=str(data.get("rationale", "")),
        source=str(data.get("source", "yaml")),
    )


def save_threshold_config(
    config: ThresholdConfig,
    path: str | os.PathLike[str] | None = None,
) -> Path:
    """Persist the chosen thresholds back to YAML so the next
    process load picks them up. Returns the path written.

    Hard-rule: the config file is committed to git — there is no
    in-memory-only state. The Day 3 tuner runs explicitly and
    writes here; nothing else does."""
    p = Path(path) if path else _CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = config.to_dict()
    try:
        import yaml  # type: ignore

        p.write_text(yaml.safe_dump(payload, sort_keys=False))
    except ImportError:
        import json
        if p.suffix.lower() in (".yaml", ".yml"):
            p = p.with_suffix(".json")
        p.write_text(json.dumps(payload, indent=2))
    return p


__all__ = [
    "ThresholdConfig",
    "default_threshold_config",
    "load_threshold_config",
    "save_threshold_config",
]
