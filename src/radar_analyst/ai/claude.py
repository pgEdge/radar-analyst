"""Claude (Anthropic) adapter.

- the system block carries ``cache_control: {"type": "ephemeral"}``
  when ``Request.cache_static`` is true, so the orchestrator pays the
  system tokens once per upload and cache-hits for the remaining
  categories
- response content is a list of blocks, and the text blocks are
  concatenated
- errors are categorized (auth / rate-limit / generic) and wrapped in
  :class:`radar_analyst.ai.base.AIError`, which the orchestrator persists
  as a "brief unavailable" marker
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic
from anthropic.types import (
    CacheControlEphemeralParam,
    MessageParam,
    TextBlock,
    TextBlockParam,
)

from radar_analyst.ai.base import (
    AIError,
    Request,
    Result,
    raise_ai_error,
    result_from,
    usage_tokens,
)

# Sonnet rather than Opus, because one upload costs a call per
# category plus a call for every active database, and the prompts
# carry structured facts rather than open-ended reasoning.
_DEFAULT_MODEL = "claude-sonnet-5"
_DEFAULT_MAX_TOKENS = 4096

_logger = logging.getLogger(__name__)


def _system_blocks(req: Request) -> list[TextBlockParam]:
    """Build the system block, cached when the request asks for it.

    An ephemeral cache_control marker makes Anthropic bill the system
    tokens once per upload and cache-hit for the remaining
    categories.
    """
    if not req.cache_static:
        return [
            TextBlockParam(type="text", text=req.system_prompt)
        ]
    return [
        TextBlockParam(
            type="text",
            text=req.system_prompt,
            cache_control=CacheControlEphemeralParam(
                type="ephemeral"
            ),
        )
    ]


def _user_messages(req: Request) -> list[MessageParam]:
    """Wrap the user prompt as the single user message."""
    return [
        MessageParam(
            role="user",
            content=[
                TextBlockParam(
                    type="text", text=req.user_prompt
                )
            ],
        )
    ]


@dataclass
class ClaudeAdapter:
    """Analyzer backed by the Anthropic Messages API."""

    name: str = "claude"
    model: str = _DEFAULT_MODEL
    max_tokens: int = _DEFAULT_MAX_TOKENS
    api_key: str | None = field(default=None, repr=False)

    def available(self) -> bool:
        """Report whether an API key is configured."""
        return bool(
            self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        )

    def unavailable_reason(self) -> str:
        """Explain an ``available() is False`` result for the UI."""
        return "ANTHROPIC_API_KEY is not set"

    async def analyze(self, req: Request) -> Result:
        """Run one category analysis and return the parsed result.

        Honours ``Request.cache_static`` by marking the system block
        ephemeral, so the system tokens are paid once per upload.
        Raises :class:`radar_analyst.ai.base.AIError` on a missing key or
        a failed call.
        """
        if not self.available():
            raise AIError(
                "ANTHROPIC_API_KEY is not set; Claude adapter "
                "cannot make API calls."
            )
        client = (
            AsyncAnthropic(api_key=self.api_key)
            if self.api_key
            else AsyncAnthropic()
        )
        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=_system_blocks(req),
                messages=_user_messages(req),
            )
        except Exception as e:
            raise_ai_error("Claude API", e, _logger)
        markdown = "".join(
            b.text
            for b in response.content
            if isinstance(b, TextBlock)
        )
        prompt_tokens, completion_tokens = usage_tokens(
            getattr(response, "usage", None),
            "input_tokens",
            "output_tokens",
        )
        return result_from(
            markdown, prompt_tokens, completion_tokens
        )
