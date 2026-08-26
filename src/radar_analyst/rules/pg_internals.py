"""Internals & I/O Health rules over bgwriter, checkpointer, and
WAL activity counters.
"""

from __future__ import annotations

from typing import Any

from radar_analyst.parse.pg_internals import (
    PgBgwriter,
    PgCheckpointer,
    PgStatWal,
)
from radar_analyst.rules.base import Finding, register


# Checkpoint requested-ratio threshold: > 50% of checkpoints
# triggered by demand rather than schedule indicates the checkpoint
# interval is too short or write load is too high.
_CHECKPOINT_REQ_RATIO_WARN = 0.5


@register("Internals & I/O Health")
def wal_buffers_full(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when pg_stat_wal.wal_buffers_full > 0.

    A non-zero value means WAL buffers were exhausted and had to be
    written to WAL files mid-transaction (adding latency). This
    typically means ``wal_buffers`` is too small; PG's default of -1
    (1/32 of shared_buffers, min 64 kB) is usually fine but can
    be insufficient on highly concurrent write workloads.
    """
    w: PgStatWal | None = parsed.get("pg.stat_wal")
    if w is None or w.wal_buffers_full == 0:
        return []
    return [
        Finding(
            rule_id="pg.internals.wal_buffers_full",
            severity="warning",
            title=(
                f"WAL buffers exhausted "
                f"{w.wal_buffers_full:,} time(s)"
            ),
            detail=(
                "pg_stat_wal.wal_buffers_full > 0 means WAL "
                "buffers ran out and were flushed mid-transaction,"
                " adding latency. Consider increasing "
                "wal_buffers (default -1 = 1/32 of "
                "shared_buffers). On PG ≥ 10 the default "
                "usually auto-sizes correctly; if this counter "
                "keeps rising, profile concurrent WAL writers."
            ),
        )
    ]


@register("Internals & I/O Health")
def checkpoint_req_ratio_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when more than 50 % of checkpoints are requested.

    Prefers ``pg.checkpointer`` (PG17+) over ``pg.bgwriter``
    (pre-PG17) when both are present.  Silent when neither file
    is in the archive.
    """
    timed: int | None = None
    requested: int | None = None

    cp: PgCheckpointer | None = parsed.get("pg.checkpointer")
    if cp is not None:
        timed = cp.num_timed
        requested = cp.num_requested
    else:
        bg: PgBgwriter | None = parsed.get("pg.bgwriter")
        if bg is not None:
            timed = bg.checkpoints_timed
            requested = bg.checkpoints_req

    if timed is None or requested is None:
        return []
    total = timed + requested
    if total == 0:
        return []
    ratio = requested / total
    if ratio <= _CHECKPOINT_REQ_RATIO_WARN:
        return []

    pct = f"{ratio * 100:.0f}%"
    return [
        Finding(
            rule_id="pg.internals.checkpoint_req_ratio",
            severity="warning",
            title=(
                f"Requested checkpoints are {pct} of total "
                f"({requested:,} of {total:,})"
            ),
            detail=(
                "More than half of all checkpoints are "
                "demand-driven (not scheduled). Possible causes: "
                "checkpoint_completion_target too low, "
                "max_wal_size too small for the write rate, or "
                "a bursty write workload. Raise max_wal_size and "
                "tune checkpoint_completion_target toward 0.9."
            ),
        )
    ]


@register("Internals & I/O Health")
def bgwriter_backend_writes_dominant(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when backend-direct buffer writes dominate bgwriter.

    Only meaningful pre-PG17 when pg_stat_bgwriter carries
    ``buffers_backend``; silent on PG17+ (those counters moved to
    pg_stat_io).
    """
    bg: PgBgwriter | None = parsed.get("pg.bgwriter")
    if bg is None:
        return []
    if bg.buffers_backend is None or bg.buffers_checkpoint is None:
        # PG17+ layout: bgwriter no longer tracks this.
        return []
    backend = bg.buffers_backend
    managed = (bg.buffers_checkpoint or 0) + bg.buffers_clean
    total = backend + managed
    if total == 0:
        return []
    # Warn when backends wrote more than half of all dirty buffers.
    if backend <= managed:
        return []
    pct = f"{backend / total * 100:.0f}%"
    return [
        Finding(
            rule_id="pg.internals.bgwriter_backend_dominant",
            severity="warning",
            title=(
                f"Backends wrote {pct} of dirty buffers "
                "directly (bgwriter underperforming)"
            ),
            detail=(
                "pg_stat_bgwriter.buffers_backend is larger than "
                "buffers_clean + buffers_checkpoint. Backends "
                "writing dirty buffers themselves stalls client "
                "queries. Tune bgwriter_lru_maxpages, "
                "bgwriter_delay, and bgwriter_lru_multiplier; "
                "also check for very bursty write patterns that "
                "can outrun any bgwriter configuration."
            ),
        )
    ]


@register("Internals & I/O Health")
def bgwriter_backend_fsync_nonzero(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when backends had to execute fsync themselves.

    Only meaningful pre-PG17; silent when the field is absent.
    """
    bg: PgBgwriter | None = parsed.get("pg.bgwriter")
    if bg is None or bg.buffers_backend_fsync is None:
        return []
    if bg.buffers_backend_fsync == 0:
        return []
    return [
        Finding(
            rule_id="pg.internals.bgwriter_backend_fsync",
            severity="warning",
            title=(
                f"Backends executed fsync directly "
                f"{bg.buffers_backend_fsync:,} time(s)"
            ),
            detail=(
                "pg_stat_bgwriter.buffers_backend_fsync > 0 "
                "means the bgwriter's fsync queue was full and "
                "backends had to call fsync themselves, adding "
                "latency to write transactions. Increase "
                "bgwriter_lru_maxpages or investigate storage "
                "I/O saturation."
            ),
        )
    ]
