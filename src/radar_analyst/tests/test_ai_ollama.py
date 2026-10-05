"""Tests for the Ollama (local) adapter."""

import asyncio
import logging
from typing import Any

import ollama
import pytest

from radar_analyst.ai import ollama as ollama_adapter
from radar_analyst.ai.base import AIError, Request
from radar_analyst.ai.ollama import OllamaAdapter


class _FakeAsyncClient:
    def __init__(
        self,
        response: dict[str, Any] | BaseException,
        **_: Any,
    ):
        self._response = response
        self.last_args: dict[str, Any] | None = None

    async def chat(
        self, *, model: str, messages: list[dict[str, str]]
    ) -> dict[str, Any]:
        self.last_args = {"model": model, "messages": messages}
        if isinstance(self._response, BaseException):
            raise self._response
        return self._response


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any] | BaseException,
) -> list[_FakeAsyncClient]:
    created: list[_FakeAsyncClient] = []

    def _factory(*args: Any, **kwargs: Any) -> _FakeAsyncClient:
        fake = _FakeAsyncClient(response, **kwargs)
        created.append(fake)
        return fake

    monkeypatch.setattr(ollama, "AsyncClient", _factory)
    return created


def test_default_model_is_current_gemma() -> None:
    # RADAR_ANALYST_OLLAMA_MODEL overrides it per host, since what fits
    # depends on the VRAM available.
    assert OllamaAdapter().model == "gemma4:e4b"


def test_available_returns_true_by_default() -> None:
    # Ollama is a local service with no API key; availability is
    # "can we reach the server?". We treat configured hosts as
    # available at construction time; connection errors surface
    # during analyze().
    adapter = OllamaAdapter(model="gemma4:e4b")
    assert adapter.available() is True


async def test_analyze_returns_markdown_and_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(
        monkeypatch,
        {
            "message": {
                "role": "assistant",
                "content": "**[CRITICAL]**\nwal_level=minimal",
            },
            "prompt_eval_count": 200,
            "eval_count": 35,
        },
    )
    adapter = OllamaAdapter(model="gemma4:e4b")
    res = await adapter.analyze(
        Request(
            category="PostgreSQL Configuration",
            system_prompt="SYS",
            user_prompt="USER",
            cache_static=False,
        )
    )
    assert res.markdown == (
        "**[CRITICAL]**\nwal_level=minimal"
    )
    assert res.verdict == "CRITICAL"
    assert res.prompt_tokens == 200
    assert res.completion_tokens == 35


async def test_analyze_sends_system_then_user_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = _patch_client(
        monkeypatch,
        {"message": {"role": "assistant", "content": "ok"}},
    )
    adapter = OllamaAdapter(model="gemma4:e4b")
    await adapter.analyze(
        Request(
            category="Host & OS",
            system_prompt="SYSTEM-HERE",
            user_prompt="USER-HERE",
            cache_static=False,
        )
    )
    assert len(clients) == 1
    assert clients[0].last_args == {
        "model": "gemma4:e4b",
        "messages": [
            {"role": "system", "content": "SYSTEM-HERE"},
            {"role": "user", "content": "USER-HERE"},
        ],
    }


async def test_analyze_wraps_sdk_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(
        monkeypatch,
        ConnectionError("connection refused"),
    )
    adapter = OllamaAdapter(model="gemma4:e4b")
    with pytest.raises(AIError):
        await adapter.analyze(
            Request(
                category="Host & OS",
                system_prompt="SYS",
                user_prompt="USER",
                cache_static=False,
            )
        )


async def test_concurrency_is_bounded_by_semaphore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent analyze() calls must not exceed ``concurrency``."""
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    class _SlowClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def chat(
            self,
            *,
            model: str,
            messages: list[dict[str, str]],
        ) -> dict[str, Any]:
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1
            return {
                "message": {
                    "role": "assistant",
                    "content": "ok",
                }
            }

    monkeypatch.setattr(ollama, "AsyncClient", _SlowClient)

    adapter = OllamaAdapter(model="m", concurrency=2)
    req = Request(
        category="X",
        system_prompt="s",
        user_prompt="u",
        cache_static=False,
    )
    await asyncio.gather(*(adapter.analyze(req) for _ in range(6)))
    assert max_in_flight <= 2


@pytest.mark.parametrize("value", ["0", "-1", "three"])
async def test_an_unusable_concurrency_gives_the_default(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    value: str,
) -> None:
    # Zero makes a semaphore that no call can acquire, and a negative
    # value one that cannot be made at all.
    _patch_client(monkeypatch, {"message": {"content": "ok"}})
    monkeypatch.setenv("RADAR_ANALYST_OLLAMA_CONCURRENCY", value)
    with caplog.at_level(logging.WARNING):
        adapter = OllamaAdapter(model="m")
    req = Request(
        category="X",
        system_prompt="s",
        user_prompt="u",
        cache_static=False,
    )
    result = await asyncio.wait_for(adapter.analyze(req), timeout=5.0)
    assert result.markdown == "ok"
    assert adapter.concurrency == 3
    assert "RADAR_ANALYST_OLLAMA_CONCURRENCY" in caplog.text


def test_unavailable_reason_is_empty_when_always_available() -> None:
    adapter = OllamaAdapter()
    assert adapter.available() is True
    assert adapter.unavailable_reason() == ""


async def test_a_server_that_never_answers_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled server leaves an unavailable brief, not a stalled job."""

    async def silent(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.read()

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.delenv("RADAR_ANALYST_OLLAMA_HOST", raising=False)
    monkeypatch.setattr(ollama_adapter, "_TIMEOUT_SECONDS", 0.5)
    adapter = OllamaAdapter(model="m", host=f"http://127.0.0.1:{port}")
    req = Request(
        category="X",
        system_prompt="s",
        user_prompt="u",
        cache_static=False,
    )
    try:
        with pytest.raises(AIError, match=r"\(timeout\)"):
            await asyncio.wait_for(adapter.analyze(req), timeout=5.0)
    finally:
        server.close()
