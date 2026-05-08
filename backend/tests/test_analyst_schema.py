"""AnalystStructuredOutput schema coercion (Week 4 / Day 2).

The analyst LLM intermittently emits ``assumptions`` as a list of dicts
(``[{"assumption": "..."}]``) instead of plain strings. Day 2 spec
addressed this with a Pydantic ``before`` validator that coerces known
shapes back to strings. These tests pin the contract so a future schema
edit doesn't silently re-introduce the retries.
"""

from __future__ import annotations

import pytest

from models.agent_structured import AnalystStructuredOutput


def test_assumptions_plain_strings_pass_through() -> None:
    out = AnalystStructuredOutput.model_validate(
        {"assumptions": ["assumption 1", "assumption 2"]}
    )
    assert out.assumptions == ["assumption 1", "assumption 2"]


def test_assumptions_dict_with_assumption_key_coerced() -> None:
    out = AnalystStructuredOutput.model_validate(
        {
            "assumptions": [
                {"assumption": "Greater China stays above 10% growth"},
                {"assumption": "Services attach rate continues at FY24 trend"},
            ]
        }
    )
    assert out.assumptions == [
        "Greater China stays above 10% growth",
        "Services attach rate continues at FY24 trend",
    ]


def test_assumptions_dict_with_rationale_concatenated() -> None:
    """When the dict has both 'assumption' and an extra field (e.g.
    'rationale'), concatenate so neither half is lost.
    """
    out = AnalystStructuredOutput.model_validate(
        {
            "assumptions": [
                {
                    "assumption": "iPhone segment grows mid-single digits",
                    "rationale": "Apple Intelligence expansion in EMEA",
                }
            ]
        }
    )
    assert len(out.assumptions) == 1
    s = out.assumptions[0]
    assert isinstance(s, str)
    assert "iPhone segment grows mid-single digits" in s
    assert "rationale" in s.lower() and "Apple Intelligence" in s


def test_assumptions_mixed_shapes_all_normalised() -> None:
    out = AnalystStructuredOutput.model_validate(
        {
            "assumptions": [
                "plain string",
                {"assumption": "from dict"},
                "",  # empty string dropped
                {"assumption": "  trailing whitespace  "},
            ]
        }
    )
    assert out.assumptions == [
        "plain string",
        "from dict",
        "trailing whitespace",
    ]


def test_assumptions_dict_without_assumption_key_serialised_not_lost() -> None:
    """Edge case: dict has no 'assumption' key. Spec says "fall back to
    json.dumps so the data isn't lost" — verify we keep the payload."""
    out = AnalystStructuredOutput.model_validate(
        {"assumptions": [{"text": "weird shape", "weight": 0.7}]}
    )
    assert len(out.assumptions) == 1
    assert "weird shape" in out.assumptions[0]


def test_assumptions_none_or_non_list_does_not_crash() -> None:
    AnalystStructuredOutput.model_validate({"assumptions": None})
    AnalystStructuredOutput.model_validate({"assumptions": "single string"})
