"""Ollama (local) adapter.

The Ollama SDK is async-first, so no thread wrapper is needed here.

Local inference is far slower than the cloud adapters, so concurrent
``analyze()`` calls (the orchestrator's per-database fan-out) are
bounded by an :class:`asyncio.Semaphore` and cannot swamp a laptop's
Ollama server. The semaphore is per-adapter, so a caller wanting
global bounds shares one adapter instance.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import ollama

from radar_analyst.ai.base import (
    Request,
    Result,
    raise_ai_error,
    result_from,
)
from radar_analyst.env import positive_int_env


_DEFAULT_HOST = "http://localhost:11434"
# Gemma 4 E4B: ~4.5B effective params, needing ~10 GB VRAM to run
# fully on GPU and partially offloading to CPU on smaller cards.
# RADAR_ANALYST_OLLAMA_MODEL overrides it per host.
_DEFAULT_MODEL = "gemma4:e4b"
_DEFAULT_CONCURRENCY = 3
# How long one call waits for the server's answer: the ten minutes
# that the anthropic and openai SDKs allow a call by default. A
# server that takes a request and never answers then costs one
# unavailable brief rather than an assessment that never finishes.
_TIMEOUT_SECONDS = 600.0

_logger = logging.getLogger(__name__)


@dataclass
class OllamaAdapter:
    """Analyzer backed by a local Ollama server."""

    name: str = "local"
    model: str = _DEFAULT_MODEL
    host: str = field(default=_DEFAULT_HOST)
    concurrency: int = _DEFAULT_CONCURRENCY
    # Lazily initialized so the semaphore is attached to the caller's
    # running loop.
    _sem: asyncio.Semaphore | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Apply the RADAR_ANALYST_OLLAMA_* overrides."""
        env_host = os.environ.get("RADAR_ANALYST_OLLAMA_HOST")
        if env_host:
            self.host = env_host
        env_model = os.environ.get("RADAR_ANALYST_OLLAMA_MODEL")
        if env_model:
            self.model = env_model
        self.concurrency = positive_int_env(
            "RADAR_ANALYST_OLLAMA_CONCURRENCY", self.concurrency
        )

    def available(self) -> bool:
        """Report availability, which is unconditional here."""
        # No API key to check. Reachability is probed at request
        # time, so a transient Ollama restart reads as a per-call
        # error rather than a startup rejection.
        return True

    def unavailable_reason(self) -> str:
        """Empty: this provider has no startup precondition."""
        return ""

    def _semaphore(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.concurrency)
        return self._sem

    async def analyze(self, req: Request) -> Result:
        """Run one category analysis and return the parsed result.

        Waits on the per-instance semaphore first, and raises
        :class:`radar_analyst.ai.base.AIError` when the call fails.
        """
        client: Any = ollama.AsyncClient(host=self.host)
        messages = [
            {"role": "system", "content": req.system_prompt},
            {"role": "user", "content": req.user_prompt},
        ]
        async with self._semaphore():
            try:
                async with asyncio.timeout(_TIMEOUT_SECONDS):
                    response = await client.chat(
                        model=self.model, messages=messages
                    )
            except TimeoutError:
                raise_ai_error(
                    "Ollama",
                    TimeoutError(
                        f"no answer within {_TIMEOUT_SECONDS:.0f}s"
                    ),
                    _logger,
                    kind="timeout",
                )
            except Exception as e:
                raise_ai_error("Ollama", e, _logger)
        markdown = (
            response.get("message", {}).get("content", "") or ""
        )
        return result_from(
            markdown,
            response.get("prompt_eval_count"),
            response.get("eval_count"),
        )
