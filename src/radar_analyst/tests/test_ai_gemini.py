"""Tests for the Gemini adapter."""

from dataclasses import dataclass
from typing import Any

import pytest
from google import genai

from radar_analyst.ai.base import AIError, Request
from radar_analyst.ai.gemini import GeminiAdapter


# ---------------------------------------------------------------------
# Fakes that model the parts of the google-genai surface we use.
# ---------------------------------------------------------------------


@dataclass
class _FakeUsage:
    prompt_token_count: int | None = 123
    candidates_token_count: int | None = 45


@dataclass
class _FakeResponse:
    text: str
    usage_metadata: _FakeUsage | None = None


class _FakeModels:
    def __init__(self, response: _FakeResponse | BaseException):
        self._response = response
        self.last_args: dict[str, Any] | None = None

    def generate_content(
        self, *, model: str, contents: Any, config: Any
    ) -> _FakeResponse:
        self.last_args = {
            "model": model,
            "contents": contents,
            "config": config,
        }
        if isinstance(self._response, BaseException):
            raise self._response
        return self._response


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    response: _FakeResponse | BaseException,
) -> _FakeModels:
    models = _FakeModels(response)

    def _factory(*args: Any, **kwargs: Any) -> _FakeClient:
        return _FakeClient(models)

    monkeypatch.setattr(genai, "Client", _factory)
    return models


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------


def test_default_model_is_current_flash() -> None:
    # Flash-class is the most capable Gemini the free tier covers.
    assert GeminiAdapter().model == "gemini-3.7-flash"


def test_available_true_with_explicit_key() -> None:
    assert GeminiAdapter(api_key="k").available() is True


def test_available_reads_google_api_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiAdapter().available() is False
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    assert GeminiAdapter().available() is True


def test_available_reads_gemini_api_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert GeminiAdapter().available() is True


async def test_analyze_returns_markdown_and_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(
        monkeypatch,
        _FakeResponse(
            text="**[WARNING]**\nswap is configured",
            usage_metadata=_FakeUsage(),
        ),
    )
    adapter = GeminiAdapter(api_key="k")
    res = await adapter.analyze(
        Request(
            category="Host & OS",
            system_prompt="SYS",
            user_prompt="USER",
            cache_static=False,
        )
    )
    assert res.markdown == "**[WARNING]**\nswap is configured"
    assert res.verdict == "WARNING"
    assert res.prompt_tokens == 123
    assert res.completion_tokens == 45


async def test_analyze_passes_system_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = _patch_client(
        monkeypatch,
        _FakeResponse(text="**[HEALTHY]**"),
    )
    adapter = GeminiAdapter(api_key="k")
    await adapter.analyze(
        Request(
            category="Host & OS",
            system_prompt="SYSTEM-HERE",
            user_prompt="USER-HERE",
            cache_static=False,
        )
    )
    assert models.last_args is not None
    assert models.last_args["contents"] == "USER-HERE"
    cfg = models.last_args["config"]
    assert getattr(cfg, "system_instruction", None) == (
        "SYSTEM-HERE"
    )


async def test_analyze_without_keys_raises_aierror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    adapter = GeminiAdapter()
    with pytest.raises(AIError):
        await adapter.analyze(
            Request(
                category="Host & OS",
                system_prompt="SYS",
                user_prompt="USER",
                cache_static=False,
            )
        )


async def test_analyze_wraps_sdk_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(
        monkeypatch, RuntimeError("quota exceeded")
    )
    adapter = GeminiAdapter(api_key="k")
    with pytest.raises(AIError):
        await adapter.analyze(
            Request(
                category="Host & OS",
                system_prompt="SYS",
                user_prompt="USER",
                cache_static=False,
            )
        )


def test_unavailable_reason_names_the_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    adapter = GeminiAdapter()
    assert adapter.available() is False
    reason = adapter.unavailable_reason()
    assert "GOOGLE_API_KEY" in reason
    assert "GEMINI_API_KEY" in reason
