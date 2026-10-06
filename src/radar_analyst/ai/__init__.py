"""AI-provider registry.

Each provider has a short ``name`` (used in ``/api/config`` and the
``RADAR_ANALYST_AI_PROVIDER`` env var), a human-facing ``label``, and a
zero-arg factory producing an :class:`Analyzer` instance.

The ``mock`` provider is registered only when ``RADAR_ANALYST_TEST=1``, so
e2e tests run without real API keys.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from radar_analyst.ai.base import Analyzer
from radar_analyst.ai.claude import ClaudeAdapter
from radar_analyst.ai.gemini import GeminiAdapter
from radar_analyst.ai.ollama import OllamaAdapter
from radar_analyst.ai.openai_compat import OpenAIAdapter


DEFAULT_PROVIDER = "claude"


@dataclass(frozen=True)
class ProviderInfo:
    """One registry entry: the key, the UI label, the factory."""

    name: str
    label: str
    factory: Callable[[], Analyzer]


_REAL_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(
        name="claude",
        label="Claude (Anthropic)",
        factory=ClaudeAdapter,
    ),
    ProviderInfo(
        name="gemini",
        label="Gemini (Google)",
        factory=GeminiAdapter,
    ),
    ProviderInfo(
        name="openai",
        label="OpenAI / compatible",
        factory=OpenAIAdapter,
    ),
    ProviderInfo(
        name="local",
        label="Local (Ollama)",
        factory=OllamaAdapter,
    ),
]


def providers() -> list[ProviderInfo]:
    """Return known providers, conditionally including the mock."""
    out = list(_REAL_PROVIDERS)
    if os.environ.get("RADAR_ANALYST_TEST") == "1":
        # Import lazily so the mock module isn't loaded in prod.
        from radar_analyst.ai.mock import MockAdapter

        out.append(
            ProviderInfo(
                name="mock",
                label="Mock (tests only)",
                factory=MockAdapter,
            )
        )
    return out


def make(name: str) -> Analyzer:
    """Instantiate the provider identified by *name*."""
    for p in providers():
        if p.name == name:
            return p.factory()
    raise ValueError(f"unknown AI provider: {name}")


def configured_provider() -> str:
    """Name the provider that RADAR_ANALYST_AI_PROVIDER selects."""
    return os.environ.get("RADAR_ANALYST_AI_PROVIDER") or DEFAULT_PROVIDER


__all__ = [
    "DEFAULT_PROVIDER",
    "ProviderInfo",
    "configured_provider",
    "make",
    "providers",
]
