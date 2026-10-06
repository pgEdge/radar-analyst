"""Human-readable formatting for counts, sizes, and durations.

Shared by the facts builders and the snapshot summaries so the
prompt text and the console read the same way.
"""

from __future__ import annotations


def format_uptime(seconds: float) -> str:
    """Render an uptime in compact d/h/m units."""
    s = int(seconds)
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    minutes, _ = divmod(s, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_age_seconds(s: float | None) -> str:
    """Render a duration in DBA-friendly compound units."""
    if s is None:
        return "n/a"
    if s < 1.0:
        return f"{s * 1000:.1f} ms"
    if s < 60.0:
        return f"{s:.1f} s"
    if s < 3600.0:
        return f"{s / 60:.1f} min"
    if s < 86400.0:
        return f"{s / 3600:.2f} h"
    return f"{s / 86400:.2f} d"


def format_count(n: int) -> str:
    """Compact human-readable row count: 1500 → '1.5K', 1.2e6 → '1.2M'."""
    if n < 1000:
        return f"{n}"
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1_000_000_000:.1f}B"


def format_size_bytes(n: int) -> str:
    """Render a byte count in B/KiB/MiB/GiB units."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KiB"
    if n < 1024 ** 3:
        return f"{n / (1024 ** 2):.0f} MiB"
    return f"{n / (1024 ** 3):.1f} GiB"
