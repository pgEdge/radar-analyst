"""Parse ``system/proc/loadavg.out`` (a single line from /proc/loadavg).

Format: ``0.52 0.58 0.59 1/418 12345``
- 1-minute, 5-minute, 15-minute load averages,
- running/total tasks,
- last PID created.

We only carry the three load averages; the rest is noise for
rule purposes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoadAverage:
    """The three load averages from /proc/loadavg."""
    load1: float
    load5: float
    load15: float


def parse_loadavg(data: bytes) -> LoadAverage | None:
    """Parse /proc/loadavg into a LoadAverage."""
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    parts = text.split()
    if len(parts) < 3:
        return None
    try:
        return LoadAverage(
            load1=float(parts[0]),
            load5=float(parts[1]),
            load15=float(parts[2]),
        )
    except ValueError:
        return None
