"""OpenAI adapter, also covering OpenAI-compatible endpoints.

One adapter serves OpenAI itself and any server that speaks the
chat-completions API (vLLM, LM Studio, llama.cpp, OpenRouter, Groq,
Ollama's ``/v1`` endpoint), because the request shape is identical and
only the endpoint and model name differ.

Configuration uses the SDK's own env vars, so an operator with an
OpenAI environment already set up needs no extra wiring:

- ``OPENAI_API_KEY``: required, even for servers that ignore it
- ``OPENAI_BASE_URL``: points at a compatible server
- ``OPENAI_MODEL``: the model name, which compatible servers need
  because each names its models its own way

``Request.cache_static`` has no effect here. OpenAI applies its
prompt-cache discount on its own, with no per-request flag to set, and
compatible servers each have their own policy.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import openai
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from radar_analyst.ai.base import (
    AIError,
    Request,
    Result,
    call_provider,
    categorize_error,
    result_from,
    usage_tokens,
)


# OPENAI_MODEL overrides this, and a compatible server needs it to,
# because each names its models its own way.
_DEFAULT_MODEL = "gpt-5.6-luna"

# OpenAI's own endpoint, passed to the SDK explicitly because the SDK
# takes an empty OPENAI_BASE_URL literally and builds requests against
# it, and an env var handed through unset arrives as an empty string.
_DEFAULT_BASE_URL = "https://api.openai.com/v1"

_logger = logging.getLogger(__name__)


# Typed SDK exceptions, first match wins. A 404 means the server has
# no such model: OpenAI returns it for an unknown model name, and a
# compatible server for one it has not loaded. A connection attempt
# that times out arrives as APITimeoutError, a subclass of
# APIConnectionError, so it reads as "connection"; a provider that
# never answers reaches the call's own time limit first.
_ERROR_TYPES: tuple[tuple[type[Exception], str], ...] = (
    (openai.AuthenticationError, "auth"),
    (openai.PermissionDeniedError, "auth"),
    (openai.RateLimitError, "rate_limit"),
    (openai.APIConnectionError, "connection"),
    (openai.NotFoundError, "model_missing"),
)


def _categorize_error(exc: BaseException) -> str:
    """Classify an OpenAI (or compatible-server) error for the log.

    Returns one of ``auth``, ``rate_limit``, ``connection``,
    ``model_missing`` or ``generic``. Typed SDK exceptions win;
    compatible servers reporting errors in their own shapes fall
    back to the shared message markers.
    """
    for exc_type, kind in _ERROR_TYPES:
        if isinstance(exc, exc_type):
            return kind
    return categorize_error(exc)


def _messages(req: Request) -> list[ChatCompletionMessageParam]:
    """Build the chat-completions message list.

    A system message plus a user message is the shape every
    compatible server implements.
    """
    return [
        ChatCompletionSystemMessageParam(
            role="system", content=req.system_prompt
        ),
        ChatCompletionUserMessageParam(
            role="user", content=req.user_prompt
        ),
    ]


@dataclass
class OpenAIAdapter:
    """Analyzer backed by the chat-completions API.

    ``OPENAI_MODEL`` and ``OPENAI_BASE_URL`` win over the model and
    endpoint passed here, so a deployment's choice beats a caller's
    default. The API key resolves the other way round, constructor
    before ``OPENAI_API_KEY``, so a caller can hand in a specific key.
    """

    name: str = "openai"
    model: str = _DEFAULT_MODEL
    # None selects OpenAI itself, via _DEFAULT_BASE_URL.
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Apply the OPENAI_MODEL / OPENAI_BASE_URL overrides."""
        env_model = os.environ.get("OPENAI_MODEL")
        if env_model:
            self.model = env_model
        env_base = os.environ.get("OPENAI_BASE_URL")
        if env_base:
            self.base_url = env_base

    def _resolved_api_key(self) -> str | None:
        """Return the configured key, constructor before env."""
        return self.api_key or os.environ.get("OPENAI_API_KEY")

    def available(self) -> bool:
        """Report whether an API key is configured.

        A key is the test even against a compatible server that
        ignores it, because the SDK requires one to build a client.
        """
        return bool(self._resolved_api_key())

    def unavailable_reason(self) -> str:
        """Explain an ``available() is False`` result for the UI."""
        return "OPENAI_API_KEY is not set"

    async def analyze(self, req: Request) -> Result:
        """Run one category analysis and return the parsed result.

        Raises :class:`radar_analyst.ai.base.AIError` when no key is
        configured or the call fails, which the orchestrator turns
        into a "brief unavailable" row.
        """
        key = self._resolved_api_key()
        if not key:
            raise AIError(
                "OPENAI_API_KEY is not set; OpenAI adapter cannot "
                "make API calls."
            )
        client = AsyncOpenAI(
            api_key=key,
            base_url=self.base_url or _DEFAULT_BASE_URL,
        )
        response = await call_provider(
            "OpenAI API",
            client.chat.completions.create(
                model=self.model,
                messages=_messages(req),
            ),
            _logger,
            _categorize_error,
        )
        markdown = ""
        if response.choices:
            markdown = response.choices[0].message.content or ""
        prompt_tokens, completion_tokens = usage_tokens(
            getattr(response, "usage", None),
            "prompt_tokens",
            "completion_tokens",
        )
        return result_from(
            markdown, prompt_tokens, completion_tokens
        )
