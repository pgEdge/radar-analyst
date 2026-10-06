"""Tests for the built-in mock AI provider (e2e-only)."""

import pytest

from radar_analyst.ai.base import Request
from radar_analyst.ai.mock import MockAdapter


def test_mock_conforms_to_analyzer_protocol() -> None:
    from radar_analyst.ai.base import Analyzer

    assert isinstance(MockAdapter(), Analyzer)


def test_mock_is_always_available() -> None:
    assert MockAdapter().available() is True


async def test_mock_returns_deterministic_healthy_markdown() -> None:
    adapter = MockAdapter()
    res = await adapter.analyze(
        Request(
            category="Host & OS",
            system_prompt="SYS",
            user_prompt="USER",
            cache_static=False,
        )
    )
    assert res.verdict == "HEALTHY"
    assert "Host & OS" in res.markdown
    assert res.markdown.startswith("**[HEALTHY]**")


async def test_mock_never_raises() -> None:
    adapter = MockAdapter()
    for category in (
        "Host & OS",
        "PostgreSQL Configuration",
        "Replication",
    ):
        await adapter.analyze(
            Request(
                category=category,
                system_prompt="",
                user_prompt="",
                cache_static=False,
            )
        )


def test_providers_excludes_mock_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RADAR_ANALYST_TEST", raising=False)
    from radar_analyst.ai import providers

    names = {p.name for p in providers()}
    assert "mock" not in names
    assert {"claude", "gemini", "local", "openai"} <= names


def test_providers_includes_mock_with_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RADAR_ANALYST_TEST", "1")
    from radar_analyst.ai import providers

    names = {p.name for p in providers()}
    assert "mock" in names


def test_make_returns_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RADAR_ANALYST_TEST", "1")
    from radar_analyst.ai import make

    a = make("mock")
    assert a.name == "mock"


def test_make_unknown_provider_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RADAR_ANALYST_TEST", raising=False)
    from radar_analyst.ai import make

    with pytest.raises(ValueError):
        make("no-such-provider")


def test_unavailable_reason_is_empty() -> None:
    adapter = MockAdapter()
    assert adapter.available() is True
    assert adapter.unavailable_reason() == ""
