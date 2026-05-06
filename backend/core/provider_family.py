"""Provider-family classification for the cross-family verification wedge.

Phase 1 / Week 1, Day 3. The Argus pipeline contract is that the verifier
runs on a different provider family than the analyst — same-family
verification is observably less critical of the upstream model's output
(an OpenAI judge over an OpenAI analyst tends to ratify rather than
challenge). To make the wedge non-bypassable we crash on boot whenever
``analyst`` and ``verifier`` resolve to the same family.

The mapping intentionally collapses provider variants that share a model
endpoint family:

- ``openai/`` and ``azure/`` -> ``openai``  (Azure proxies the same models)
- ``anthropic/``             -> ``anthropic``
- ``google/``, ``vertex_ai/``, ``gemini/`` -> ``google``  (litellm 1.40.20
  routes the AI Studio API as ``gemini/`` and Vertex as ``vertex_ai/``;
  the project YAML uses ``google/`` and our litellm wrapper rewrites it
  at the call site)
- ``xai/``                   -> ``xai``

Anything else falls back to the lowercased prefix.
"""

from __future__ import annotations

_PREFIX_TO_FAMILY: dict[str, str] = {
    "openai": "openai",
    "azure": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "vertex_ai": "google",
    "gemini": "google",
    "xai": "xai",
}


def family_of(model: str) -> str:
    """Return the provider family for a litellm-style model string.

    Examples:
        family_of("openai/gpt-4o")          -> "openai"
        family_of("azure/gpt-4o")           -> "openai"
        family_of("anthropic/claude-...")   -> "anthropic"
        family_of("google/gemini-2.5-pro")  -> "google"
        family_of("gemini/gemini-2.5-flash") -> "google"
        family_of("vertex_ai/gemini-2.5-pro") -> "google"
        family_of("xai/grok-3")             -> "xai"
        family_of("")                       -> ""
    """
    if not model:
        return ""
    head = model.split("/", 1)[0].lower() if "/" in model else model.lower()
    return _PREFIX_TO_FAMILY.get(head, head)


def assert_cross_family(analyst_model: str, verifier_model: str) -> None:
    """Crash on boot if analyst and verifier come from the same provider family.

    Raises ``RuntimeError`` naming both models so the operator can correct
    ``backend/config/models.yaml`` (or the corresponding ``ARGUS_MODEL_*``
    env override) without grepping for the rule.
    """
    a_family = family_of(analyst_model)
    v_family = family_of(verifier_model)
    if not a_family or not v_family:
        # Empty model strings shouldn't happen in production routing, but the
        # config layer treats absent values as the default; surface the bad
        # input rather than silently passing.
        raise RuntimeError(
            "cross-family verification check received an empty model string: "
            f"analyst={analyst_model!r} ({a_family!r}), "
            f"verifier={verifier_model!r} ({v_family!r})"
        )
    if a_family == v_family:
        raise RuntimeError(
            "Argus cross-family verification rule violated: "
            f"analyst={analyst_model!r} and verifier={verifier_model!r} "
            f"are both in the {a_family!r} family. "
            "Update backend/config/models.yaml so the analyst and verifier "
            "primaries resolve to different provider families "
            "(or override via ARGUS_MODEL_ANALYST / ARGUS_MODEL_VERIFIER)."
        )
