"""Parsers for PostgreSQL progress and diagnostics files.

Covers:
- ``postgresql/tablespaces.tsv``
- ``postgresql/tablespace_sizes.tsv``
- ``postgresql/roles.tsv``
- ``postgresql/shmem_allocations.tsv``
- ``postgresql/stat_progress_*.tsv``
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from radar_analyst.parse.coerce import (
    as_bool,
)
from radar_analyst.parse.tsv import parse_tsv_bytes


# ---------------------------------------------------------------------------
# Tablespaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tablespace:
    """One row from ``postgresql/tablespaces.tsv``."""

    spcname: str
    spclocation: str  # empty for pg_default / pg_global


def parse_tablespaces(data: bytes) -> list[Tablespace] | None:
    """Parse ``postgresql/tablespaces.tsv``.

    Returns ``None`` for empty input, ``[]`` for header-only.
    """
    if not data.strip():
        return None
    table = parse_tsv_bytes(data)
    if not table.rows:
        return []
    out: list[Tablespace] = []
    for row in table.rows:
        spcname = row.get("spcname", "")
        spclocation = row.get("spclocation", "")
        out.append(Tablespace(
            spcname=spcname, spclocation=spclocation,
        ))
    return out


# ---------------------------------------------------------------------------
# Tablespace sizes
# ---------------------------------------------------------------------------


_SIZE_RE = re.compile(
    r"^\s*([\d.]+)\s*(bytes?|kB|MB|GB|TB)\s*$",
    re.IGNORECASE,
)
_SIZE_UNITS = {
    "bytes": 1,
    "byte": 1,
    "kb": 1024,
    "mb": 1024 * 1024,
    "gb": 1024 * 1024 * 1024,
    "tb": 1024 * 1024 * 1024 * 1024,
}


def _parse_pg_size_pretty(s: str) -> int | None:
    """Convert a ``pg_size_pretty`` string to bytes.

    Handles: ``"1190 MB"``, ``"604 kB"``, ``"2 GB"``, ``"512 bytes"``.
    Uses 1024-based multipliers (PostgreSQL's convention).
    Returns ``None`` for unrecognised formats.
    """
    m = _SIZE_RE.match(s)
    if m is None:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2).lower()
    multiplier = _SIZE_UNITS.get(unit)
    if multiplier is None:
        return None
    return int(value * multiplier)


@dataclass(frozen=True)
class TablespaceSize:
    """One row from ``postgresql/tablespace_sizes.tsv``."""

    spcname: str
    size_bytes: int | None  # None if size string not parseable


def parse_tablespace_sizes(data: bytes) -> list[TablespaceSize] | None:
    """Parse ``postgresql/tablespace_sizes.tsv``.

    Returns ``None`` for empty input, ``[]`` for header-only.
    """
    if not data.strip():
        return None
    table = parse_tsv_bytes(data)
    if not table.rows:
        return []
    out: list[TablespaceSize] = []
    for row in table.rows:
        spcname = row.get("spcname", "")
        size_str = row.get("size", "")
        size_bytes = _parse_pg_size_pretty(size_str)
        out.append(TablespaceSize(spcname=spcname, size_bytes=size_bytes))
    return out


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PgRole:
    """One row from ``postgresql/roles.tsv``."""

    rolname: str
    rolsuper: bool
    rolreplication: bool
    rolcanlogin: bool
    rolvaliduntil: str  # empty string = no expiry


def parse_roles(data: bytes) -> list[PgRole] | None:
    """Parse ``postgresql/roles.tsv``.

    Returns ``None`` for empty input, ``[]`` for header-only.
    """
    if not data.strip():
        return None
    table = parse_tsv_bytes(data)
    if not table.rows:
        return []
    out: list[PgRole] = []
    for row in table.rows:
        validuntil = row.get("rolvaliduntil", "")
        out.append(
            PgRole(
                rolname=row.get("rolname", ""),
                rolsuper=as_bool(row.get("rolsuper", "false")),
                rolreplication=as_bool(
                    row.get("rolreplication", "false")
                ),
                rolcanlogin=as_bool(row.get("rolcanlogin", "false")),
                rolvaliduntil=validuntil,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Shared memory allocations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShmemAllocation:
    """One row from ``postgresql/shmem_allocations.tsv``."""

    name: str
    size: int


def parse_shmem_allocations(
    data: bytes,
) -> list[ShmemAllocation] | None:
    """Parse ``postgresql/shmem_allocations.tsv``.

    Returns ``None`` for empty input, ``[]`` for header-only.
    """
    if not data.strip():
        return None
    table = parse_tsv_bytes(data)
    if not table.rows:
        return []
    out: list[ShmemAllocation] = []
    for row in table.rows:
        name = row.get("name", "")
        try:
            size = int(row.get("size", "0"))
        except ValueError:
            size = 0
        out.append(ShmemAllocation(name=name, size=size))
    return out


# ---------------------------------------------------------------------------
# stat_progress_* (generic handler for all variants)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProgressRow:
    """Minimal normalised row from any ``stat_progress_*`` TSV.

    All stat_progress files share ``pid``, ``datname``, and ``phase``.
    Block-progress columns (``blocks_done`` / ``blocks_total``) are
    populated from whichever columns are present:

    - vacuum: ``heap_blks_vacuumed`` / ``heap_blks_total``
    - create_index: ``blocks_done`` / ``blocks_total``
    - analyze: ``blocks_done`` / ``blocks_total``
    - copy / cluster / basebackup: ``blocks_done`` / ``blocks_total``
    """

    pid: int
    datname: str
    phase: str
    blocks_done: int | None
    blocks_total: int | None


def _int_col(row: dict[str, str], *keys: str) -> int | None:
    for key in keys:
        val = row.get(key, "")
        if val:
            try:
                return int(val)
            except ValueError:
                pass
    return None


def parse_stat_progress(data: bytes) -> list[ProgressRow] | None:
    """Parse any ``postgresql/stat_progress_*.tsv``.

    Returns ``None`` for empty input, ``[]`` for header-only.
    Handles all stat_progress variants through column-name fallback.
    """
    if not data.strip():
        return None
    table = parse_tsv_bytes(data)
    if not table.rows:
        return []
    out: list[ProgressRow] = []
    for row in table.rows:
        try:
            pid = int(row.get("pid", "0"))
        except ValueError:
            pid = 0
        datname = row.get("datname", "")
        phase = row.get("phase", "")
        blocks_done = _int_col(
            row, "blocks_done", "heap_blks_vacuumed"
        )
        blocks_total = _int_col(
            row, "blocks_total", "heap_blks_total"
        )
        out.append(
            ProgressRow(
                pid=pid,
                datname=datname,
                phase=phase,
                blocks_done=blocks_done,
                blocks_total=blocks_total,
            )
        )
    return out
