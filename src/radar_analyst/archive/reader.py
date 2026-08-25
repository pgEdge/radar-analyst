"""Walk a radar zip and classify each entry to a known file-kind.

The classification is derived purely from the archive path. Unknown
paths are collected into a coverage-canary list so radar adding a new
collector cannot silently drop out of analysis.

Kind strings (stable):
- ``pg.*``: PostgreSQL-instance files under ``postgresql/``
- ``pg.conf.*``: raw PostgreSQL config files
- ``pg.db.*``: per-database files under ``databases/{db}/``
  (``dbname`` is populated)
- ``pg_statviz.*``: per-database pg_statviz time-series under
  ``pg_statviz/{db}/`` (``dbname`` populated)
- ``sys.*``: system files under ``system/``

Safety:
- ``list_entries`` reads the central directory only: no decompression.
- Zip-bomb limits (``MAX_ENTRIES``, ``MAX_ENTRY_SIZE_BYTES``,
  ``MAX_TOTAL_UNCOMPRESSED_BYTES``) reject archives whose declared
  uncompressed size or entry count exceeds what a real radar collection
  could plausibly produce.
- ``open_entry`` opens a single entry via ``ZipFile.open()`` behind a
  reader with a hard byte cap, so a lying central directory cannot
  blow memory: reads stop at ``max_bytes + 1`` and raise.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, cast

# Real radar archives ship ~150–250 entries for a small instance,
# scaling with database count: per-db data is 17 files and pg_statviz
# adds 11 more, so 100 databases ≈ 2.9k entries and 500 databases ≈
# 14k. The ``MAX_ENTRIES`` cap here is not a business-logic limit on
# database count; it's a defense-in-depth bound on how much
# Python-object state we'll let ``zipfile`` allocate while reading
# the central directory (each ``ZipInfo`` is ~200 bytes plus the
# entry path). 100 000 entries = ~20–30 MB of ZipInfo state, which
# accommodates a 3500-database radar host and still rejects a
# million-entry DoS archive. Total uncompressed and per-entry caps
# are the load-bearing limits; raising this one further has no
# downside beyond that memory ceiling.
#
# Observed: 228 entries / 789 MiB total / 186 MiB largest
# (pg_statviz db.tsv) on a real pg_statviz-heavy sample.
MAX_ENTRIES: int = 100_000
MAX_ENTRY_SIZE_BYTES: int = 500 * 1024 * 1024  # 500 MiB
MAX_TOTAL_UNCOMPRESSED_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GiB


class ZipSafetyError(Exception):
    """Raised when an archive's declared or actual size breaks a limit."""


@dataclass(frozen=True)
class ArchiveEntry:
    """One zip entry: path and declared size."""
    path: str
    size: int


@dataclass(frozen=True)
class ClassifiedEntry:
    """A classified entry: path, size, kind, database name."""
    path: str
    size: int
    kind: str
    dbname: str | None


# Fixed archive paths → kind strings. Sourced from radar's DATA.md;
# kept comprehensive so that file-kinds without a parser are still
# classified (the coverage canary is about *unknown* paths, not about
# missing parsers).
_FIXED: dict[str, str] = {
    # Zip-root metadata: radar 0.5.0+ writes ``radar.out`` with
    # ``version:`` / ``commit:`` lines identifying the producer.
    "radar.out": "radar.meta",

    # PostgreSQL instance (postgresql/)
    "postgresql/archiver.tsv": "pg.archiver",
    "postgresql/available_extensions.tsv":
        "pg.available_extensions",
    "postgresql/bgwriter.tsv": "pg.bgwriter",
    "postgresql/blocking_locks.tsv": "pg.blocking_locks",
    "postgresql/checkpointer.tsv": "pg.checkpointer",
    "postgresql/configuration.tsv": "pg.settings",
    "postgresql/connection_summary.tsv": "pg.connection_summary",
    "postgresql/database_conflicts.tsv": "pg.database_conflicts",
    "postgresql/database_sizes.tsv": "pg.database_sizes",
    "postgresql/databases.tsv": "pg.databases",
    "postgresql/databases_blk.tsv": "pg.databases_blk",
    "postgresql/databases_checksums.tsv": "pg.databases_checksums",
    "postgresql/databases_tup.tsv": "pg.databases_tup",
    "postgresql/databases_xact.tsv": "pg.databases_xact",
    "postgresql/db_role_setting.tsv": "pg.db_role_setting",
    "postgresql/file_settings.tsv": "pg.file_settings",
    "postgresql/pg_hba.conf": "pg.conf.pg_hba",
    "postgresql/pg_hba_file_rules.tsv": "pg.hba_file_rules",
    "postgresql/pg_ident.conf": "pg.conf.pg_ident",
    "postgresql/postgresql.auto.conf": "pg.conf.postgresql_auto",
    "postgresql/postgresql.conf": "pg.conf.postgresql",
    "postgresql/postmaster_start_time.tsv":
        "pg.postmaster_start_time",
    "postgresql/prepared_xacts.tsv": "pg.prepared_xacts",
    "postgresql/recovery.conf": "pg.conf.recovery",
    "postgresql/recovery.done": "pg.recovery_done",
    "postgresql/replication.tsv": "pg.replication",
    "postgresql/replication_origin.tsv": "pg.replication_origin",
    "postgresql/replication_slots.tsv": "pg.replication_slots",
    "postgresql/roles.tsv": "pg.roles",
    "postgresql/running_activity.tsv": "pg.running_activity",
    "postgresql/running_activity_maxage.tsv":
        "pg.running_activity_maxage",
    "postgresql/running_locks.tsv": "pg.running_locks",
    "postgresql/shmem_allocations.tsv": "pg.shmem_allocations",
    "postgresql/stat_io.tsv": "pg.stat_io",
    "postgresql/stat_progress_analyze.tsv":
        "pg.stat_progress_analyze",
    "postgresql/stat_progress_basebackup.tsv":
        "pg.stat_progress_basebackup",
    "postgresql/stat_progress_cluster.tsv":
        "pg.stat_progress_cluster",
    "postgresql/stat_progress_copy.tsv": "pg.stat_progress_copy",
    "postgresql/stat_progress_create_index.tsv":
        "pg.stat_progress_create_index",
    "postgresql/stat_progress_vacuum.tsv":
        "pg.stat_progress_vacuum",
    "postgresql/stat_replication_slots.tsv":
        "pg.stat_replication_slots",
    "postgresql/stat_slru.tsv": "pg.stat_slru",
    "postgresql/stat_ssl.tsv": "pg.stat_ssl",
    "postgresql/stat_statements_calls.tsv":
        "pg.stat_statements.calls",
    "postgresql/stat_statements_max_time.tsv":
        "pg.stat_statements.max_time",
    "postgresql/stat_statements_total_time.tsv":
        "pg.stat_statements.total_time",
    "postgresql/stat_wal.tsv": "pg.stat_wal",
    "postgresql/subscriptions.tsv": "pg.subscriptions",
    "postgresql/tablespace_sizes.tsv": "pg.tablespace_sizes",
    "postgresql/tablespaces.tsv": "pg.tablespaces",
    "postgresql/version.tsv": "pg.version",
    "postgresql/waits_sample.tsv": "pg.waits_sample",
    "postgresql/wal_position.tsv": "pg.wal_position",
    "postgresql/wal_receiver.tsv": "pg.wal_receiver",

    # System: cross-platform and Linux/macOS mixed. All are
    # classified even when no parser exists for the kind.
    "system/diskspace.out": "sys.diskspace",
    "system/dmesg.out": "sys.dmesg",
    "system/dmesg_t.out": "sys.dmesg_t",
    "system/fstab.out": "sys.fstab",
    "system/free.out": "sys.free",
    "system/hostname.out": "sys.hostname",
    "system/hosts.out": "sys.hosts",
    "system/hypervisor.out": "sys.hypervisor",
    "system/ifconfig.out": "sys.ifconfig",
    "system/interfaces.out": "sys.interfaces",
    "system/io_queue_depth.out": "sys.io_queue_depth",
    "system/io_schedulers.out": "sys.io_schedulers",
    "system/iostat.out": "sys.iostat",
    "system/ip_addr.out": "sys.ip_addr",
    "system/ipcs.out": "sys.ipcs",
    "system/limits.out": "sys.limits",
    "system/locale.out": "sys.locale",
    "system/locale_all.out": "sys.locale_all",
    "system/locale_conf.out": "sys.locale_conf",
    "system/localectl.out": "sys.localectl",
    "system/lsblk.out": "sys.lsblk",
    "system/lscpu.out": "sys.lscpu",
    "system/lsdevmapper.out": "sys.lsdevmapper",
    "system/lsmod.out": "sys.lsmod",
    "system/lspci.out": "sys.lspci",
    "system/machine_id.out": "sys.machine_id",
    "system/meminfo.out": "sys.meminfo",
    "system/mount.out": "sys.mount",
    "system/mpstat.out": "sys.mpstat",
    "system/netstat_stats.out": "sys.netstat_stats",
    "system/nfsiostat.out": "sys.nfsiostat",
    "system/numactl.out": "sys.numactl",
    "system/numastat.out": "sys.numastat",
    "system/os_release.out": "sys.os_release",
    "system/ps.out": "sys.ps",
    "system/read_ahead.out": "sys.read_ahead",
    "system/resolv_conf.out": "sys.resolv_conf",
    "system/sar.out": "sys.sar",
    "system/sestatus.out": "sys.sestatus",
    "system/ss_listeners.out": "sys.ss_listeners",
    "system/ss_summary.out": "sys.ss_summary",
    "system/sysctl.out": "sys.sysctl",
    "system/sysctl.conf": "sys.sysctl_conf",
    "system/timedatectl.out": "sys.timedatectl",
    "system/top.out": "sys.top",
    "system/uname.out": "sys.uname",
    "system/vmstat-command.out": "sys.vmstat_command",

    # /proc/*
    "system/proc/cpuinfo.out": "sys.proc.cpuinfo",
    "system/proc/diskstats.out": "sys.proc.diskstats",
    "system/proc/loadavg.out": "sys.proc.loadavg",
    "system/proc/meminfo.out": "sys.proc.meminfo",
    "system/proc/mounts.out": "sys.proc.mounts",
    "system/proc/pressure_cpu.out": "sys.proc.pressure_cpu",
    "system/proc/pressure_io.out": "sys.proc.pressure_io",
    "system/proc/pressure_memory.out":
        "sys.proc.pressure_memory",
    "system/proc/swaps.out": "sys.proc.swaps",
    "system/proc/uptime.out": "sys.proc.uptime",
    "system/proc/vmstat.out": "sys.proc.vmstat",

    # /sys/*
    "system/sys/clocksource.out": "sys.sys.clocksource",
    "system/sys/cpu_scaling_available_governors.out":
        "sys.sys.cpu_scaling_available_governors",
    "system/sys/cpu_scaling_driver.out":
        "sys.sys.cpu_scaling_driver",
    "system/sys/cpu_scaling_governor.out":
        "sys.sys.cpu_scaling_governor",
    "system/sys/energy_perf_bias.out":
        "sys.sys.energy_perf_bias",
    "system/sys/intel_pstate.out": "sys.sys.intel_pstate",
    "system/sys/kernel_mm_transparent_hugepage.out":
        "sys.sys.transparent_hugepage",

    # Cgroup v2
    "system/cgroup/cpu_max.out": "sys.cgroup.cpu_max",
    "system/cgroup/cpu_weight.out": "sys.cgroup.cpu_weight",
    "system/cgroup/cpuset_cpus_effective.out":
        "sys.cgroup.cpuset_cpus_effective",
    "system/cgroup/io_max.out": "sys.cgroup.io_max",
    "system/cgroup/memory_current.out":
        "sys.cgroup.memory_current",
    "system/cgroup/memory_max.out": "sys.cgroup.memory_max",
    "system/cgroup/memory_stat.out": "sys.cgroup.memory_stat",
    "system/cgroup/memory_swap_max.out":
        "sys.cgroup.memory_swap_max",
    "system/cgroup/pids_current.out": "sys.cgroup.pids_current",
    "system/cgroup/pids_max.out": "sys.cgroup.pids_max",

    # Cgroup v1
    "system/cgroup-v1/cpu_cfs_period_us.out":
        "sys.cgroup_v1.cpu_cfs_period_us",
    "system/cgroup-v1/cpu_cfs_quota_us.out":
        "sys.cgroup_v1.cpu_cfs_quota_us",
    "system/cgroup-v1/cpu_shares.out":
        "sys.cgroup_v1.cpu_shares",
    "system/cgroup-v1/cpuset_cpus.out":
        "sys.cgroup_v1.cpuset_cpus",
    "system/cgroup-v1/memory_limit_in_bytes.out":
        "sys.cgroup_v1.memory_limit_in_bytes",
    "system/cgroup-v1/memory_stat.out":
        "sys.cgroup_v1.memory_stat",
    "system/cgroup-v1/memory_usage_in_bytes.out":
        "sys.cgroup_v1.memory_usage_in_bytes",

    # Cloud / container identity
    "system/cloud/bios_vendor.out": "sys.cloud.bios_vendor",
    "system/cloud/chassis_asset_tag.out":
        "sys.cloud.chassis_asset_tag",
    "system/cloud/product_name.out": "sys.cloud.product_name",
    "system/cloud/sys_vendor.out": "sys.cloud.sys_vendor",
    "system/container/cgroup_membership.out":
        "sys.container.cgroup_membership",
    "system/container/dockerenv.out": "sys.container.dockerenv",
    "system/container/environment.out":
        "sys.container.environment",
    "system/container/k8s_namespace.out":
        "sys.container.k8s_namespace",
    "system/container/mountinfo.out": "sys.container.mountinfo",

    # openssl
    "system/openssl/ciphers.out": "sys.openssl.ciphers",
    "system/openssl/crypto-policies-isapplied.out":
        "sys.openssl.crypto_policies_isapplied",
    "system/openssl/crypto-policies-show.out":
        "sys.openssl.crypto_policies_show",
    "system/openssl/engines.out": "sys.openssl.engines",
    "system/openssl/fips-mode-setup.out":
        "sys.openssl.fips_mode_setup",
    "system/openssl/version.out": "sys.openssl.version",

    # systemd / tuned
    "system/systemd/list-units.out": "sys.systemd.list_units",
    "system/systemd/postgresql-status.out":
        "sys.systemd.postgresql_status",
    "system/tuned/tuned-active.out": "sys.tuned.active",
    "system/tuned/tuned-list.out": "sys.tuned.list",
}

# Package manager dumps: several possible filenames per distro.
for _pkg_name in (
    "packages-apt-list-installed",
    "packages-dnf-list-installed",
    "packages-dpkg",
    "packages-rpm",
    "packages-yum-list-installed",
    "packages_brew",
    "packages_brew_postgres",
):
    _FIXED[f"system/{_pkg_name}.out"] = f"sys.{_pkg_name}"

# Per-database and pg_statviz files are classified by pattern.
_DB_RE = re.compile(
    r"^databases/(?P<db>[^/]+)/(?P<stem>[^/]+)\.(?P<ext>tsv)$"
)
_STATVIZ_RE = re.compile(
    r"^pg_statviz/(?P<db>[^/]+)/(?P<stem>[^/]+)\.(?P<ext>tsv)$"
)
# Per-db stems we know about (from DATA.md). Unknown stems inside a known
# per-db parent still fall through to "unknown" so the canary catches them.
_DB_STEMS: frozenset[str] = frozenset(
    {
        "bloat",
        "extensions",
        "funcs",
        "indexes",
        "languages",
        "operators",
        "partitioned_tables",
        "partitions",
        "pgstattuple",
        "procs",
        "publication_tables",
        "publications",
        "schemas",
        "sequences",
        "stat_database",
        "statistics",
        "subscription_tables",
        "tables",
        "triggers",
        "types",
    }
)
_STATVIZ_STEMS: frozenset[str] = frozenset(
    {
        "buf",
        "conf",
        "conn",
        "db",
        "io",
        "lock",
        "repl",
        "slru",
        "snapshots",
        "wait",
        "wal",
    }
)


def classify(path: str, size: int = 0) -> ClassifiedEntry | None:
    """Classify *path* into a known file-kind.

    Returns ``None`` for unrecognized paths (the coverage-canary case).
    """
    kind = _FIXED.get(path)
    if kind is not None:
        return ClassifiedEntry(
            path=path, size=size, kind=kind, dbname=None
        )

    m = _DB_RE.match(path)
    if m is not None and m.group("stem") in _DB_STEMS:
        return ClassifiedEntry(
            path=path,
            size=size,
            kind=f"pg.db.{m.group('stem')}",
            dbname=m.group("db"),
        )

    m = _STATVIZ_RE.match(path)
    if m is not None and m.group("stem") in _STATVIZ_STEMS:
        return ClassifiedEntry(
            path=path,
            size=size,
            kind=f"pg_statviz.{m.group('stem')}",
            dbname=m.group("db"),
        )

    return None


def list_entries(zip_path: Path) -> list[ArchiveEntry]:
    """Return (non-directory) entries in *zip_path*.

    Raises ``ZipSafetyError`` if the archive declares more entries or
    more uncompressed bytes than we're willing to process. Reads only
    the central directory: no decompression happens here.
    """
    out: list[ArchiveEntry] = []
    total = 0
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            count += 1
            if count > MAX_ENTRIES:
                raise ZipSafetyError(
                    f"archive has >{MAX_ENTRIES} entries"
                )
            if info.file_size > MAX_ENTRY_SIZE_BYTES:
                raise ZipSafetyError(
                    f"entry {info.filename!r} declares "
                    f"{info.file_size} bytes uncompressed, "
                    f"ceiling is {MAX_ENTRY_SIZE_BYTES}"
                )
            total += info.file_size
            if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise ZipSafetyError(
                    f"archive declares >{total} bytes total "
                    f"uncompressed, ceiling is "
                    f"{MAX_TOTAL_UNCOMPRESSED_BYTES}"
                )
            out.append(
                ArchiveEntry(
                    path=info.filename, size=info.file_size
                )
            )
    return out


@contextmanager
def open_entry(
    zip_path: Path,
    entry_path: str,
    *,
    max_bytes: int = MAX_ENTRY_SIZE_BYTES,
) -> Iterator[IO[bytes]]:
    """Open a zip entry as a streaming binary file-like.

    Yields the ``ZipExtFile`` returned by :meth:`zipfile.ZipFile.open`,
    which decompresses on demand as the caller reads. Nothing is
    loaded into memory up-front. Suitable for iterating
    line-by-line or feeding a streaming parser.

    The central-directory-declared size is enforced at the entry level
    in :func:`list_entries`; this function layers an additional
    runtime guard for mismatched zips: the returned file-like raises
    :class:`ZipSafetyError` if the caller reads past ``max_bytes``.

    Raises ``KeyError`` if *entry_path* is not in the archive.
    """
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(entry_path, "r") as raw:
            # The helper exposes just the subset of IO[bytes] we
            # actually use (.read, iter). `cast` lets type-checkers
            # treat it as IO[bytes] without forcing us to stub the
            # other 20+ methods.
            yield cast(
                IO[bytes],
                _CappedReader(raw, max_bytes, entry_path),
            )


class _CappedReader:
    """File-like wrapper that enforces ``max_bytes`` at read time."""

    def __init__(
        self,
        inner: IO[bytes],
        max_bytes: int,
        entry_path: str,
    ) -> None:
        self._inner = inner
        self._remaining = max_bytes
        self._entry_path = entry_path

    def read(self, size: int = -1) -> bytes:
        """Read up to *n* bytes, raising past the byte cap."""
        want = self._remaining + 1 if size < 0 else size
        data = self._inner.read(want)
        self._remaining -= len(data)
        if self._remaining < 0:
            raise ZipSafetyError(
                f"entry {self._entry_path!r} exceeds "
                f"max_bytes during read"
            )
        return data

    def readable(self) -> bool:
        """Report that the stream supports reading."""
        return True

    def close(self) -> None:
        """Close the underlying zip stream."""
        self._inner.close()

    def __iter__(self) -> Iterator[bytes]:
        while True:
            chunk = self.read(64 * 1024)
            if not chunk:
                return
            yield chunk


def walk(
    zip_path: Path,
) -> tuple[list[ClassifiedEntry], list[str]]:
    """Walk *zip_path* returning (classified, unknown_paths).

    Propagates ``ZipSafetyError`` from ``list_entries``.
    """
    classified: list[ClassifiedEntry] = []
    unknown: list[str] = []
    for entry in list_entries(zip_path):
        ce = classify(entry.path, entry.size)
        if ce is None:
            unknown.append(entry.path)
        else:
            classified.append(ce)
    return classified, unknown
