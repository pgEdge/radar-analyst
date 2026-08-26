"""Archive walk and parser dispatch.

Turns a radar zip into the ``parsed`` dict the rules and the
facts builders consume: one entry per file kind, with per-
database kinds nested as ``parsed[kind][dbname]``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from radar_analyst.archive.reader import (
    ClassifiedEntry,
    ZipSafetyError,
    open_entry,
    walk,
)
from radar_analyst.parse.databases import (
    count_tsv_rows,
    count_user_objects,
    parse_database_conflicts,
    parse_database_sizes,
    parse_databases,
    parse_databases_blk,
    parse_databases_checksums,
    parse_databases_tup,
    parse_databases_xact,
    parse_db_stat_database,
    parse_extension_names,
    parse_schema_oids,
)
from radar_analyst.parse.diskspace import parse_diskspace
from radar_analyst.parse.extensions import (
    parse_available_extensions,
)
from radar_analyst.parse.host_os import (
    parse_cgroup_memory_bytes,
    parse_dmesg,
    parse_iostat,
    parse_pressure,
)
from radar_analyst.parse.io_schedulers import parse_io_schedulers
from radar_analyst.parse.loadavg import parse_loadavg
from radar_analyst.parse.meminfo import parse_meminfo
from radar_analyst.parse.pg_activity import (
    parse_blocking_locks_count,
    parse_connection_summary,
    parse_prepared_xacts,
    parse_running_activity,
    parse_running_activity_maxage,
    parse_running_locks,
    parse_waits_sample,
)
from radar_analyst.parse.pg_conf import (
    parse_db_role_setting,
    parse_file_settings,
    parse_hba_file_rules,
)
from radar_analyst.parse.pg_db_bloat import (
    parse_db_bloat,
    parse_db_pgstattuple,
)
from radar_analyst.parse.pg_db_indexes import parse_db_indexes
from radar_analyst.parse.pg_db_repl_tables import (
    parse_publication_tables,
    parse_subscription_tables,
)
from radar_analyst.parse.pg_db_sequences import parse_db_sequences
from radar_analyst.parse.pg_db_tables import parse_db_tables
from radar_analyst.parse.pg_diagnostics import (
    parse_roles,
    parse_shmem_allocations,
    parse_stat_progress,
    parse_tablespace_sizes,
    parse_tablespaces,
)
from radar_analyst.parse.pg_internals import (
    parse_bgwriter,
    parse_checkpointer,
    parse_stat_io,
    parse_stat_slru,
    parse_stat_wal,
)
from radar_analyst.parse.pg_settings import (
    parse_pg_settings,
)
from radar_analyst.parse.pg_stat_replication_slots import (
    parse_stat_replication_slots,
)
from radar_analyst.parse.pg_stat_ssl import parse_stat_ssl
from radar_analyst.parse.pg_stat_statements import parse_stat_statements
from radar_analyst.parse.pg_version import (
    parse_version,
)
from radar_analyst.parse.pg_wal import (
    parse_archiver,
    parse_replication,
    parse_replication_origins,
    parse_replication_slots,
    parse_subscriptions,
    parse_wal_position,
    parse_wal_receiver,
)
from radar_analyst.parse.postmaster_start_time import (
    parse_postmaster_start_time,
)
from radar_analyst.parse.radar_version import parse_radar_meta
from radar_analyst.parse.swaps import parse_swaps
from radar_analyst.parse.sysctl import parse_sysctl
from radar_analyst.parse.system_facts import (
    parse_hostname,
    parse_hypervisor,
    parse_lscpu,
    parse_os_release,
    parse_uname,
    parse_uptime,
)
from radar_analyst.parse.thp import parse_thp


_logger = logging.getLogger(__name__)


_SMALL_ENTRY_BYTES: int = 1 * 1024 * 1024  # 1 MiB


def _strip_text(data: bytes) -> str | None:
    s = data.decode("utf-8", errors="replace").strip()
    return s or None


_PARSERS: dict[str, Callable[[bytes], Any]] = {
    "pg.version": parse_version,
    "pg.settings": parse_pg_settings,
    "sys.sysctl": parse_sysctl,
    "sys.proc.meminfo": parse_meminfo,
    "sys.proc.loadavg": parse_loadavg,
    "sys.diskspace": parse_diskspace,
    "radar.meta": parse_radar_meta,
    "sys.hostname": parse_hostname,
    "sys.hypervisor": parse_hypervisor,
    "pg.postmaster_start_time": parse_postmaster_start_time,
    "sys.os_release": parse_os_release,
    "sys.uname": parse_uname,
    "sys.lscpu": parse_lscpu,
    "sys.proc.uptime": parse_uptime,
    "sys.proc.swaps": parse_swaps,
    "sys.sys.transparent_hugepage": parse_thp,
    "sys.sys.cpu_scaling_governor": _strip_text,
    # PSI pressure files.
    "sys.proc.pressure_cpu": parse_pressure,
    "sys.proc.pressure_io": parse_pressure,
    "sys.proc.pressure_memory": parse_pressure,
    # iostat device utilisation.
    "sys.iostat": parse_iostat,
    "sys.io_schedulers": parse_io_schedulers,
    # cgroup v2 memory limits (single-line byte values).
    "sys.cgroup.memory_current": parse_cgroup_memory_bytes,
    "sys.cgroup.memory_max": parse_cgroup_memory_bytes,
    # dmesg: kernel log for OOM and I/O errors.
    "sys.dmesg": parse_dmesg,
    "sys.dmesg_t": parse_dmesg,
    # PostgreSQL runtime state.
    "pg.running_activity": parse_running_activity,
    "pg.blocking_locks": parse_blocking_locks_count,
    "pg.running_activity_maxage": parse_running_activity_maxage,
    "pg.waits_sample": parse_waits_sample,
    "pg.connection_summary": parse_connection_summary,
    "pg.running_locks": parse_running_locks,
    # prepared_xacts: no snapshot "now" is parsed from radar
    # zips, so age-of-oldest stays None. Count is what the rule
    # fires on.
    "pg.prepared_xacts": lambda data: parse_prepared_xacts(
        data, now_iso=None
    ),
    "pg.archiver": parse_archiver,
    "pg.replication_slots": parse_replication_slots,
    "pg.replication": parse_replication,
    "pg.wal_position": parse_wal_position,
    "pg.wal_receiver": parse_wal_receiver,
    "pg.subscriptions": parse_subscriptions,
    "pg.replication_origin": parse_replication_origins,
    # Internals & I/O Health sources.
    "pg.bgwriter": parse_bgwriter,
    "pg.checkpointer": parse_checkpointer,
    "pg.stat_statements.calls": parse_stat_statements,
    "pg.stat_statements.max_time": parse_stat_statements,
    "pg.stat_statements.total_time": parse_stat_statements,
    "pg.stat_wal": parse_stat_wal,
    "pg.stat_io": parse_stat_io,
    "pg.stat_slru": parse_stat_slru,
    # PostgreSQL per-database lists (instance-level, one row/db).
    "pg.databases": parse_databases,
    "pg.database_sizes": parse_database_sizes,
    "pg.databases_checksums": parse_databases_checksums,
    "pg.databases_xact": parse_databases_xact,
    "pg.databases_blk": parse_databases_blk,
    "pg.databases_tup": parse_databases_tup,
    "pg.database_conflicts": parse_database_conflicts,
    "pg.available_extensions": parse_available_extensions,
    "pg.stat_ssl": parse_stat_ssl,
    "pg.stat_replication_slots": parse_stat_replication_slots,
    # PostgreSQL configuration file data.
    "pg.file_settings": parse_file_settings,
    "pg.hba_file_rules": parse_hba_file_rules,
    "pg.db_role_setting": parse_db_role_setting,
    "pg.conf.postgresql_auto": _strip_text,
    "pg.conf.postgresql": _strip_text,
    "pg.conf.pg_hba": _strip_text,
    "pg.conf.pg_ident": _strip_text,
    # PostgreSQL diagnostics: roles, tablespaces, shmem, progress.
    "pg.tablespaces": parse_tablespaces,
    "pg.tablespace_sizes": parse_tablespace_sizes,
    "pg.roles": parse_roles,
    "pg.shmem_allocations": parse_shmem_allocations,
    "pg.stat_progress_vacuum": parse_stat_progress,
    "pg.stat_progress_analyze": parse_stat_progress,
    "pg.stat_progress_create_index": parse_stat_progress,
    "pg.stat_progress_copy": parse_stat_progress,
    "pg.stat_progress_cluster": parse_stat_progress,
    "pg.stat_progress_basebackup": parse_stat_progress,
    # Cloud/container identity: each of these is a one-line
    # file. Read them with the trivial strip-text reader.
    "sys.cloud.sys_vendor": _strip_text,
    "sys.cloud.bios_vendor": _strip_text,
    "sys.cloud.product_name": _strip_text,
    "sys.container.k8s_namespace": _strip_text,
}


_CONTAINER_SIGNALS = frozenset(
    {
        "sys.container.dockerenv",
        "sys.container.environment",
        "sys.container.k8s_namespace",
    }
)

# DMI ``sys_vendor`` strings that actually denote a cloud provider.
# A laptop or bare-metal server reports "LENOVO", "Dell Inc.",
# "ASUS", "Supermicro" etc.; those should NOT be surfaced as
# ``cloud_provider`` in the snapshot.
_CLOUD_VENDORS = (
    "amazon",
    "ec2",
    "google",
    "gcp",
    "microsoft",
    "azure",
    "oracle",
    "ovh",
    "hetzner",
    "digitalocean",
    "digital ocean",
    "linode",
    "alibaba",
    "tencent",
    "vultr",
    "scaleway",
    "ibm cloud",
)


def _derive_cloud_provider(
    parsed: dict[str, Any],
) -> str:
    """Return the cloud provider name, or '' if the host is not cloud.

    Cross-references the DMI ``sys_vendor`` and ``product_name``
    against a short whitelist of known cloud-operator strings so a
    physical laptop reporting "LENOVO" doesn't get misclassified.
    """
    for key in (
        "sys.cloud.sys_vendor",
        "sys.cloud.product_name",
        "sys.cloud.bios_vendor",
    ):
        value = parsed.get(key) or ""
        lower = value.lower()
        for needle in _CLOUD_VENDORS:
            if needle in lower:
                return value
    return ""


# Kinds whose counts must exclude system schemas. Note:
# ``pg.db.tables`` and ``pg.db.indexes`` are handled separately
# via ``_PER_DB_PARSERS`` (full parse into TablesPerDb /
# IndexesPerDb) since the rule layer needs the rows, not just a
# count. The summary builder derives those counts via ``len()``.
_SCHEMA_FILTERED_KINDS: dict[str, str] = {
    "pg.db.triggers": "triggers",
    "pg.db.funcs": "funcs",
    "pg.db.procs": "procs",
    "pg.db.types": "types",
}

# Kinds counted without filtering (no system objects). Note:
# ``pg.db.publication_tables`` and ``pg.db.subscription_tables``
# are full-parsed via ``_PER_DB_PARSERS`` so the Replication
# facts builder can list table membership.
_UNFILTERED_COUNT_KINDS = frozenset({
    "pg.db.partitioned_tables",
    "pg.db.partitions",
    "pg.db.publications",
})

# Per-db parsers are dispatched differently: their result is
# stored as ``parsed[kind][dbname] = value``, keyed first by kind
# and then by database name.
_PER_DB_PARSERS: dict[str, Callable[[bytes], Any]] = {
    "pg.db.bloat": parse_db_bloat,
    "pg.db.extensions": parse_extension_names,
    "pg.db.indexes": parse_db_indexes,
    "pg.db.pgstattuple": parse_db_pgstattuple,
    "pg.db.publication_tables": parse_publication_tables,
    "pg.db.sequences": parse_db_sequences,
    "pg.db.stat_database": parse_db_stat_database,
    "pg.db.subscription_tables": parse_subscription_tables,
    "pg.db.tables": parse_db_tables,
}


def _build_inventory(
    classified: list[ClassifiedEntry], unknown: list[str]
) -> list[dict[str, Any]]:
    """JSON-ready inventory rows for every archive entry."""
    inventory: list[dict[str, Any]] = [
        {
            "path": e.path,
            "kind": e.kind,
            "dbname": e.dbname,
            "size": e.size,
        }
        for e in classified
    ]
    inventory.extend(
        {
            "path": path,
            "kind": None,
            "dbname": None,
            "size": None,
        }
        for path in unknown
    )
    return inventory


def _read_small_entry(
    zip_path: Path, path: str
) -> bytes | None:
    """Read one entry under the small-entry cap, or None.

    Oversize and unreadable entries are logged and skipped, so
    their kinds simply stay absent from ``parsed``.
    """
    try:
        with open_entry(
            zip_path, path, max_bytes=_SMALL_ENTRY_BYTES
        ) as fh:
            data = fh.read(_SMALL_ENTRY_BYTES + 1)
    except ZipSafetyError:
        _logger.warning(
            "entry %s exceeds small-entry cap (%d), skipping; "
            "use a streaming parser if this is expected",
            path,
            _SMALL_ENTRY_BYTES,
        )
        return None
    except Exception as e:
        _logger.warning("failed to read %s: %s", path, e)
        return None
    if len(data) > _SMALL_ENTRY_BYTES:
        _logger.warning(
            "entry %s larger than small-entry cap, skipping",
            path,
        )
        return None
    return data


def _is_per_db(entry: ClassifiedEntry) -> bool:
    """Whether *entry* is parsed per database."""
    return entry.dbname is not None and (
        entry.kind in _PER_DB_PARSERS
        or entry.kind in _SCHEMA_FILTERED_KINDS
        or entry.kind in _UNFILTERED_COUNT_KINDS
        or entry.kind == "pg.db.schemas"
    )


def _parse_per_db_entry(
    entry: ClassifiedEntry,
    data: bytes,
    parsed: dict[str, Any],
    schema_maps: dict[str, dict[str, str]],
    deferred: list[tuple[str, str, bytes]],
) -> None:
    """Dispatch one per-database entry into *parsed*.

    ``schemas.tsv`` feeds *schema_maps*; schema-filtered kinds
    are deferred until every schema map has been collected.
    """
    dbname = entry.dbname
    assert dbname is not None
    if entry.kind == "pg.db.schemas":
        schema_maps[dbname] = parse_schema_oids(data)
        return
    if entry.kind in _SCHEMA_FILTERED_KINDS:
        deferred.append((entry.kind, dbname, data))
        return
    if entry.kind in _UNFILTERED_COUNT_KINDS:
        parsed.setdefault(entry.kind, {})[dbname] = (
            count_tsv_rows(data)
        )
        return
    fn = _PER_DB_PARSERS[entry.kind]
    try:
        value = fn(data)
    except Exception as e:
        _logger.warning(
            "per-db parser for %s failed: %s", entry.path, e
        )
        return
    parsed.setdefault(entry.kind, {})[dbname] = value


def _parse_fixed_entry(
    zip_path: Path,
    entry: ClassifiedEntry,
    parsed: dict[str, Any],
) -> None:
    """Parse one fixed-kind entry into *parsed*, when a parser
    is registered for its kind.
    """
    parser = _PARSERS.get(entry.kind)
    if parser is None:
        return
    data = _read_small_entry(zip_path, entry.path)
    if data is None:
        return
    try:
        value = parser(data)
    except Exception as e:
        _logger.warning(
            "parser for %s failed: %s", entry.kind, e
        )
        return
    if value is not None:
        parsed[entry.kind] = value


def _resolve_deferred_counts(
    deferred: list[tuple[str, str, bytes]],
    schema_maps: dict[str, dict[str, str]],
    parsed: dict[str, Any],
) -> None:
    """Count schema-filtered kinds once schema maps exist."""
    for kind, dbname, data in deferred:
        obj_kind = _SCHEMA_FILTERED_KINDS[kind]
        schema_map = schema_maps.get(dbname, {})
        try:
            count = count_user_objects(
                data, schema_map, kind=obj_kind
            )
        except Exception as e:
            _logger.warning(
                "count_user_objects for %s/%s failed: %s",
                kind,
                dbname,
                e,
            )
            continue
        parsed.setdefault(kind, {})[dbname] = count


def read_and_parse(zip_path: Path) -> tuple[
    dict[str, Any],
    list[str],
    list[str],
    set[str],
    list[dict[str, Any]],
]:
    """Walk *zip_path* and return parsed/inventory tuple.

    Tuple shape: ``(parsed, unknown, parsed_kinds, present,
    inventory)``.

    - ``parsed`` maps kind string to parsed value for every entry
      we actually decoded.
    - ``unknown`` is the coverage-canary list of archive paths
      that don't match any classification.
    - ``parsed_kinds`` is a sorted list of the kinds that had data.
    - ``present`` is the set of ALL classified kinds in the archive
      (including those without a registered parser). Used for
      "is the host containerised?"-style derivations without
      needing to decode each file.
    - ``inventory`` is the JSON-serialisable list of every entry
      found in the archive (classified and unknown), suitable for
      :func:`set_archive_files`. Each item: ``{path, kind,
      dbname, size}`` with ``kind=None`` for unknown entries.
    """
    classified, unknown = walk(zip_path)
    present = {e.kind for e in classified}
    inventory = _build_inventory(classified, unknown)

    parsed: dict[str, Any] = {}
    schema_maps: dict[str, dict[str, str]] = {}
    deferred: list[tuple[str, str, bytes]] = []
    for entry in classified:
        if _is_per_db(entry):
            data = _read_small_entry(zip_path, entry.path)
            if data is not None:
                _parse_per_db_entry(
                    entry, data, parsed, schema_maps, deferred
                )
        else:
            _parse_fixed_entry(zip_path, entry, parsed)

    _resolve_deferred_counts(deferred, schema_maps, parsed)

    # Containerisation and cloud provider are derived once here
    # so rules and facts builders read one consistent answer.
    parsed["sys.is_container"] = bool(
        present & _CONTAINER_SIGNALS
    )
    parsed["sys.cloud_provider"] = _derive_cloud_provider(
        parsed
    )

    return (
        parsed, unknown, sorted(parsed.keys()), present,
        inventory,
    )
