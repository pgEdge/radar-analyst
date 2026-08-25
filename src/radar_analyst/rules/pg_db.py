"""Per-database inline rules.

Unlike the cluster-level rules in other ``rules/*.py`` modules,
these don't register into the category REGISTRY. They're called
directly from :func:`orchestrator._build_database_summaries`
with the already-aggregated per-db dict, because each rule
needs a specific database's row: not the full parsed state.

Each rule function takes a per-db summary dict and returns a
list of zero or one finding dicts. ``run_per_db_rules`` calls
them all and flattens the result.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Floor thresholds for when a per-db rule is meaningful.
_CACHE_HIT_MIN_BLOCKS = 100_000
_CACHE_HIT_WARN_BELOW = 0.95

_TEMP_FILES_MIN = 100
_TEMP_AVG_WARN_BYTES = 64 * 1024 * 1024  # 64 MiB average


def cache_hit_low(db: dict[str, Any]) -> list[dict[str, str]]:
    """Warn if cache-hit ratio is low on a busy database.

    Skips idle databases to avoid warning on ratios computed
    from a handful of cold reads.
    """
    ratio = db.get("cache_hit_ratio")
    total = (db.get("blks_hit") or 0) + (
        db.get("blks_read") or 0
    )
    if (
        ratio is None
        or total < _CACHE_HIT_MIN_BLOCKS
        or ratio >= _CACHE_HIT_WARN_BELOW
    ):
        return []
    pct = ratio * 100
    return [
        {
            "rule_id": "pg.db.cache_hit_low",
            "severity": "warning",
            "title": (
                f"Buffer cache hit ratio is {pct:.1f}% "
                "(target >=95%)"
            ),
            "detail": (
                "With shared_buffers under-sized or hot data "
                "pushed out by scans, the planner reads from "
                "the OS page cache / disk rather than "
                "PostgreSQL's own buffer pool. Raise "
                "shared_buffers, investigate top queries for "
                "sequential scans on hot tables, or check "
                "whether a recent large backup or VACUUM "
                "FULL evicted the working set."
            ),
        }
    ]


def deadlocks_nonzero(
    db: dict[str, Any],
) -> list[dict[str, str]]:
    """Warn on any non-zero deadlock count.

    Deadlocks indicate lock-order inconsistency in application
    code. Source is per-db ``stat_database.deadlocks``: NOT
    instance-level ``databases_tup.tsv``, which doesn't carry
    this column.
    """
    n = db.get("deadlocks") or 0
    if n == 0:
        return []
    return [
        {
            "rule_id": "pg.db.deadlocks_nonzero",
            "severity": "warning",
            "title": (
                f"{n} deadlock(s) since last stats reset"
            ),
            "detail": (
                "Deadlocks indicate lock-order inconsistency "
                "in application code. Turn on log_lock_waits + "
                "deadlock_timeout and inspect the server log "
                "for the specific statements involved."
            ),
        }
    ]


def temp_files_heavy(
    db: dict[str, Any],
) -> list[dict[str, str]]:
    """Warn when the server is spilling many large temp files.

    Thresholds: at least 100 temp files AND an average size of
    at least 64 MiB per file. Small / few spill files are
    normal and don't warrant a warning.
    """
    n = db.get("temp_files") or 0
    total_bytes = db.get("temp_bytes") or 0
    if n < _TEMP_FILES_MIN:
        return []
    avg = total_bytes / n if n > 0 else 0
    if avg < _TEMP_AVG_WARN_BYTES:
        return []
    avg_mib = avg / (1024 * 1024)
    total_mib = total_bytes / (1024 * 1024)
    return [
        {
            "rule_id": "pg.db.temp_files_heavy",
            "severity": "warning",
            "title": (
                f"{n:,} temp-file spills averaging "
                f"{avg_mib:.0f} MiB "
                f"(total {total_mib:.0f} MiB)"
            ),
            "detail": (
                "Large temp-file spills mean sorts, hashes or "
                "materialised CTEs can't fit in work_mem. "
                "Raise work_mem for the offending roles, "
                "investigate specific queries via "
                "log_temp_files = 0, or rewrite to spill "
                "less."
            ),
        }
    ]


def recovery_conflicts_nonzero(
    db: dict[str, Any],
) -> list[dict[str, str]]:
    """Critical if a standby is cancelling queries for recovery.

    ``confl_lock`` and ``confl_deadlock`` mean the standby is
    being forced to kill long-running reads to keep up with
    the primary's WAL stream. Both indicate a real workload
    issue on the standby.
    """
    n = (db.get("confl_lock") or 0) + (
        db.get("confl_deadlock") or 0
    )
    if n == 0:
        return []
    return [
        {
            "rule_id": "pg.db.recovery_conflicts_nonzero",
            "severity": "critical",
            "title": (
                f"{n} recovery conflict(s) "
                "(queries cancelled for replay)"
            ),
            "detail": (
                "On a hot standby, long-running reads are "
                "being killed to let WAL replay proceed. "
                "Either raise max_standby_streaming_delay, "
                "enable hot_standby_feedback, or move the "
                "reads off the standby."
            ),
        }
    ]


_RULES: tuple[Callable[[dict[str, Any]], list[dict[str, str]]], ...] = (
    cache_hit_low,
    deadlocks_nonzero,
    temp_files_heavy,
    recovery_conflicts_nonzero,
)


def run_per_db_rules(
    db: dict[str, Any],
) -> list[dict[str, str]]:
    """Call every per-db rule against *db* and flatten results."""
    out: list[dict[str, str]] = []
    for fn in _RULES:
        try:
            out.extend(fn(db))
        except Exception:  # noqa: BLE001
            # A broken rule must not break the summary build.
            # Logging is handled at orchestrator level.
            continue
    return out
