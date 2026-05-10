"""Phase 2 / Week 7 / Iterate — litellm_client extra-headers wiring.

Original Step 2 plan was to send the Anthropic extended-output beta
header (``extended-output-128k-2025-02-19``) on every Anthropic call
so Sonnet 4.5 would accept ``max_tokens > 8192``. In practice that
beta name was rejected with HTTP 400 on every Anthropic call,
including the analyst (which doesn't need extended output at all).
Per the spec's pivot rule the path swapped to **swap the writer
model to OpenAI** via ``model_overrides``, and the
``_extra_headers_for`` helper now returns empty.

These tests pin the helper's current behaviour AND the plumbing
contract (extra_headers, when set, must reach the underlying
acompletion call) so a future header (cache-control, prompt
caching, a re-introduced beta) can land without re-discovering the
wiring.
"""

from __future__ import annotations

from unittest import mock

import pytest

from core.inference.litellm_client import _extra_headers_for, chat_complete


def _stub_response():
    """Minimal acompletion return shape — tests only inspect call kwargs."""
    rsp = mock.MagicMock()
    rsp.choices = [mock.MagicMock(message=mock.MagicMock(content="{}"))]
    return rsp


# ---------------------------------------------------------------------------
# Helper behaviour pin
# ---------------------------------------------------------------------------


def test_extra_headers_for_returns_empty_today() -> None:
    """Anthropic extended-output beta is not currently sent (broken
    on Sonnet 4.5 with the published beta name). Pinned here so an
    accidental re-introduction shows up in CI."""
    assert _extra_headers_for("anthropic/claude-sonnet-4-5") == {}
    assert _extra_headers_for("openai/gpt-4o") == {}
    assert _extra_headers_for("google/gemini-2.5-pro") == {}


# ---------------------------------------------------------------------------
# Plumbing contract — extra_headers, when set, reaches acompletion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_call_does_not_currently_set_extra_headers() -> None:
    """With the empty helper, no ``extra_headers`` kwarg is sent on
    Anthropic calls. Pinning behaviour so the broken beta header
    doesn't sneak back in."""
    with mock.patch(
        "core.inference.litellm_client.acompletion",
        new=mock.AsyncMock(return_value=_stub_response()),
    ) as mock_call:
        await chat_complete(
            model="anthropic/claude-sonnet-4-5",
            temperature=0.3,
            max_tokens=8192,
            system="sys",
            user="usr",
            response_format=None,
            timeout_seconds=10,
        )
    kwargs = mock_call.call_args.kwargs
    assert "extra_headers" not in kwargs


@pytest.mark.asyncio
async def test_openai_call_preserves_response_format_kwarg() -> None:
    """Non-Anthropic calls still see ``response_format`` (Anthropic
    has it dropped in chat_complete because litellm 1.40.20 rejects
    it on Anthropic)."""
    with mock.patch(
        "core.inference.litellm_client.acompletion",
        new=mock.AsyncMock(return_value=_stub_response()),
    ) as mock_call:
        await chat_complete(
            model="openai/gpt-4o",
            temperature=0.3,
            max_tokens=4000,
            system="sys",
            user="usr",
            response_format={"type": "json_object"},
            timeout_seconds=10,
        )
    kwargs = mock_call.call_args.kwargs
    assert kwargs.get("response_format") == {"type": "json_object"}
    assert "extra_headers" not in kwargs
