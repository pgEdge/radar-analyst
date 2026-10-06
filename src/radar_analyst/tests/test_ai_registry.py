"""Tests for the provider that RADAR_ANALYST_AI_PROVIDER selects."""

import pytest

from radar_analyst.ai import DEFAULT_PROVIDER, configured_provider


def test_the_default_provider_applies_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RADAR_ANALYST_AI_PROVIDER", raising=False)
    assert configured_provider() == DEFAULT_PROVIDER


def test_the_variable_selects_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RADAR_ANALYST_AI_PROVIDER", "local")
    assert configured_provider() == "local"


def test_an_empty_variable_selects_the_default_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RADAR_ANALYST_AI_PROVIDER", "")
    assert configured_provider() == DEFAULT_PROVIDER
