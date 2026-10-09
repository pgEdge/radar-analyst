"""Per-category facts blocks for the LLM prompts.

Each builder renders one category's parsed evidence into the
compact text block the user prompt wraps in ``<user_data>``.
A builder returns None when the archive carries no data for
its category, which the orchestrator persists as UNKNOWN.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from radar_analyst.ai.prompts import (
    SystemContext,
)
from radar_analyst.analyze.categories import Category
from radar_analyst.analyze.humanize import (
    format_age_seconds,
    format_count,
    format_size_bytes,
    format_uptime,
)
from radar_analyst.parse.databases import (
    DatabaseXactStats,
)
from radar_analyst.parse.host_os import (
    CgroupMemoryStat,
    DmesgSummary,
    IostatDevice,
    PsiPressure,
)
from radar_analyst.parse.pg_activity import (
    ConnectionSummary,
    PgActivity,
    PreparedXacts,
    RunningActivityMaxage,
    RunningLocks,
    WaitsSample,
    oldest_client_query_age_s,
)
from radar_analyst.parse.pg_conf import (
    DbRoleSetting,
    FileSetting,
    HbaRule,
)
from radar_analyst.parse.pg_diagnostics import (
    PgRole,
    ProgressRow,
    ShmemAllocation,
    Tablespace,
    TablespaceSize,
)
from radar_analyst.parse.pg_internals import (
    PgBgwriter,
    PgCheckpointer,
    PgStatWal,
)
from radar_analyst.parse.pg_settings import (
    PgSettings,
)
from radar_analyst.parse.pg_version import (
    PgVersionInfo,
)
from radar_analyst.parse.pg_wal import (
    PgArchiver,
    ReplicationOrigin,
    ReplicationReplica,
    ReplicationSlots,
    Subscription,
    WalPosition,
    WalReceiver,
)
from radar_analyst.parse.swaps import SwapDevice


_logger = logging.getLogger(__name__)


def _kernel_from_uname(uname: str) -> str:
    # "Linux host 6.11.0-9-generic #10-Ubuntu SMP ...": third token
    # is the kernel release. Fall back to the whole line if we
    # can't find it.
    parts = uname.split()
    return parts[2] if len(parts) >= 3 else uname


def build_system_context(
    parsed: dict[str, Any], present: set[str]
) -> SystemContext:
    """Assemble the SystemContext from parsed host facts."""
    version: PgVersionInfo | None = parsed.get("pg.version")
    meminfo: dict[str, int] = (
        parsed.get("sys.proc.meminfo") or {}
    )
    total_ram = ""
    mem_total = meminfo.get("MemTotal")
    if mem_total:
        gib = mem_total / (1024**3)
        total_ram = f"{gib:.1f} GiB"

    hostname = parsed.get("sys.hostname") or ""
    os_release = parsed.get("sys.os_release") or {}
    os_name = (
        os_release.get("PRETTY_NAME")
        or os_release.get("NAME")
        or ""
    )
    uname = parsed.get("sys.uname") or ""
    kernel = _kernel_from_uname(uname) if uname else ""

    lscpu: dict[str, str] = parsed.get("sys.lscpu") or {}
    cpu_count = 0
    try:
        cpu_count = int(lscpu.get("CPU(s)", "0"))
    except ValueError:
        cpu_count = 0

    uptime_secs = parsed.get("sys.proc.uptime")
    host_uptime = (
        format_uptime(uptime_secs)
        if isinstance(uptime_secs, (int, float))
        and uptime_secs > 0
        else ""
    )
    pg_started = parsed.get("pg.postmaster_start_time") or ""
    hypervisor = parsed.get("sys.hypervisor") or ""

    is_container = bool(parsed.get("sys.is_container"))
    cloud_provider = parsed.get("sys.cloud_provider") or ""

    return SystemContext(
        hostname=hostname,
        os=os_name,
        kernel=kernel,
        cpu_count=cpu_count,
        total_ram=total_ram,
        is_container=is_container,
        hypervisor=hypervisor,
        cloud_provider=cloud_provider,
        pg_version=version.raw if version else "",
        role="",
        pg_started=pg_started,
        host_uptime=host_uptime,
    )


def _host_memory_lines(parsed: dict[str, Any]) -> list[str]:
    """Render the meminfo section of the Host & OS block."""
    lines: list[str] = []
    meminfo: dict[str, int] = (
        parsed.get("sys.proc.meminfo") or {}
    )
    if meminfo:
        lines.append("Memory (bytes):")
        for k in (
            "MemTotal",
            "MemAvailable",
            "Buffers",
            "Cached",
            "SwapTotal",
            "SwapFree",
        ):
            if k in meminfo:
                lines.append(f"  {k} = {meminfo[k]:,}")
    return lines


def _host_kernel_lines(parsed: dict[str, Any]) -> list[str]:
    """Render kernel tunables, THP, and CPU governor lines."""
    lines: list[str] = []
    sysctl: dict[str, str] = parsed.get("sys.sysctl") or {}
    if sysctl:
        lines.append("Kernel tunables (PG-relevant whitelist):")
        for k in sorted(sysctl):
            lines.append(f"  {k} = {sysctl[k]}")
    thp = parsed.get("sys.sys.transparent_hugepage")
    if thp:
        lines.append(f"Transparent Huge Pages: {thp}")
    governor: str | None = parsed.get(
        "sys.sys.cpu_scaling_governor"
    )
    if governor:
        lines.append(f"CPU scaling governor: {governor}")
    return lines


def _host_pressure_lines(parsed: dict[str, Any]) -> list[str]:
    """Render PSI pressure lines for CPU, I/O, and memory."""
    lines: list[str] = []
    for kind, label in (
        ("sys.proc.pressure_cpu", "CPU"),
        ("sys.proc.pressure_io", "I/O"),
        ("sys.proc.pressure_memory", "memory"),
    ):
        p: PsiPressure | None = parsed.get(kind)
        if p is not None:
            full_str = (
                f" full.avg300={p.full.avg300:.2f}"
                if p.full is not None
                else ""
            )
            lines.append(
                f"PSI {label} pressure: "
                f"some.avg300={p.some.avg300:.2f}"
                f"{full_str}"
            )
    return lines


def _host_cgroup_lines(parsed: dict[str, Any]) -> list[str]:
    """Render the cgroup v2 memory usage line."""
    mem_cur: int | None = parsed.get("sys.cgroup.memory_current")
    mem_max: int | None = parsed.get("sys.cgroup.memory_max")
    stat: CgroupMemoryStat | None = parsed.get(
        "sys.cgroup.memory_stat"
    )
    if mem_cur is None:
        return []
    gib = 1024 ** 3
    line = f"cgroup memory: {mem_cur / gib:.1f} GiB"
    if mem_max is not None:
        line += (
            f" / {mem_max / gib:.1f} GiB"
            f" ({mem_cur / mem_max * 100:.0f}%)"
        )
    else:
        line += " (no limit)"
    if stat is not None:
        line += (
            f", {(mem_cur - stat.page_cache) / gib:.1f} GiB"
            " excluding page cache"
        )
    return [line]


def _host_dmesg_lines(parsed: dict[str, Any]) -> list[str]:
    """Render the dmesg OOM and I/O error summary line."""
    lines: list[str] = []
    dmesg: DmesgSummary | None = parsed.get("sys.dmesg")
    if dmesg is not None:
        if dmesg.oom_count == 0 and dmesg.io_error_count == 0:
            lines.append("dmesg: no OOM or I/O errors")
        else:
            lines.append(
                f"dmesg: {dmesg.oom_count} OOM, "
                f"{dmesg.io_error_count} I/O error(s)"
            )
    return lines


def _host_iostat_lines(parsed: dict[str, Any]) -> list[str]:
    """Render the iostat top-devices-by-utilisation line."""
    lines: list[str] = []
    iostat: list[IostatDevice] | None = parsed.get(
        "sys.iostat"
    )
    if iostat:
        real = [
            d for d in iostat
            if d.util_pct is not None and d.util_pct > 0
        ]
        top3 = sorted(
            real,
            key=lambda d: d.util_pct or 0,
            reverse=True,
        )[:3]
        if top3:
            dev_str = ", ".join(
                f"{d.device} {d.util_pct:.0f}%"
                for d in top3
            )
            lines.append(f"iostat top devices: {dev_str}")
    return lines


def _host_swap_lines(parsed: dict[str, Any]) -> list[str]:
    """Render the swap devices summary line."""
    lines: list[str] = []
    swaps: list[SwapDevice] | None = parsed.get(
        "sys.proc.swaps"
    )
    if swaps is not None:
        if not swaps:
            lines.append("Swap: none active")
        else:
            total_gib = sum(
                d.size_kib for d in swaps
            ) / (1024 * 1024)
            lines.append(
                f"Swap: {len(swaps)} device(s), "
                f"{total_gib:.1f} GiB total"
            )
    return lines


def _build_host_os_facts(
    parsed: dict[str, Any],
) -> str | None:
    """Render the Host & OS facts block, or None if no data."""
    lines: list[str] = []
    lines.extend(_host_memory_lines(parsed))
    lines.extend(_host_kernel_lines(parsed))
    lines.extend(_host_pressure_lines(parsed))
    lines.extend(_host_cgroup_lines(parsed))
    lines.extend(_host_dmesg_lines(parsed))
    lines.extend(_host_iostat_lines(parsed))
    lines.extend(_host_swap_lines(parsed))
    return "\n".join(lines) if lines else None


# Subset of pg_settings worth sending to the LLM regardless of
# whether they were explicitly configured: these are the knobs a
# DBA always cares about when reviewing a server's config.
_IMPORTANT_SETTINGS: tuple[str, ...] = (
    "shared_buffers",
    "work_mem",
    "maintenance_work_mem",
    "max_connections",
    "max_wal_size",
    "min_wal_size",
    "checkpoint_timeout",
    "fsync",
    "synchronous_commit",
    "wal_level",
    "archive_mode",
    "wal_compression",
    "autovacuum",
    "effective_cache_size",
    "random_page_cost",
    "huge_pages",
)


def _config_setting_lines(parsed: dict[str, Any]) -> list[str]:
    """Render the version line and the key pg_settings values."""
    lines: list[str] = []
    version: PgVersionInfo | None = parsed.get("pg.version")
    if version:
        lines.append(f"PostgreSQL version: {version.raw}")
    settings: PgSettings | None = parsed.get("pg.settings")
    if settings:
        lines.append(
            "Key PostgreSQL settings "
            "(non-default filter not yet applied):"
        )
        for name in _IMPORTANT_SETTINGS:
            s = settings.get(name)
            if s is None:
                continue
            unit = f" {s.unit}" if s.unit else ""
            lines.append(f"  {name} = {s.setting}{unit}")
    return lines


def _config_hba_lines(parsed: dict[str, Any]) -> list[str]:
    """Render HBA auth methods pivoted by connection type."""
    # The type axis matters: `trust` on a `local` rule is normal
    # (Unix-socket admin access) while `trust` on a `host*` rule
    # is a critical misconfiguration, so the pivot keeps the two
    # distinguishable in the prompt.
    lines: list[str] = []
    hba_rules: list[HbaRule] | None = parsed.get(
        "pg.hba_file_rules"
    )
    if hba_rules:
        from collections import Counter
        by_type: dict[str, Counter[str]] = {}
        for r in hba_rules:
            by_type.setdefault(r.type, Counter())[r.auth_method] += 1
        type_lines: list[str] = []
        for typ in sorted(by_type):
            methods = ", ".join(
                f"{m}={n}"
                for m, n in by_type[typ].most_common()
            )
            type_lines.append(f"{typ}: {methods}")
        lines.append(
            f"HBA auth methods ({len(hba_rules)} rules): "
            + "; ".join(type_lines)
        )
    return lines


def _config_drift_lines(parsed: dict[str, Any]) -> list[str]:
    """Render ALTER SYSTEM drift, file_settings, role overrides."""
    lines: list[str] = []
    auto_conf: str | None = parsed.get("pg.conf.postgresql_auto")
    if auto_conf:
        has_settings = any(
            ln.strip() and not ln.strip().startswith("#")
            for ln in auto_conf.splitlines()
        )
        if has_settings:
            lines.append(
                "postgresql.auto.conf: has active settings "
                "(ALTER SYSTEM was used)"
            )
    file_settings: list[FileSetting] | None = parsed.get(
        "pg.file_settings"
    )
    if file_settings:
        errors = sum(1 for s in file_settings if s.error)
        lines.append(
            f"file_settings: {len(file_settings)} entries"
            + (f", {errors} with errors" if errors else "")
        )
    role_settings: list[DbRoleSetting] | None = parsed.get(
        "pg.db_role_setting"
    )
    if role_settings:
        lines.append(
            f"db_role_setting: {len(role_settings)} override(s)"
        )
    return lines


def _config_role_lines(parsed: dict[str, Any]) -> list[str]:
    """Render the roles summary line."""
    lines: list[str] = []
    roles: list[PgRole] | None = parsed.get("pg.roles")
    if roles:
        superusers = [r.rolname for r in roles if r.rolsuper]
        repl_roles = [
            r.rolname for r in roles if r.rolreplication
        ]
        lines.append(
            f"Roles: {len(roles)} total, "
            f"superusers: {', '.join(superusers) or 'none'}, "
            f"replication: "
            f"{', '.join(repl_roles) or 'none'}"
        )
    return lines


def _config_tablespace_lines(parsed: dict[str, Any]) -> list[str]:
    """Render the custom tablespaces line with sizes."""
    lines: list[str] = []
    tablespaces: list[Tablespace] | None = parsed.get(
        "pg.tablespaces"
    )
    tbs_sizes: list[TablespaceSize] | None = parsed.get(
        "pg.tablespace_sizes"
    )
    if tablespaces:
        custom = [
            t.spcname for t in tablespaces
            if t.spclocation
        ]
        size_map = (
            {s.spcname: s.size_bytes for s in tbs_sizes}
            if tbs_sizes else {}
        )
        if custom:
            entries = []
            for name in custom:
                sz = size_map.get(name)
                sz_str = (
                    f"{sz / (1024 ** 3):.1f} GiB"
                    if sz else "unknown size"
                )
                entries.append(f"{name} ({sz_str})")
            lines.append(
                f"Custom tablespaces: {', '.join(entries)}"
            )
    return lines


def _build_pg_config_facts(
    parsed: dict[str, Any],
) -> str | None:
    """Render the PostgreSQL Configuration facts block."""
    lines: list[str] = []
    lines.extend(_config_setting_lines(parsed))
    lines.extend(_config_hba_lines(parsed))
    lines.extend(_config_drift_lines(parsed))
    lines.extend(_config_role_lines(parsed))
    lines.extend(_config_tablespace_lines(parsed))
    return "\n".join(lines) if lines else None


def _workload_sizing_lines(parsed: dict[str, Any]) -> list[str]:
    """Render the max_connections sizing context line."""
    lines: list[str] = []
    settings: PgSettings | None = parsed.get("pg.settings")
    if settings is not None:
        mc = settings.get("max_connections")
        if mc is not None:
            lines.append(f"max_connections = {mc.setting}")
    return lines


def _workload_xact_lines(parsed: dict[str, Any]) -> list[str]:
    """Render cluster-wide commit and rollback totals."""
    # Cumulative since stats reset, from pg_stat_database,
    # summed across all databases.
    lines: list[str] = []
    xact: dict[str, DatabaseXactStats] = (
        parsed.get("pg.databases_xact") or {}
    )
    if xact:
        total_commits = sum(
            x.xact_commit for x in xact.values()
        )
        total_rollbacks = sum(
            x.xact_rollback for x in xact.values()
        )
        total = total_commits + total_rollbacks
        rb_pct = (
            f" ({total_rollbacks / total:.1%} rollback)"
            if total > 0 else ""
        )
        # bgwriter.stats_reset is cluster-wide (reset only by
        # pg_stat_reset_shared('bgwriter')).
        bg: PgBgwriter | None = parsed.get("pg.bgwriter")
        reset_dt = bg.stats_reset if bg else None
        since_note = (
            f" (since {reset_dt.isoformat()})"
            if reset_dt else ""
        )
        lines.append(
            f"Cluster transactions{since_note}: "
            f"{total_commits:,} commits, "
            f"{total_rollbacks:,} rollbacks{rb_pct}"
        )
    return lines


def _workload_session_lines(a: PgActivity | None) -> list[str]:
    """Render backend totals grouped by state."""
    lines: list[str] = []
    if a is not None:
        lines.append(f"Total backends: {a.total}")
        if a.by_state:
            grouped = ", ".join(
                f"{s}={n}"
                for s, n in sorted(a.by_state.items())
            )
            lines.append(f"  by state: {grouped}")
    return lines


def _workload_maxage_lines(
    maxage: RunningActivityMaxage | None, a: PgActivity | None
) -> list[str]:
    """Render oldest backend, xact, and query age lines."""
    lines: list[str] = []
    if maxage is not None:
        lines.append(
            "Oldest in pg_stat_activity (now - column):"
        )
        lines.append(
            f"  backend = {format_age_seconds(maxage.max_backend_age_s)}"
        )
        lines.append(
            f"  xact    = {format_age_seconds(maxage.max_xact_age_s)}"
        )
        query_age = oldest_client_query_age_s(maxage, a)
        lines.append(
            f"  query   = {format_age_seconds(query_age)}"
            " (client backends)"
        )
    return lines


def _workload_wait_lines(
    waits: WaitsSample | None, a: PgActivity | None
) -> list[str]:
    """Render wait-event lines, preferring the waits_sample."""
    lines: list[str] = []
    if waits is not None and waits.total > 0:
        lines.append(
            f"Currently waiting backends: {waits.total}"
        )
        if waits.by_event_type:
            grouped = ", ".join(
                f"{k}={v}"
                for k, v in sorted(waits.by_event_type.items())
            )
            lines.append(f"  by wait_event_type: {grouped}")
        # Top events only: keep token count bounded.
        top_events = sorted(
            waits.by_event.items(),
            key=lambda kv: -kv[1],
        )[:8]
        if top_events:
            grouped = ", ".join(
                f"{k}={v}" for k, v in top_events
            )
            lines.append(f"  top events: {grouped}")
    elif a is not None and a.wait_events:
        lines.append("Observed wait events (from running):")
        for ev in sorted(a.wait_events):
            lines.append(f"  {ev} = {a.wait_events[ev]}")
    return lines


def _workload_grid_lines(
    conn: ConnectionSummary | None,
) -> list[str]:
    """Render the pre-aggregated state and wait_event_type grid."""
    lines: list[str] = []
    if conn is not None and conn.cells:
        lines.append(
            "connection_summary (state, wait_event_type, "
            "count):"
        )
        # Cap at 12 cells; the file is naturally small but
        # bound it as a defensive measure.
        for state, wet, n in conn.cells[:12]:
            s_disp = state if state else "(unknown)"
            w_disp = wet if wet else "(none)"
            lines.append(f"  {s_disp} / {w_disp} = {n}")
    return lines


def _workload_lock_lines(
    rlocks: RunningLocks | None, locks_count: int | None
) -> list[str]:
    """Render granted-lock distribution and blocking-chain lines."""
    lines: list[str] = []
    if rlocks is not None and rlocks.total > 0:
        lines.append(f"Granted locks: {rlocks.total}")
        if rlocks.by_mode:
            top_modes = sorted(
                rlocks.by_mode.items(),
                key=lambda kv: -kv[1],
            )[:8]
            grouped = ", ".join(
                f"{k}={v}" for k, v in top_modes
            )
            lines.append(f"  by mode: {grouped}")
        if rlocks.by_locktype:
            grouped = ", ".join(
                f"{k}={v}"
                for k, v in sorted(rlocks.by_locktype.items())
            )
            lines.append(f"  by locktype: {grouped}")
    if locks_count is not None:
        lines.append(
            f"Blocking lock chains at snapshot: {locks_count}"
        )
    return lines


def _workload_prepared_lines(
    prep: PreparedXacts | None,
) -> list[str]:
    """Render the prepared (2PC) transactions line."""
    lines: list[str] = []
    if prep is not None:
        if prep.total == 0:
            lines.append("Prepared (2PC) transactions: 0")
        else:
            tail = (
                f" (oldest gid = {prep.oldest_gid})"
                if prep.oldest_gid
                else ""
            )
            lines.append(
                f"Prepared (2PC) transactions: {prep.total}"
                f"{tail}"
            )
    return lines


def _build_workload_facts(
    parsed: dict[str, Any],
) -> str | None:
    """Cluster-level workload picture for the LLM.

    Combines pg_stat_activity (sessions, wait events, oldest
    xact/query/backend), the pre-aggregated connection_summary
    grid, the granted-locks distribution, blocking-lock count,
    and prepared (2PC) transactions. ``max_connections`` from
    pg_settings is included so the LLM can put backend counts in
    context.
    """
    a: PgActivity | None = parsed.get("pg.running_activity")
    locks_count: int | None = parsed.get("pg.blocking_locks")
    maxage: RunningActivityMaxage | None = parsed.get(
        "pg.running_activity_maxage"
    )
    waits: WaitsSample | None = parsed.get("pg.waits_sample")
    conn: ConnectionSummary | None = parsed.get(
        "pg.connection_summary"
    )
    rlocks: RunningLocks | None = parsed.get("pg.running_locks")
    prep: PreparedXacts | None = parsed.get("pg.prepared_xacts")

    if all(
        v is None
        for v in (a, locks_count, maxage, waits, conn, rlocks, prep)
    ):
        return None

    lines: list[str] = []
    lines.extend(_workload_sizing_lines(parsed))
    lines.extend(_workload_xact_lines(parsed))
    lines.extend(_workload_session_lines(a))
    lines.extend(_workload_maxage_lines(maxage, a))
    lines.extend(_workload_wait_lines(waits, a))
    lines.extend(_workload_grid_lines(conn))
    lines.extend(_workload_lock_lines(rlocks, locks_count))
    lines.extend(_workload_prepared_lines(prep))
    return "\n".join(lines) if lines else None


def _internals_archiver_lines(
    archiver: PgArchiver | None,
) -> list[str]:
    """Render WAL archiver state and failure counters."""
    lines: list[str] = []
    if archiver is not None:
        lines.append("WAL archiver:")
        lines.append(
            f"  archived_count = {archiver.archived_count}"
        )
        lines.append(
            "  last_archived_wal = "
            f"{archiver.last_archived_wal or '(none)'}"
        )
        lines.append(
            "  last_archived_time = "
            f"{archiver.last_archived_time or '(never)'}"
        )
        lines.append(
            f"  failed_count = {archiver.failed_count}"
        )
        if archiver.last_failed_wal:
            lines.append(
                f"  last_failed_wal = {archiver.last_failed_wal}"
            )
            lines.append(
                "  last_failed_time = "
                f"{archiver.last_failed_time or '(never)'}"
            )
    return lines


def _internals_checkpoint_lines(
    bg: PgBgwriter | None, cp: PgCheckpointer | None
) -> list[str]:
    """Render checkpoint counters from checkpointer or bgwriter."""
    lines: list[str] = []
    if cp is not None:
        # PG17+: dedicated checkpointer table.
        total_cp = cp.num_timed + cp.num_requested
        req_pct = (
            f"{cp.num_requested / total_cp * 100:.0f}%"
            if total_cp > 0
            else "n/a"
        )
        lines.append(
            f"Checkpointer (PG17+): "
            f"timed={cp.num_timed:,} "
            f"requested={cp.num_requested:,} "
            f"({req_pct} requested) "
            f"write_time={cp.write_time:.0f}ms "
            f"sync_time={cp.sync_time:.0f}ms "
            f"buffers_written={cp.buffers_written:,}"
        )
    elif bg is not None and bg.checkpoints_timed is not None:
        # Pre-PG17: checkpoint fields live in bgwriter.
        ct = bg.checkpoints_timed or 0
        cr = bg.checkpoints_req or 0
        total_cp = ct + cr
        req_pct = (
            f"{cr / total_cp * 100:.0f}%"
            if total_cp > 0
            else "n/a"
        )
        lines.append(
            f"Checkpoints: timed={ct:,} "
            f"requested={cr:,} ({req_pct} requested)"
        )
    return lines


def _internals_bgwriter_lines(bg: PgBgwriter | None) -> list[str]:
    """Render bgwriter buffer counters."""
    lines: list[str] = []
    if bg is not None:
        parts = [
            f"buffers_clean={bg.buffers_clean:,}",
            f"maxwritten_clean={bg.maxwritten_clean:,}",
            f"buffers_alloc={bg.buffers_alloc:,}",
        ]
        if bg.buffers_backend is not None:
            parts.append(
                f"buffers_backend={bg.buffers_backend:,}"
            )
        if bg.buffers_backend_fsync is not None:
            parts.append(
                "buffers_backend_fsync="
                f"{bg.buffers_backend_fsync:,}"
            )
        lines.append("Bgwriter: " + " ".join(parts))
    return lines


def _internals_wal_lines(wal: PgStatWal | None) -> list[str]:
    """Render pg_stat_wal write-activity counters."""
    lines: list[str] = []
    if wal is not None:
        lines.append(
            f"pg_stat_wal: records={wal.wal_records:,} "
            f"fpi={wal.wal_fpi:,} "
            f"bytes={wal.wal_bytes:,} "
            f"buffers_full={wal.wal_buffers_full:,} "
            f"writes={wal.wal_write:,} "
            f"syncs={wal.wal_sync:,}"
        )
    return lines


def _internals_shmem_lines(parsed: dict[str, Any]) -> list[str]:
    """Render the shared memory top-allocations line."""
    lines: list[str] = []
    shmem: list[ShmemAllocation] | None = parsed.get(
        "pg.shmem_allocations"
    )
    if shmem:
        total = sum(s.size for s in shmem)
        top3 = sorted(shmem, key=lambda s: -s.size)[:3]
        top3_str = ", ".join(
            f"{s.name} ({s.size // (1024 * 1024)} MiB)"
            for s in top3
        )
        lines.append(
            f"Shmem: {total // (1024 * 1024)} MiB total, "
            f"top allocations: {top3_str}"
        )
    return lines


def _internals_progress_lines(parsed: dict[str, Any]) -> list[str]:
    """Render active progress operations (vacuum, index, etc.)."""
    lines: list[str] = []
    _progress_kinds = (
        "pg.stat_progress_vacuum",
        "pg.stat_progress_analyze",
        "pg.stat_progress_create_index",
        "pg.stat_progress_copy",
        "pg.stat_progress_cluster",
        "pg.stat_progress_basebackup",
    )
    active_ops: list[str] = []
    for kind in _progress_kinds:
        rows: list[ProgressRow] | None = parsed.get(kind)
        if rows:
            op = kind.split("_progress_")[-1]
            active_ops.append(f"{op}×{len(rows)}")
    if active_ops:
        lines.append(
            f"Active progress operations: "
            f"{', '.join(active_ops)}"
        )
    return lines


def _build_internals_facts(
    parsed: dict[str, Any],
) -> str | None:
    """Compact facts block for Internals & I/O Health.

    Combines WAL archiver state (always present when archiving is
    on), pg_stat_bgwriter / pg_stat_checkpointer (checkpoint and
    bgwriter counters), and pg_stat_wal (WAL write activity).
    Returns None only when all sources are absent.
    """
    lines: list[str] = []
    archiver: PgArchiver | None = parsed.get("pg.archiver")
    bg: PgBgwriter | None = parsed.get("pg.bgwriter")
    cp: PgCheckpointer | None = parsed.get("pg.checkpointer")
    wal: PgStatWal | None = parsed.get("pg.stat_wal")
    lines.extend(_internals_archiver_lines(archiver))
    lines.extend(_internals_checkpoint_lines(bg, cp))
    lines.extend(_internals_bgwriter_lines(bg))
    lines.extend(_internals_wal_lines(wal))
    lines.extend(_internals_shmem_lines(parsed))
    lines.extend(_internals_progress_lines(parsed))
    # Per-database top-N summaries: bounded so the prompt stays
    # within sane token budgets even on hundreds-of-tables clusters.
    _append_top_n_per_db(parsed, lines, max_per_list=10)
    return "\n".join(lines) if lines else None


def _top_n_header_bits(tpd: Any, ipd: Any) -> list[str]:
    """Render the table and index count bits for one db header."""
    header_bits: list[str] = []
    n_tables = len(tpd) if tpd is not None else None
    n_indexes = len(ipd) if ipd is not None else None
    if n_tables is not None:
        header_bits.append(f"{n_tables:,} tables")
    if n_indexes is not None:
        header_bits.append(f"{n_indexes:,} indexes")
    return header_bits


def _top_n_db_lines(
    tpd: Any, ipd: Any, *, max_per_list: int
) -> list[str]:
    """Render top-N table and index lines for one database."""
    # Skip rendering when the underlying columns aren't
    # available (pre-0.5.0 radar tables.tsv lacked
    # table_size/reltuples; pre-0.5.0 indexes.tsv lacked
    # index_size). Without this, every row would render as
    # "(0 B, 0 rows)": meaningless noise in the LLM prompt.
    db_lines: list[str] = []
    have_table_size = tpd is not None and any(
        r.table_size or r.reltuples for r in tpd.rows
    )
    have_index_size = ipd is not None and any(
        r.index_size for r in ipd.rows
    )

    if tpd is not None and tpd.rows and have_table_size:
        top_tables = sorted(
            tpd.rows,
            key=lambda r: (-r.table_size, -r.reltuples),
        )[:max_per_list]
        shown = ", ".join(
            f"{t.fqname} "
            f"({format_size_bytes(t.table_size)}, "
            f"{format_count(int(t.reltuples))} rows)"
            for t in top_tables
        )
        db_lines.append(
            f"  Top {len(top_tables)} tables by size: "
            f"{shown}"
        )

    if ipd is not None and ipd.rows and have_index_size:
        top_indexes = sorted(
            ipd.rows, key=lambda r: -r.index_size
        )[:max_per_list]
        shown = ", ".join(
            f"{i.fqname} "
            f"({format_size_bytes(i.index_size)})"
            for i in top_indexes
        )
        db_lines.append(
            f"  Top {len(top_indexes)} indexes by size: "
            f"{shown}"
        )
    return db_lines


def _append_top_n_per_db(
    parsed: dict[str, Any],
    lines: list[str],
    *,
    max_per_list: int,
) -> None:
    """Append top-N largest-tables / largest-indexes lines.

    Per-database; one entry per line, hard-capped at *max_per_list*
    to keep the LLM prompt bounded. Tables sort by ``table_size``
    desc with ``reltuples`` as tiebreaker (size is the operationally
    interesting axis; row count disambiguates two equally-sized
    tables: and stays useful for older radar collectors that
    didn't emit table_size, where every row tied at 0). Indexes
    sort by ``index_size`` desc.

    Quietly does nothing if the per-db data isn't present.
    """
    tables_by_db: dict[str, Any] = (
        parsed.get("pg.db.tables") or {}
    )
    indexes_by_db: dict[str, Any] = (
        parsed.get("pg.db.indexes") or {}
    )
    if not tables_by_db and not indexes_by_db:
        return

    dbs = sorted(set(tables_by_db) | set(indexes_by_db))
    for db in dbs:
        tpd = tables_by_db.get(db)
        ipd = indexes_by_db.get(db)
        header_bits = _top_n_header_bits(tpd, ipd)
        if not header_bits:
            continue
        db_lines = _top_n_db_lines(
            tpd, ipd, max_per_list=max_per_list
        )
        if db_lines:
            lines.append(
                f"Database {db} ({', '.join(header_bits)}):"
            )
            lines.extend(db_lines)


def _repl_wal_position_lines(
    wal_pos: WalPosition | None,
) -> list[str]:
    """Render WAL position and recovery-state lines."""
    lines: list[str] = []
    if wal_pos is not None:
        role = "standby" if wal_pos.is_in_recovery else "primary"
        lsn = wal_pos.current_wal_lsn or "?"
        lines.append(
            f"WAL position: role={role} current_lsn={lsn}"
        )
        if wal_pos.is_in_recovery:
            lines.append(
                f"  receive_lsn={wal_pos.last_wal_receive_lsn}"
                f" replay_lsn={wal_pos.last_wal_replay_lsn}"
            )
    return lines


def _repl_replica_lines(
    replicas: list[ReplicationReplica] | None,
) -> list[str]:
    """Render streaming replica state and lag lines."""
    lines: list[str] = []
    if replicas is not None:
        if not replicas:
            lines.append(
                "Streaming replicas: none connected at snapshot."
            )
        else:
            lines.append(
                f"Streaming replicas: {len(replicas)} connected"
            )
            for r in replicas:
                t_lag = (
                    f"{r.replay_lag_s / 60:.1f} min"
                    if r.replay_lag_s is not None
                    else "n/a"
                )
                b_lag = (
                    f"{r.lsn_lag_bytes // (1024 * 1024)} MiB"
                    if r.lsn_lag_bytes is not None
                    else "n/a"
                )
                lines.append(
                    f"  {r.application_name} "
                    f"({r.client_addr}) "
                    f"state={r.state} "
                    f"sync={r.sync_state} "
                    f"replay_lag={t_lag} "
                    f"byte_lag={b_lag}"
                )
    return lines


def _repl_receiver_lines(
    receiver: WalReceiver | None,
) -> list[str]:
    """Render the WAL receiver status line for a standby."""
    lines: list[str] = []
    if receiver is not None:
        lines.append(
            f"WAL receiver: status={receiver.status} "
            f"primary={receiver.sender_host}:"
            f"{receiver.sender_port}"
            + (
                f" slot={receiver.slot_name}"
                if receiver.slot_name
                else ""
            )
        )
    return lines


def _repl_slot_lines(
    slots: ReplicationSlots | None,
) -> list[str]:
    """Render replication slot status lines."""
    lines: list[str] = []
    if slots is not None:
        if not slots.all:
            lines.append(
                "Replication slots: none configured."
            )
        else:
            lines.append(
                f"Replication slots ({len(slots.all)} total):"
            )
            for s in slots.all:
                active = "active" if s.active else "INACTIVE"
                db = f" db={s.database}" if s.database else ""
                lines.append(
                    f"  {s.slot_name} [{s.slot_type}]{db} "
                    f"status={s.wal_status or '?'} "
                    f"{active} "
                    f"restart_lsn={s.restart_lsn or '?'}"
                )
    return lines


def _repl_subscription_lines(
    subs: list[Subscription] | None,
) -> list[str]:
    """Render logical subscription worker lines."""
    lines: list[str] = []
    if subs is not None:
        if not subs:
            lines.append("Logical subscriptions: none.")
        else:
            lines.append(
                f"Logical subscriptions: {len(subs)}"
            )
            for sub in subs:
                running = (
                    f"running (pid={sub.pid})"
                    if sub.pid is not None
                    else "NOT RUNNING"
                )
                lines.append(
                    f"  {sub.subname}: {running}"
                )
    return lines


def _repl_origin_lines(
    origins: list[ReplicationOrigin] | None,
) -> list[str]:
    """Render replication origin progress lines."""
    lines: list[str] = []
    if origins:
        lines.append(
            f"Replication origins: {len(origins)}"
        )
        for o in origins:
            lines.append(
                f"  {o.external_id} "
                f"remote_lsn={o.remote_lsn} "
                f"local_lsn={o.local_lsn}"
            )
    return lines


def _repl_publication_lines(parsed: dict[str, Any]) -> list[str]:
    """Render per-database publication table membership lines."""
    # Names the LLM can cite when summarising what's actually
    # replicated.
    lines: list[str] = []
    pub_tables_by_db: dict[str, list[Any]] = (
        parsed.get("pg.db.publication_tables") or {}
    )
    if any(pub_tables_by_db.values()):
        lines.append("Publications (per database):")
        for db, rows in sorted(pub_tables_by_db.items()):
            if not rows:
                continue
            by_pub: dict[str, list[str]] = {}
            for row in rows:
                by_pub.setdefault(row.pubname, []).append(
                    row.fqname
                )
            for pub, members in sorted(by_pub.items()):
                shown = ", ".join(sorted(members)[:5])
                extra = (
                    f" (+{len(members) - 5} more)"
                    if len(members) > 5
                    else ""
                )
                lines.append(
                    f"  {db}/{pub}: {shown}{extra}"
                )
    return lines


def _repl_sub_state_lines(parsed: dict[str, Any]) -> list[str]:
    """Render per-database subscription state summaries."""
    lines: list[str] = []
    sub_tables_by_db: dict[str, list[Any]] = (
        parsed.get("pg.db.subscription_tables") or {}
    )
    if any(sub_tables_by_db.values()):
        lines.append("Subscription state (per database):")
        for db, rows in sorted(sub_tables_by_db.items()):
            if not rows:
                continue
            by_state: dict[str, int] = {}
            for row in rows:
                key = row.state_label
                by_state[key] = by_state.get(key, 0) + 1
            summary = ", ".join(
                f"{state}: {n}"
                for state, n in sorted(by_state.items())
            )
            lines.append(
                f"  {db}: {len(rows)} rel(s): {summary}"
            )
    return lines


def _build_replication_facts(
    parsed: dict[str, Any],
) -> str | None:
    """Compact facts block for the Replication category.

    Combines WAL position, replication slots, streaming replicas
    (pg_stat_replication), WAL receiver state (on standbys),
    logical subscription workers, and replication origins. Returns
    None only when all sources are absent (so the LLM call is
    short-circuited to UNKNOWN rather than producing a hallucinated
    assessment).
    """
    slots: ReplicationSlots | None = parsed.get(
        "pg.replication_slots"
    )
    replicas: list[ReplicationReplica] | None = parsed.get(
        "pg.replication"
    )
    wal_pos: WalPosition | None = parsed.get("pg.wal_position")
    receiver: WalReceiver | None = parsed.get("pg.wal_receiver")
    subs: list[Subscription] | None = parsed.get(
        "pg.subscriptions"
    )
    origins: list[ReplicationOrigin] | None = parsed.get(
        "pg.replication_origin"
    )

    if all(
        v is None
        for v in (
            slots,
            replicas,
            wal_pos,
            receiver,
            subs,
            origins,
        )
    ):
        return None

    lines: list[str] = []
    lines.extend(_repl_wal_position_lines(wal_pos))
    lines.extend(_repl_replica_lines(replicas))
    lines.extend(_repl_receiver_lines(receiver))
    lines.extend(_repl_slot_lines(slots))
    lines.extend(_repl_subscription_lines(subs))
    lines.extend(_repl_origin_lines(origins))
    lines.extend(_repl_publication_lines(parsed))
    lines.extend(_repl_sub_state_lines(parsed))
    return "\n".join(lines) if lines else None


# Facts builder per Category.key.
_CATEGORY_BUILDERS: dict[
    str, Callable[[dict[str, Any]], str | None]
] = {
    "host_os": _build_host_os_facts,
    "pg_config": _build_pg_config_facts,
    "pg_workload": _build_workload_facts,
    "pg_health": _build_internals_facts,
    "pg_replication": _build_replication_facts,
}


def build_category_facts(
    cat: Category, parsed: dict[str, Any]
) -> str | None:
    """Return a compact facts block for *cat*, or None if no data.

    None is the signal that the orchestrator should skip the LLM
    call and persist an UNKNOWN placeholder: we'd rather say "we
    haven't collected this yet" than ask the LLM to hallucinate an
    assessment from an empty prompt.
    """
    builder = _CATEGORY_BUILDERS.get(cat.key)
    return builder(parsed) if builder is not None else None


def _db_schema_lines(db: dict[str, Any]) -> list[str]:
    """Render the schema summary and extensions lines."""
    lines: list[str] = []
    tc = db.get("table_count")
    ic = db.get("index_count")
    if tc is not None or ic is not None:
        parts: list[str] = []
        if tc is not None:
            parts.append(f"{tc} tables")
        if ic is not None:
            parts.append(f"{ic} indexes")
        lines.append(f"Schema: {', '.join(parts)}")
    exts = db.get("extensions") or []
    if exts:
        lines.append(f"Extensions: {', '.join(exts)}")
    return lines


def build_db_facts(db: dict[str, Any]) -> str:
    """Build a compact facts block for a single database summary.

    Used as the ``facts`` argument to *render_db_user_prompt*. Only
    includes fields that are meaningful to the LLM (not findings,
    severity, or internal bookkeeping).
    """
    lines: list[str] = []
    size = db.get("size") or ""
    if size:
        lines.append(f"Size: {size}")
    # Activity counters
    backends = db.get("active_sessions") or 0
    lines.append(f"Active sessions: {backends}")
    chr_ = db.get("cache_hit_ratio")
    if chr_ is not None:
        lines.append(f"Cache hit ratio: {chr_:.4f}")
    deadlocks = db.get("deadlocks") or 0
    lines.append(f"Deadlocks: {deadlocks}")
    tf = db.get("temp_files") or 0
    tb = db.get("temp_bytes") or 0
    if tf > 0:
        lines.append(
            f"Temp files: {tf}"
            + (f" ({tb:,} bytes)" if tb > 0 else "")
        )
    # Tuple I/O
    for col in (
        "tup_returned", "tup_fetched",
        "tup_inserted", "tup_updated", "tup_deleted",
    ):
        val = db.get(col) or 0
        if val > 0:
            lines.append(f"{col}: {val:,}")
    lines.extend(_db_schema_lines(db))
    return "\n".join(lines)
