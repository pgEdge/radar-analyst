"""Gemini (Google AI Studio / google-genai) adapter.

The google-genai SDK ships a synchronous API, wrapped here in
:func:`asyncio.to_thread` so this adapter satisfies the async
:class:`radar_analyst.ai.base.Analyzer` contract without a second client
library.

``Request.cache_static`` has no effect here. The SDK exposes prompt
caching through the ``cachedContents`` resource rather than a
per-message flag.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from google import genai
from google.genai import types as genai_types

from radar_analyst.ai.base import (
    AIError,
    Request,
    Result,
    raise_ai_error,
    result_from,
    usage_tokens,
)


# Flash-class is the most capable Gemini the free tier covers.
_DEFAULT_MODEL = "gemini-3.7-flash"

_logger = logging.getLogger(__name__)


@dataclass
class GeminiAdapter:
    """Analyzer backed by the google-genai generate-content API."""

    name: str = "gemini"
    model: str = _DEFAULT_MODEL
    api_key: str | None = field(default=None, repr=False)

    def _env_key(self) -> str | None:
        return os.environ.get("GOOGLE_API_KEY") or os.environ.get(
            "GEMINI_API_KEY"
        )

    def available(self) -> bool:
        """Report whether an API key is configured."""
        return bool(self.api_key or self._env_key())

    def unavailable_reason(self) -> str:
        """Explain an ``available() is False`` result for the UI."""
        return "GOOGLE_API_KEY / GEMINI_API_KEY is not set"

    async def analyze(self, req: Request) -> Result:
        """Run one category analysis and return the parsed result.

        Raises :class:`radar_analyst.ai.base.AIError` on a missing key or
        a failed call.
        """
        if not self.available():
            raise AIError(
                "GOOGLE_API_KEY / GEMINI_API_KEY is not set; "
                "Gemini adapter cannot make API calls."
            )
        key = self.api_key or self._env_key()
        client = (
            genai.Client(api_key=key)
            if key is not None
            else genai.Client()
        )
        config = genai_types.GenerateContentConfig(
            system_instruction=req.system_prompt,
        )
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.model,
                contents=req.user_prompt,
                config=config,
            )
        except Exception as e:
            raise_ai_error("Gemini API", e, _logger)
        markdown = getattr(response, "text", "") or ""
        prompt_tokens, completion_tokens = usage_tokens(
            getattr(response, "usage_metadata", None),
            "prompt_token_count",
            "candidates_token_count",
        )
        return result_from(
            markdown, prompt_tokens, completion_tokens
        )
