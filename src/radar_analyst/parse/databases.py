"""Parsers for instance-level per-database views.

Covers the radar files that one query produces per row-per-database:

- ``postgresql/databases.tsv``          : pg_database rows
- ``postgresql/database_sizes.tsv``     : pg_database_size() per db
- ``postgresql/databases_tup.tsv``      : per-db tuple counters
  (``tup_returned / _fetched / _inserted / _updated / _deleted``).
  Deadlocks and temp_files live in the per-db ``stat_database``
  file, NOT here: radar's databases_tup.tsv query doesn't
  select them.
- ``postgresql/databases_checksums.tsv``: per-db checksum failures

Also ships a small generic helper ``count_tsv_rows`` used by the
orchestrator to aggregate per-db files (one per database, classified
as ``pg.db.*`` with ``dbname`` populated) into {dbname: rowcount}
summaries without writing a dedicated parser per kind.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.parse.coerce import (
    row_float,
    row_int,
)
from radar_analyst.parse.tsv import parse_tsv_bytes


_TEMPLATE_NAMES = frozenset({"template0", "template1"})


@dataclass(frozen=True)
class DatabaseInfo:
    """One pg_database row radar collected."""
    datname: str
    datistemplate: bool
    datallowconn: bool = True
    datconnlimit: int = -1
    # Wraparound tracking: present when radar's query supplies
    # the columns; ``None`` for archives from older radars.
    datfrozenxid: int | None = None
    frozenxid_age: int | None = None
    datminmxid: int | None = None
    minmxid_age: int | None = None


def _coerce_bool(value: str) -> bool:
    return value.strip().lower() in {"t", "true", "yes", "1"}


def _coerce_int_or_none(value: str) -> int | None:
    v = value.strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def parse_databases(data: bytes) -> list[DatabaseInfo]:
    """Parse ``postgresql/databases.tsv`` (radar's pg_database dump).

    Recent radar collectors select ``oid, datname, datdba,
    encoding, datcollate, datctype, datistemplate, datallowconn,
    datconnlimit, datfrozenxid, frozenxid_age, datminmxid,
    minmxid_age``. Older radars ship a narrower column set; this
    parser tolerates both: missing columns become defaults
    (templates fall back to name-based detection, ``datallowconn``
    defaults to ``True``, age columns become ``None``).
    """
    out: list[DatabaseInfo] = []
    t = parse_tsv_bytes(data)
    has_dat_template = "datistemplate" in t.columns
    has_dat_allow = "datallowconn" in t.columns
    has_dat_connlimit = "datconnlimit" in t.columns
    for r in t.rows:
        name = r.get("datname", "")
        if not name:
            continue
        if has_dat_template:
            is_template = _coerce_bool(r.get("datistemplate", ""))
        else:
            is_template = name in _TEMPLATE_NAMES
        allow_conn = (
            _coerce_bool(r.get("datallowconn", ""))
            if has_dat_allow
            else True
        )
        connlimit_raw = (
            r.get("datconnlimit", "") if has_dat_connlimit else ""
        )
        connlimit = _coerce_int_or_none(connlimit_raw)
        out.append(
            DatabaseInfo(
                datname=name,
                datistemplate=is_template,
                datallowconn=allow_conn,
                datconnlimit=(
                    connlimit if connlimit is not None else -1
                ),
                datfrozenxid=_coerce_int_or_none(
                    r.get("datfrozenxid", "")
                ),
                frozenxid_age=_coerce_int_or_none(
                    r.get("frozenxid_age", "")
                ),
                datminmxid=_coerce_int_or_none(
                    r.get("datminmxid", "")
                ),
                minmxid_age=_coerce_int_or_none(
                    r.get("minmxid_age", "")
                ),
            )
        )
    return out


def parse_database_sizes(data: bytes) -> dict[str, str]:
    """``datname → human-readable size string`` (from pg_size_pretty)."""
    out: dict[str, str] = {}
    t = parse_tsv_bytes(data)
    for r in t.rows:
        name = r.get("datname", "")
        size = r.get("size", "")
        if name and size:
            out[name] = size
    return out


@dataclass(frozen=True)
class DatabaseTupleStats:
    """Per-database tuple traffic counters."""
    datname: str
    tup_returned: int
    tup_fetched: int
    tup_inserted: int
    tup_updated: int
    tup_deleted: int


def parse_databases_tup(
    data: bytes,
) -> dict[str, DatabaseTupleStats]:
    """Per-db tuple counters from ``databases_tup.tsv``.

    Columns that radar actually ships: ``tup_returned``,
    ``tup_fetched``, ``tup_inserted``, ``tup_updated``,
    ``tup_deleted``. These drive "what is this database
    actually doing" context in the Databases tree (read-heavy
    vs write-heavy workload shape).
    """
    out: dict[str, DatabaseTupleStats] = {}
    t = parse_tsv_bytes(data)

    for r in t.rows:
        name = r.get("datname", "")
        if not name:
            continue
        out[name] = DatabaseTupleStats(
            datname=name,
            tup_returned=row_int(r, "tup_returned"),
            tup_fetched=row_int(r, "tup_fetched"),
            tup_inserted=row_int(r, "tup_inserted"),
            tup_updated=row_int(r, "tup_updated"),
            tup_deleted=row_int(r, "tup_deleted"),
        )
    return out


@dataclass(frozen=True)
class DatabaseXactStats:
    """Per-database commit/rollback counters."""
    datname: str
    xact_commit: int
    xact_rollback: int


def parse_databases_xact(
    data: bytes,
) -> dict[str, DatabaseXactStats]:
    """Per-db commit/rollback counters from ``databases_xact.tsv``."""
    out: dict[str, DatabaseXactStats] = {}
    t = parse_tsv_bytes(data)

    for r in t.rows:
        name = r.get("datname", "")
        if not name:
            continue
        out[name] = DatabaseXactStats(
            datname=name,
            xact_commit=row_int(r, "xact_commit"),
            xact_rollback=row_int(r, "xact_rollback"),
        )
    return out


@dataclass(frozen=True)
class DatabaseBlkStats:
    """Per-database block read/hit counters."""
    datname: str
    blks_read: int
    blks_hit: int
    blk_read_time: float
    blk_write_time: float


def parse_databases_blk(
    data: bytes,
) -> dict[str, DatabaseBlkStats]:
    """Per-db block I/O counters from ``databases_blk.tsv``.

    Cache-hit ratio derivation happens downstream in the
    summary builder: we just carry the raw counters here.
    """
    out: dict[str, DatabaseBlkStats] = {}
    t = parse_tsv_bytes(data)

    for r in t.rows:
        name = r.get("datname", "")
        if not name:
            continue
        out[name] = DatabaseBlkStats(
            datname=name,
            blks_read=row_int(r, "blks_read"),
            blks_hit=row_int(r, "blks_hit"),
            blk_read_time=row_float(r, "blk_read_time"),
            blk_write_time=row_float(r, "blk_write_time"),
        )
    return out


@dataclass(frozen=True)
class DatabaseConflictStats:
    """Per-database recovery-conflict counters."""
    datname: str
    confl_tablespace: int
    confl_lock: int
    confl_snapshot: int
    confl_bufferpin: int
    confl_deadlock: int


def parse_database_conflicts(
    data: bytes,
) -> dict[str, DatabaseConflictStats]:
    """Per-db replica-conflict counters from
    ``database_conflicts.tsv``.

    Non-zero ``confl_lock`` or ``confl_deadlock`` on a standby
    means queries are being cancelled to keep up with the
    primary: a critical DBA signal.
    """
    out: dict[str, DatabaseConflictStats] = {}
    t = parse_tsv_bytes(data)

    for r in t.rows:
        name = r.get("datname", "")
        if not name:
            continue
        out[name] = DatabaseConflictStats(
            datname=name,
            confl_tablespace=row_int(r, "confl_tablespace"),
            confl_lock=row_int(r, "confl_lock"),
            confl_snapshot=row_int(r, "confl_snapshot"),
            confl_bufferpin=row_int(r, "confl_bufferpin"),
            confl_deadlock=row_int(r, "confl_deadlock"),
        )
    return out


@dataclass(frozen=True)
class DbStatDatabase:
    """Per-db single-row stats from ``databases/{db}/stat_database.tsv``.

    Radar's per-db query selects ``datname, conflicts, deadlocks,
    temp_files, temp_bytes, stats_reset``. **This** is where
    deadlocks and temp_files live: the instance-level
    ``databases_tup.tsv`` does NOT carry those columns.
    """

    datname: str
    conflicts: int
    deadlocks: int
    temp_files: int
    temp_bytes: int
    stats_reset: str


def parse_db_stat_database(data: bytes) -> DbStatDatabase | None:
    """Parse one database's ``stat_database.tsv`` (single data row)."""
    t = parse_tsv_bytes(data)
    if not t.rows:
        return None
    r = t.rows[0]
    if not r.get("datname"):
        return None

    return DbStatDatabase(
        datname=r.get("datname", ""),
        conflicts=row_int(r, "conflicts"),
        deadlocks=row_int(r, "deadlocks"),
        temp_files=row_int(r, "temp_files"),
        temp_bytes=row_int(r, "temp_bytes"),
        stats_reset=r.get("stats_reset", "") or "",
    )


@dataclass(frozen=True)
class DatabaseChecksums:
    """Per-database checksum-failure counters."""
    datname: str
    checksum_failures: int
    checksum_last_failure: str


def parse_databases_checksums(
    data: bytes,
) -> dict[str, DatabaseChecksums]:
    """``databases_checksums.tsv`` → per-db checksum-failure facts.

    Any non-zero failure count is a critical-severity signal:
    data-page checksum mismatches mean storage corruption.
    """
    out: dict[str, DatabaseChecksums] = {}
    t = parse_tsv_bytes(data)

    for r in t.rows:
        name = r.get("datname", "")
        if not name:
            continue
        out[name] = DatabaseChecksums(
            datname=name,
            checksum_failures=row_int(r, "checksum_failures"),
            checksum_last_failure=(
                r.get("checksum_last_failure", "") or ""
            ),
        )
    return out


def count_tsv_rows(data: bytes) -> int:
    """How many data rows in this TSV (header excluded)."""
    return len(parse_tsv_bytes(data).rows)


# System schemas whose objects should not count as user objects.
_SYSTEM_SCHEMAS = frozenset({
    "pg_catalog", "information_schema", "pg_toast",
})


def parse_schema_oids(data: bytes) -> dict[str, str]:
    """Parse ``schemas.tsv`` → ``{oid_str: nspname}``."""
    if not data.strip():
        return {}
    t = parse_tsv_bytes(data)
    return {
        r.get("oid", ""): r.get("nspname", "")
        for r in t.rows
        if r.get("oid")
    }


def count_user_objects(
    data: bytes,
    schema_map: dict[str, str],
    *,
    kind: str,
) -> int:
    """Count non-system rows in a per-database TSV.

    Filtering strategy depends on the kind:

    - ``tables``, ``indexes``: have a ``schemaname`` column:
      exclude rows where schemaname ∈ system schemas.
    - ``funcs``, ``procs``, ``types``: have a namespace OID
      column (``pronamespace`` / ``typnamespace``): resolve
      via *schema_map* and exclude system schemas.
    - ``triggers``: have ``tgisinternal``: exclude internal.
    - Everything else: count all rows (no filter).
    """
    if not data.strip():
        return 0
    t = parse_tsv_bytes(data)
    if not t.rows:
        return 0

    if kind in ("tables", "indexes"):
        return sum(
            1 for r in t.rows
            if r.get("schemaname", "") not in _SYSTEM_SCHEMAS
        )

    if kind in ("funcs", "procs"):
        return sum(
            1 for r in t.rows
            if schema_map.get(
                r.get("pronamespace", ""), ""
            ) not in _SYSTEM_SCHEMAS
        )

    if kind == "types":
        # Exclude system schemas AND auto-generated types:
        # composite types (typtype='c') exist for every table,
        # and array types are base types (typtype='b'), so only
        # the kinds a DBA creates deliberately remain: domains,
        # enums, ranges, and multiranges.
        return sum(
            1 for r in t.rows
            if schema_map.get(
                r.get("typnamespace", ""), ""
            ) not in _SYSTEM_SCHEMAS
            and r.get("typtype") not in ("c", "b")
        )

    if kind == "triggers":
        return sum(
            1 for r in t.rows
            if r.get("tgisinternal", "").lower() != "true"
        )

    return len(t.rows)


def parse_extension_names(data: bytes) -> list[str]:
    """List of extension names from a ``pg_extension`` dump."""
    t = parse_tsv_bytes(data)
    return [
        r.get("extname", "")
        for r in t.rows
        if r.get("extname")
    ]
