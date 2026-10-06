"""Mapping from analysis category to archive file kinds.

Used to derive, per analysis row, the list of archive paths that
contributed to it. The mapping is intentionally a forward index
(``category -> set of kinds``) rather than backed off the rules /
prompt-builder code: that code reads many kinds opportunistically,
including a few that don't materially shape any single category's
output, and we want stability for the operator-facing source list.

Per-database briefs use the synthetic category name
``"Database: <datname>"`` (matching what the orchestrator persists
in ``radar.briefs.category``). Their source files are the
``pg.db.*`` and ``pg_statviz.*`` entries whose ``dbname`` matches.

Coverage-canary (unknown) paths are deliberately excluded: those
surface separately through the per-upload files inventory
endpoint, not per-category.
"""

from __future__ import annotations

from typing import Any


# Top-level categories (must mirror the names persisted by the
# orchestrator at insert_brief time: see analyze/categories.py).
CATEGORY_KINDS: dict[str, frozenset[str]] = {
    "Host & OS": frozenset({
        "sys.cgroup_v1.memory_limit_in_bytes",
        "sys.cgroup_v1.memory_usage_in_bytes",
        "sys.cgroup.cpu_max",
        "sys.cgroup.memory_current",
        "sys.cgroup.memory_max",
        "sys.cloud.bios_vendor",
        "sys.cloud.product_name",
        "sys.cloud.sys_vendor",
        "sys.container.dockerenv",
        "sys.container.environment",
        "sys.container.k8s_namespace",
        "sys.dmesg",
        "sys.dmesg_t",
        "sys.diskspace",
        "sys.free",
        "sys.fstab",
        "sys.hostname",
        "sys.hosts",
        "sys.hypervisor",
        "sys.ifconfig",
        "sys.interfaces",
        "sys.io_queue_depth",
        "sys.io_schedulers",
        "sys.iostat",
        "sys.ip_addr",
        "sys.ipcs",
        "sys.limits",
        "sys.locale",
        "sys.locale_all",
        "sys.locale_conf",
        "sys.localectl",
        "sys.lsblk",
        "sys.lscpu",
        "sys.lsdevmapper",
        "sys.lsmod",
        "sys.lspci",
        "sys.machine_id",
        "sys.mount",
        "sys.mpstat",
        "sys.netstat_stats",
        "sys.nfsiostat",
        "sys.numactl",
        "sys.numastat",
        "sys.os_release",
        "sys.proc.cpuinfo",
        "sys.proc.diskstats",
        "sys.proc.loadavg",
        "sys.proc.meminfo",
        "sys.proc.mounts",
        "sys.proc.pressure_cpu",
        "sys.proc.pressure_io",
        "sys.proc.pressure_memory",
        "sys.proc.swaps",
        "sys.proc.uptime",
        "sys.ps",
        "sys.read_ahead",
        "sys.resolv_conf",
        "sys.sar",
        "sys.sestatus",
        "sys.ss_listeners",
        "sys.ss_summary",
        "sys.sys.cpu_scaling_governor",
        "sys.sys.transparent_hugepage",
        "sys.sysctl",
        "sys.sysctl_conf",
        "sys.systemd.list_units",
        "sys.systemd.postgresql_status",
        "sys.timedatectl",
        "sys.top",
        "sys.tuned.active",
        "sys.tuned.list",
        "sys.uname",
        "sys.vmstat_command",
    }),
    "PostgreSQL Configuration": frozenset({
        "pg.available_extensions",
        "pg.conf.pg_hba",
        "pg.conf.pg_ident",
        "pg.conf.postgresql",
        "pg.conf.postgresql_auto",
        "pg.conf.recovery",
        "pg.db_role_setting",
        "pg.file_settings",
        "pg.hba_file_rules",
        "pg.postmaster_start_time",
        "pg.recovery_done",
        "pg.roles",
        "pg.settings",
        "pg.shmem_allocations",
        "pg.tablespace_sizes",
        "pg.tablespaces",
        "pg.version",
    }),
    "Workload": frozenset({
        "pg.blocking_locks",
        "pg.connection_summary",
        "pg.database_sizes",
        "pg.databases",
        "pg.databases_blk",
        "pg.databases_tup",
        "pg.databases_xact",
        "pg.prepared_xacts",
        "pg.running_activity",
        "pg.running_activity_maxage",
        "pg.running_locks",
        "pg.stat_statements.calls",
        "pg.stat_statements.max_time",
        "pg.stat_statements.total_time",
        "pg.waits_sample",
    }),
    "Internals & I/O Health": frozenset({
        "pg.archiver",
        "pg.bgwriter",
        "pg.checkpointer",
        "pg.databases_checksums",
        "pg.stat_io",
        "pg.stat_progress_analyze",
        "pg.stat_progress_basebackup",
        "pg.stat_progress_cluster",
        "pg.stat_progress_copy",
        "pg.stat_progress_create_index",
        "pg.stat_progress_vacuum",
        "pg.stat_slru",
        "pg.stat_wal",
        "pg.wal_position",
    }),
    "Replication": frozenset({
        "pg.database_conflicts",
        "pg.replication",
        "pg.replication_origin",
        "pg.replication_slots",
        "pg.subscriptions",
        "pg.wal_receiver",
    }),
}

_PER_DB_PREFIX = "Database: "


def _per_db_dbname(category: str) -> str | None:
    if category.startswith(_PER_DB_PREFIX):
        return category[len(_PER_DB_PREFIX):]
    return None


def sources_for_category(
    category: str,
    inventory: list[dict[str, Any]],
) -> list[str]:
    """Return the sorted list of archive paths feeding *category*.

    *inventory* is the persisted ``radar.uploads.archive_files``
    list-of-dicts. Each dict must have ``path``, ``kind``,
    ``dbname``. Unknown entries (``kind = None``) are excluded
    regardless of category: see module docstring.
    """
    dbname = _per_db_dbname(category)
    if dbname is not None:
        return sorted(
            e["path"]
            for e in inventory
            if e.get("kind")
            and e.get("dbname") == dbname
            and (
                e["kind"].startswith("pg.db.")
                or e["kind"].startswith("pg_statviz.")
            )
        )
    kinds = CATEGORY_KINDS.get(category)
    if not kinds:
        return []
    return sorted(
        e["path"]
        for e in inventory
        if e.get("kind") in kinds
    )
