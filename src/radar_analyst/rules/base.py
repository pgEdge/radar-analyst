"""Deterministic finding generator base types.

A rule is a pure function from the parsed-data dict to a list of
:class:`Finding`. Rules are registered into :data:`REGISTRY` keyed by
category name; the orchestrator runs every rule for the category
before it calls the LLM, passes the findings into the prompt, and
uses the maximum finding severity as a floor on the final verdict
(so the LLM cannot silently downgrade a violation to HEALTHY).
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, TypeVar


_logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class Finding:
    """One deterministic issue a rule concluded from the archive."""

    rule_id: str
    severity: str  # healthy | info | warning | critical
    title: str
    detail: str
    # Stamped by ``register`` from the rule's category, so rule
    # bodies never restate it.
    category: str = ""


RuleFn = Callable[[dict[str, Any]], list[Finding]]

REGISTRY: dict[str, list[RuleFn]] = {}


def register(category: str) -> Callable[[RuleFn], RuleFn]:
    """Decorator: attach a rule function to *category*.

    The returned wrapper stamps *category* onto every finding the
    rule emits (unless the finding already names one).
    """

    def _wrap(fn: RuleFn) -> RuleFn:
        @functools.wraps(fn)
        def _stamped(parsed: dict[str, Any]) -> list[Finding]:
            return [
                f
                if f.category
                else replace(f, category=category)
                for f in fn(parsed)
            ]

        REGISTRY.setdefault(category, []).append(_stamped)
        return _stamped

    return _wrap


def tier(value: float, *, warn: float, crit: float) -> str | None:
    """Map *value* to "critical"/"warning" or None below both."""
    if value >= crit:
        return "critical"
    if value >= warn:
        return "warning"
    return None


def top_n(
    items: Sequence[T],
    fmt: Callable[[T], str],
    n: int = 5,
    sep: str = "; ",
) -> tuple[str, str]:
    """Render the first *n* items plus a ``(+K more)`` suffix.

    Returns ``(examples, suffix)`` where *suffix* is empty when
    everything fits.
    """
    examples = sep.join(fmt(x) for x in items[:n])
    suffix = (
        f" (+{len(items) - n} more)" if len(items) > n else ""
    )
    return examples, suffix


_SEVERITY_ORDER: dict[str, int] = {
    "healthy": 0,
    "info": 1,
    "warning": 2,
    "critical": 3,
}


def severity_rank(s: str | None) -> int:
    """Numeric rank of a finding severity (healthy=0)."""
    return _SEVERITY_ORDER.get(
        (s or "healthy").lower(), 0
    )


def rank_to_verdict(rank: int) -> str:
    """Map a severity rank to a category verdict.

    Info findings inform the brief without making a category
    unhealthy, so ranks 0 (healthy) and 1 (info) both read
    HEALTHY. A verdict is always one of HEALTHY / WARNING /
    CRITICAL.
    """
    if rank >= _SEVERITY_ORDER["critical"]:
        return "CRITICAL"
    if rank >= _SEVERITY_ORDER["warning"]:
        return "WARNING"
    return "HEALTHY"


def apply_finding_floor(
    verdict: str | None, severities: Iterable[str]
) -> str:
    """Return *verdict* floored by the worst finding severity.

    The floor keeps an LLM answer from downgrading a violation
    the rules detected, and carries a category through an LLM
    outage: with no verdict at all, findings alone decide.
    """
    floor = max(
        (severity_rank(s) for s in severities), default=0
    )
    if verdict is None or floor > severity_rank(verdict):
        return rank_to_verdict(floor)
    return verdict


def run_for_category(
    category: str, parsed: dict[str, Any]
) -> list[Finding]:
    """Run every registered rule for *category* against *parsed*."""
    out: list[Finding] = []
    for fn in REGISTRY.get(category, []):
        try:
            out.extend(fn(parsed))
        except Exception as e:
            _logger.warning(
                "rule %s raised: %s", fn.__name__, e
            )
    return out
