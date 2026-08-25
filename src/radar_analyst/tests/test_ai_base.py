"""Tests for the AI adapter base types (Protocol, Request, Result)."""

from dataclasses import dataclass

from radar_analyst.ai.base import (
    Analyzer,
    Request,
    Result,
    parse_verdict,
    usage_tokens,
)


def test_request_and_result_are_frozen() -> None:
    r = Request(
        category="Host & OS",
        system_prompt="hi",
        user_prompt="there",
        cache_static=True,
    )
    try:
        r.category = "other"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("Request should be frozen")
    res = Result(
        markdown="x", verdict="HEALTHY",
        prompt_tokens=None, completion_tokens=None,
    )
    try:
        res.markdown = "y"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("Result should be frozen")


def test_analyzer_protocol_is_runtime_checkable() -> None:
    class _FakeAdapter:
        name = "fake"
        model = "fake-1"

        def available(self) -> bool:
            return True

        def unavailable_reason(self) -> str:
            return ""

        async def analyze(self, req: Request) -> Result:
            return Result(
                markdown="",
                verdict=None,
                prompt_tokens=None,
                completion_tokens=None,
            )

    assert isinstance(_FakeAdapter(), Analyzer)


def test_parse_verdict_variants() -> None:
    assert parse_verdict("**[HEALTHY]**\nAll good.") == "HEALTHY"
    assert parse_verdict("**[WARNING]**\nWatch out.") == "WARNING"
    assert parse_verdict(
        "**[CRITICAL]**\nOn fire."
    ) == "CRITICAL"


def test_parse_verdict_handles_whitespace_and_case() -> None:
    assert parse_verdict("   **[ healthy ]**\nok") == "HEALTHY"
    assert parse_verdict("**[Warning]**") == "WARNING"


def test_parse_verdict_missing_tag_returns_none() -> None:
    assert parse_verdict("nothing to see") is None
    assert parse_verdict("") is None


@dataclass
class _Usage:
    input_tokens: int = 100
    output_tokens: int = 20


def test_usage_tokens_reads_the_named_attributes() -> None:
    assert usage_tokens(
        _Usage(), "input_tokens", "output_tokens"
    ) == (100, 20)


def test_usage_tokens_handles_a_missing_usage_block() -> None:
    # Providers are not obliged to report token counts, and a
    # compatible OpenAI server often does not.
    assert usage_tokens(None, "input_tokens", "output_tokens") == (
        None,
        None,
    )


def test_usage_tokens_handles_missing_attributes() -> None:
    assert usage_tokens(_Usage(), "prompt_tokens", "nope") == (
        None,
        None,
    )


def test_all_adapters_satisfy_the_analyzer_protocol() -> None:
    from radar_analyst.ai.base import Analyzer
    from radar_analyst.ai.claude import ClaudeAdapter
    from radar_analyst.ai.gemini import GeminiAdapter
    from radar_analyst.ai.mock import MockAdapter
    from radar_analyst.ai.ollama import OllamaAdapter
    from radar_analyst.ai.openai_compat import OpenAIAdapter

    adapters = (
        ClaudeAdapter(),
        GeminiAdapter(),
        MockAdapter(),
        OllamaAdapter(),
        OpenAIAdapter(),
    )
    for adapter in adapters:
        assert isinstance(adapter, Analyzer)


def test_categorize_error_buckets() -> None:
    from radar_analyst.ai.base import categorize_error

    assert categorize_error(Exception("Invalid API_KEY")) == "auth"
    assert (
        categorize_error(Exception("429 Too Many Requests"))
        == "rate_limit"
    )
    assert (
        categorize_error(Exception("insufficient_quota"))
        == "rate_limit"
    )
    assert (
        categorize_error(Exception("credit balance too low"))
        == "rate_limit"
    )
    assert (
        categorize_error(Exception("model 'x' not found"))
        == "model_missing"
    )
    assert (
        categorize_error(Exception("connection refused"))
        == "connection"
    )
    assert categorize_error(Exception("boom")) == "generic"


def test_raise_ai_error_formats_provider_and_kind() -> None:
    import logging

    import pytest

    from radar_analyst.ai.base import AIError, raise_ai_error

    with pytest.raises(AIError) as ei:
        raise_ai_error(
            "Claude API",
            ValueError("401 nope"),
            logging.getLogger("t"),
        )
    assert "Claude API call failed (auth)" in str(ei.value)


def test_result_from_parses_verdict() -> None:
    from radar_analyst.ai.base import result_from

    r = result_from("**[WARNING]**\ntext", 10, 20)
    assert r.verdict == "WARNING"
    assert r.prompt_tokens == 10
    assert r.completion_tokens == 20
