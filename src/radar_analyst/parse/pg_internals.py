"""Parsers for Internals & I/O Health sources.

Covers:
- ``postgresql/bgwriter.tsv``   : pg_stat_bgwriter (pre-PG17:
  checkpoint + bgwriter fields; PG17+: bgwriter-only fields)
- ``postgresql/checkpointer.tsv``: pg_stat_checkpointer (PG17+)
- ``postgresql/stat_wal.tsv``   : pg_stat_wal
- ``postgresql/stat_io.tsv``    : pg_stat_io (PG16+)
- ``postgresql/stat_slru.tsv``  : pg_stat_slru

All files are single-row (bgwriter, checkpointer, stat_wal) or
multi-row (stat_io, stat_slru) TSVs.

PG version sensitivity:
- ``pg_stat_bgwriter`` was split in PG17: checkpoint counters
  moved to ``pg_stat_checkpointer``; backend buffer write counters
  moved to ``pg_stat_io``. The parser handles both layouts
  gracefully by treating absent columns as ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from radar_analyst.parse.coerce import (
    as_datetime_or_none,
    as_float_or_none,
    as_int,
    as_int_or_none,
)
from radar_analyst.parse.tsv import parse_tsv_bytes


# ---------------------------------------------------------------------------
# pg_stat_bgwriter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PgBgwriter:
    """Parsed row from pg_stat_bgwriter.

    Pre-PG17 the table carried both checkpoint and bgwriter fields.
    PG17+ moved checkpoints to pg_stat_checkpointer and backend
    buffer writes to pg_stat_io; those fields are ``None`` here
    when the column is absent.
    """

    # Checkpoint fields (pre-PG17 only; None on PG17+)
    checkpoints_timed: int | None
    checkpoints_req: int | None
    buffers_checkpoint: int | None
    # Bgwriter fields (present in all versions)
    buffers_clean: int
    maxwritten_clean: int
    buffers_alloc: int
    # Backend buffer write fields (pre-PG17 only; None on PG17+)
    buffers_backend: int | None
    buffers_backend_fsync: int | None
    # Cluster-wide stats reset (None if absent/unparseable).
    stats_reset: datetime | None


def parse_bgwriter(data: bytes) -> PgBgwriter | None:
    """Parse ``postgresql/bgwriter.tsv`` → *PgBgwriter*.

    Returns ``None`` for empty or header-only input.
    """
    table = parse_tsv_bytes(data)
    if not table.rows:
        return None
    row = table.rows[0]
    return PgBgwriter(
        checkpoints_timed=as_int_or_none(row.get("checkpoints_timed")),
        checkpoints_req=as_int_or_none(row.get("checkpoints_req")),
        buffers_checkpoint=as_int_or_none(
            row.get("buffers_checkpoint")
        ),
        buffers_clean=as_int(row.get("buffers_clean")),
        maxwritten_clean=as_int(
            row.get("maxwritten_clean")
        ),
        buffers_alloc=as_int(row.get("buffers_alloc")),
        buffers_backend=as_int_or_none(row.get("buffers_backend")),
        buffers_backend_fsync=as_int_or_none(
            row.get("buffers_backend_fsync")
        ),
        stats_reset=as_datetime_or_none(row.get("stats_reset")),
    )


# ---------------------------------------------------------------------------
# pg_stat_checkpointer (PG17+)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PgCheckpointer:
    """Parsed row from pg_stat_checkpointer (PG17+)."""

    num_timed: int
    num_requested: int
    write_time: float
    sync_time: float
    buffers_written: int


def parse_checkpointer(data: bytes) -> PgCheckpointer | None:
    """Parse ``postgresql/checkpointer.tsv`` → *PgCheckpointer*.

    Returns ``None`` for empty or header-only input.
    """
    table = parse_tsv_bytes(data)
    if not table.rows:
        return None
    row = table.rows[0]
    return PgCheckpointer(
        num_timed=as_int(row.get("num_timed")),
        num_requested=as_int(row.get("num_requested")),
        write_time=as_float_or_none(row.get("write_time")) or 0.0,
        sync_time=as_float_or_none(row.get("sync_time")) or 0.0,
        buffers_written=as_int(row.get("buffers_written")),
    )


# ---------------------------------------------------------------------------
# pg_stat_wal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PgStatWal:
    """Parsed row from pg_stat_wal."""

    wal_records: int
    wal_fpi: int
    wal_bytes: int
    wal_buffers_full: int
    wal_write: int
    wal_sync: int


def parse_stat_wal(data: bytes) -> PgStatWal | None:
    """Parse ``postgresql/stat_wal.tsv`` → *PgStatWal*.

    Returns ``None`` for empty or header-only input.
    """
    table = parse_tsv_bytes(data)
    if not table.rows:
        return None
    row = table.rows[0]
    return PgStatWal(
        wal_records=as_int(row.get("wal_records")),
        wal_fpi=as_int(row.get("wal_fpi")),
        wal_bytes=as_int(row.get("wal_bytes")),
        wal_buffers_full=as_int(
            row.get("wal_buffers_full")
        ),
        wal_write=as_int(row.get("wal_write")),
        wal_sync=as_int(row.get("wal_sync")),
    )


# ---------------------------------------------------------------------------
# pg_stat_io (PG16+)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PgStatIoRow:
    """One row from pg_stat_io."""

    backend_type: str
    object: str
    context: str
    reads: int
    writes: int
    writebacks: int
    hits: int
    evictions: int
    reuses: int
    fsyncs: int


def parse_stat_io(data: bytes) -> list[PgStatIoRow] | None:
    """Parse ``postgresql/stat_io.tsv`` → list of *PgStatIoRow*.

    Returns ``None`` for completely empty input; returns ``[]`` for
    a header-only file (no data rows). This lets the orchestrator
    distinguish "file absent" from "file present but empty".
    """
    raw = data.strip()
    if not raw:
        return None
    table = parse_tsv_bytes(data)
    out: list[PgStatIoRow] = []
    for row in table.rows:
        out.append(
            PgStatIoRow(
                backend_type=row.get("backend_type") or "",
                object=row.get("object") or "",
                context=row.get("context") or "",
                reads=as_int(row.get("reads")),
                writes=as_int(row.get("writes")),
                writebacks=as_int(row.get("writebacks")),
                hits=as_int(row.get("hits")),
                evictions=as_int(row.get("evictions")),
                reuses=as_int(row.get("reuses")),
                fsyncs=as_int(row.get("fsyncs")),
            )
        )
    return out


# ---------------------------------------------------------------------------
# pg_stat_slru
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PgStatSlruRow:
    """One row from pg_stat_slru."""

    name: str
    blks_zeroed: int
    blks_hit: int
    blks_read: int
    blks_written: int
    flushes: int
    truncates: int


def parse_stat_slru(data: bytes) -> list[PgStatSlruRow] | None:
    """Parse ``postgresql/stat_slru.tsv`` → list of *PgStatSlruRow*.

    Returns ``None`` for completely empty input; ``[]`` for
    header-only (no data rows).
    """
    raw = data.strip()
    if not raw:
        return None
    table = parse_tsv_bytes(data)
    out: list[PgStatSlruRow] = []
    for row in table.rows:
        out.append(
            PgStatSlruRow(
                name=row.get("name") or "",
                blks_zeroed=as_int(row.get("blks_zeroed")),
                blks_hit=as_int(row.get("blks_hit")),
                blks_read=as_int(row.get("blks_read")),
                blks_written=as_int(
                    row.get("blks_written")
                ),
                flushes=as_int(row.get("flushes")),
                truncates=as_int(row.get("truncates")),
            )
        )
    return out
