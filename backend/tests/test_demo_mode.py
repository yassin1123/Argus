"""Tests for the demo-mode env detection helper."""

from __future__ import annotations

import os

import pytest

from core.demo_mode import has_openai_key, is_demo_mode


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "True"])
def test_demo_mode_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("DEMO_MODE", value)
    assert is_demo_mode() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_demo_mode_falsy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("DEMO_MODE", value)
    assert is_demo_mode() is False


def test_demo_mode_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert is_demo_mode() is False


def test_has_openai_key_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert has_openai_key() is True


def test_has_openai_key_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert has_openai_key() is False


def test_has_openai_key_when_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    assert has_openai_key() is False
