"""The assessment: an upload's briefs taken together.

An assessment carries one verdict per category, plus a roll-up
verdict that is the worst of them. ``UNKNOWN`` marks a category the
archive holds no data for, so it never outranks a verdict that was
actually concluded from evidence: an uncollected category cannot
make a system look worse than what was measured. An assessment with
nothing but ``UNKNOWN`` categories stays ``UNKNOWN``.
"""

from __future__ import annotations

from collections.abc import Iterable

from radar_analyst.rules.base import rank_to_verdict, severity_rank


UNKNOWN = "UNKNOWN"


def rollup_verdict(
    verdicts: Iterable[str | None],
) -> str | None:
    """Return the worst of *verdicts*, or None if there are none."""
    seen = list(verdicts)
    if not seen:
        return None
    concluded = [
        v
        for v in seen
        if v is not None and v.upper() != UNKNOWN
    ]
    if not concluded:
        return UNKNOWN
    return rank_to_verdict(
        max(severity_rank(v) for v in concluded)
    )
