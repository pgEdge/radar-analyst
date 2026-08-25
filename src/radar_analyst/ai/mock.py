"""Built-in mock AI provider for e2e tests.

Registered in the provider list ONLY when ``RADAR_ANALYST_TEST=1`` is in the
environment. Returns deterministic canned markdown tagged
``**[HEALTHY]**`` so the full analysis pipeline can run end-to-end in
CI without any real API keys. It is NOT registered in normal operation,
so it cannot leak into production.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.ai.base import Request, Result, result_from

_TEMPLATE = (
    "**[HEALTHY]**\n"
    "Mock analysis for category {category}. "
    "This output comes from the built-in mock provider and is "
    "only enabled when RADAR_ANALYST_TEST=1. The pipeline exercises "
    "parsing, rules, storage, and UI rendering end-to-end "
    "without calling a real LLM API."
)


@dataclass
class MockAdapter:
    """Deterministic stand-in analyzer for tests and e2e runs."""
    name: str = "mock"
    model: str = "mock-v0"

    def available(self) -> bool:
        """Report availability, which is unconditional here."""
        return True

    def unavailable_reason(self) -> str:
        """Empty: the mock provider is always available."""
        return ""

    async def analyze(self, req: Request) -> Result:
        """Return a canned brief for the requested category."""
        markdown = _TEMPLATE.format(category=req.category)
        return result_from(markdown, 0, 0)
