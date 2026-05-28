"""First-engagement template briefs — Phase 5 / Week 24 / Day 2.

A small library of real-shaped example briefs the pilot firm can
read as references when writing their own. Each brief demonstrates
good prompting: a clear decision to support, an evidence-rich scope,
and appropriate research targets — NOT a synthetic Meridian-style
fixture. Even anonymised, they should read like something a partner
would actually write.

Briefs live as markdown files under ``pilot_briefs/<mode>/<id>.md``
with a light frontmatter block::

    ---
    title: Project Atlas — acquire TargetCo (UK specialty retail)
    mode: m_and_a_diligence
    why_good: names the decision, the deal economics, and the
        evidence the partner already has on hand
    research_targets: comparable transactions, segment margins,
        integration risk
    ---

    <the brief body — what the partner would type into Argus>

The loader parses the frontmatter without a YAML dependency (pyyaml
is intentionally not a hard dep) so the briefs load in any
environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BRIEFS_DIR = Path(__file__).resolve().parent

# The modes we ship reference briefs for. Must be a subset of the
# built-in consulting modes (backend/config/consulting_modes.yaml).
SUPPORTED_BRIEF_MODES = (
    "m_and_a_diligence",
    "growth_strategy",
    "general",
)


@dataclass
class PilotBrief:
    """One reference brief, parsed from a markdown file."""

    id: str
    mode: str
    title: str
    why_good: str
    research_targets: list[str] = field(default_factory=list)
    body: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.mode,
            "title": self.title,
            "why_good": self.why_good,
            "research_targets": self.research_targets,
            "body": self.body,
        }


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split ``---\\n<frontmatter>\\n---\\n<body>``. Frontmatter is
    simple ``key: value`` lines (values may wrap onto indented
    continuation lines). No YAML dependency."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    fm: dict[str, str] = {}
    body_start = len(lines)
    last_key: str | None = None
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            body_start = i + 1
            break
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, val = line.partition(":")
            last_key = key.strip()
            fm[last_key] = val.strip()
        elif last_key and line.strip():
            # Continuation of the previous value.
            fm[last_key] = (fm[last_key] + " " + line.strip()).strip()
    body = "\n".join(lines[body_start:]).strip()
    return fm, body


def _coerce_brief(mode: str, path: Path) -> PilotBrief:
    fm, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    targets = [
        t.strip() for t in (fm.get("research_targets", "")).split(",")
        if t.strip()
    ]
    return PilotBrief(
        id=path.stem,
        mode=fm.get("mode", mode),
        title=fm.get("title", path.stem.replace("_", " ").title()),
        why_good=fm.get("why_good", ""),
        research_targets=targets,
        body=body,
    )


def load_pilot_briefs(
    mode: str | None = None,
) -> dict[str, list[PilotBrief]]:
    """Load every reference brief, grouped by mode. Pass ``mode`` to
    restrict to one mode. Modes with no brief files are omitted."""
    out: dict[str, list[PilotBrief]] = {}
    modes = [mode] if mode else list(SUPPORTED_BRIEF_MODES)
    for m in modes:
        mode_dir = _BRIEFS_DIR / m
        if not mode_dir.is_dir():
            continue
        briefs = [
            _coerce_brief(m, p)
            for p in sorted(mode_dir.glob("*.md"))
        ]
        if briefs:
            out[m] = briefs
    return out


__all__ = [
    "PilotBrief",
    "SUPPORTED_BRIEF_MODES",
    "load_pilot_briefs",
]
