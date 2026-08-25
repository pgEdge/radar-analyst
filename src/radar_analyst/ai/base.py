"""AI-adapter base types and helpers.

The provider-specific adapters (``claude``, ``gemini``, ``ollama``,
``openai_compat``) satisfy the ``Analyzer`` protocol defined here. The
orchestrator calls them via this shape so adapters can be swapped or
mocked without touching the rest of the pipeline.

Errors:
- ``AIError`` is the base class for anything the adapters can raise.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import NoReturn, Protocol, runtime_checkable


class AIError(Exception):
    """Base class for AI-adapter errors."""


@dataclass(frozen=True)
class Request:
    """One category's prompts, as handed to an adapter."""

    category: str
    system_prompt: str
    user_prompt: str
    # Claude honours this to mark the system block as ephemeral-
    # cached. Other providers ignore the flag.
    cache_static: bool = False


@dataclass(frozen=True)
class Result:
    """An adapter's answer: markdown, severity, token counts."""

    markdown: str
    verdict: str | None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@runtime_checkable
class Analyzer(Protocol):
    """The shape the orchestrator calls every provider through."""

    name: str
    model: str

    def available(self) -> bool:
        """Report whether this provider is configured to be called."""

    def unavailable_reason(self) -> str:
        """Explain an ``available() is False`` result for the UI.

        Empty for providers with no startup precondition.
        """

    async def analyze(self, req: Request) -> Result:
        """Analyze one category, raising ``AIError`` on failure."""


def usage_tokens(
    usage: object, prompt_attr: str, completion_attr: str
) -> tuple[int | None, int | None]:
    """Read a provider's token counts off its usage object.

    Each SDK names the two counts differently, and none of them
    guarantees a usage block at all, so adapters name the attributes
    they want and get ``None`` for whatever is absent.
    """
    if usage is None:
        return None, None
    return (
        getattr(usage, prompt_attr, None),
        getattr(usage, completion_attr, None),
    )


# Match "[HEALTHY]", "[WARNING]", "[CRITICAL]" with optional
# surrounding bold markers and arbitrary inner whitespace / case.
_VERDICT_RE = re.compile(
    r"\*{0,2}\[\s*(HEALTHY|WARNING|CRITICAL)\s*\]\*{0,2}",
    re.IGNORECASE,
)


# Message markers shared by every provider's error strings. The
# typed-SDK adapters (openai) check their exception classes first
# and fall back here.
_ERROR_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "auth",
        (
            "api_key",
            "api key",
            "authentication",
            "unauthenticated",
            "permission_denied",
            "401",
            "403",
        ),
    ),
    (
        "rate_limit",
        (
            "rate",
            "quota",
            "credit",
            "insufficient_quota",
            "resource_exhausted",
            "429",
        ),
    ),
    ("connection", ("connection", "refused")),
)


def categorize_error(exc: BaseException) -> str:
    """Bucket *exc* by message into a coarse failure kind.

    Returns ``auth``, ``rate_limit``, ``model_missing``,
    ``connection`` or ``generic``, for log lines and AIError
    text that an operator can act on without reading the whole
    provider traceback.
    """
    msg = str(exc).lower()
    if "model" in msg and "not found" in msg:
        return "model_missing"
    for kind, markers in _ERROR_MARKERS:
        if any(m in msg for m in markers):
            return kind
    return "generic"


def raise_ai_error(
    provider: str,
    exc: Exception,
    logger: logging.Logger,
    kind: str | None = None,
) -> NoReturn:
    """Log *exc* and re-raise it as :class:`AIError`.

    *provider* is the human-readable prefix ("Claude API",
    "Ollama"); *kind* overrides the message-based classification
    for adapters with typed SDK exceptions.
    """
    kind = kind or categorize_error(exc)
    logger.error("%s call failed (%s): %s", provider, kind, exc)
    raise AIError(
        f"{provider} call failed ({kind}): {exc}"
    ) from exc


def result_from(
    markdown: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> Result:
    """Build a :class:`Result`, parsing the verdict tag."""
    return Result(
        markdown=markdown,
        verdict=parse_verdict(markdown),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def parse_verdict(markdown: str) -> str | None:
    """Extract ``HEALTHY``/``WARNING``/``CRITICAL`` from *markdown*.

    Returns the upper-case tag, or ``None`` if no tag is present. Lets
    adapters stay schema-free (the LLM emits markdown per the system
    prompt's contract) while the orchestrator still gets a structured
    severity to persist alongside the raw output.
    """
    if not markdown:
        return None
    m = _VERDICT_RE.search(markdown)
    if m is None:
        return None
    return m.group(1).upper()
