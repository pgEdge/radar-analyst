"""Deterministic rules for the "PostgreSQL Configuration" category."""

from __future__ import annotations

from typing import Any

from datetime import date, timedelta

from radar_analyst.analyze.eol import PG_MAJOR_EOL
from radar_analyst.parse.extensions import AvailableExtensions
from radar_analyst.parse.pg_settings import PgSetting, PgSettings
from radar_analyst.parse.system_facts import cpu_count_from_lscpu
from radar_analyst.parse.pg_version import PgVersionInfo
from radar_analyst.rules.base import Finding, register

_SHARED_BUFFERS_MIN_RATIO = 0.10
_SHARED_BUFFERS_MAX_RATIO = 0.40

# Maintenance work_mem default is 64 MiB. On hosts with significant
# RAM that's painfully small for VACUUM / REINDEX / CREATE INDEX.
_MAINT_WORK_MEM_LOW_BYTES = 128 * 1024 * 1024  # 128 MiB
_MAINT_WORK_MEM_RAM_FLOOR = 16 * (1024 ** 3)   # 16 GiB

# Default max_wal_size = 1 GiB; on busy clusters that triggers
# requested checkpoints frequently. We don't second-guess if the
# operator already raised it; we just flag the default-with-bursty.
_MAX_WAL_SIZE_DEFAULT_BYTES = 1024 * 1024 * 1024  # 1 GiB

# Default checkpoint_timeout is 5 min. Anything shorter forces
# pg to checkpoint too aggressively on a busy cluster.
_CHECKPOINT_TIMEOUT_MIN_S = 5 * 60

# Extensions that radar-analyst flags as "essential" when missing
# from shared_preload_libraries on any non-trivial workload.
# pg_stat_statements is the only library worth recommending as
# always-on: it has minimal overhead and is the foundation of
# every query-level workload investigation. Diagnostic libraries
# like auto_explain are intentionally excluded: they're for
# short-term troubleshooting, not permanent preloading.
_ESSENTIAL_PRELOAD_LIBS = ("pg_stat_statements",)

# pg_settings rows report values in the unit advertised by the unit
# column. These cover the common cases for memory-related settings.
_UNIT_MULTIPLIERS: dict[str, int] = {
    "": 1,
    "B": 1,
    "kB": 1024,
    "8kB": 8 * 1024,
    "MB": 1024 * 1024,
    "GB": 1024 * 1024 * 1024,
}


# Time-unit conversions for GUCs whose unit is "ms"/"s"/"min".
_TIME_UNIT_SECONDS: dict[str, float] = {
    "": 1.0,
    "s": 1.0,
    "ms": 0.001,
    "min": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}


def _value_to_seconds(setting: str, unit: str) -> float | None:
    try:
        n = float(setting)
    except ValueError:
        return None
    mul = _TIME_UNIT_SECONDS.get(unit)
    if mul is None:
        return None
    return n * mul


def _value_to_bytes(setting: str, unit: str) -> int | None:
    try:
        n = int(setting)
    except ValueError:
        return None
    mul = _UNIT_MULTIPLIERS.get(unit)
    if mul is None:
        return None
    return n * mul


_ON_VALUES = frozenset(
    {"on", "true", "yes", "1"}
)
_SYNC_COMMIT_SAFE = frozenset(
    {"on", "remote_apply", "remote_write"}
)


def _is_on(value: str) -> bool:
    return value.lower() in _ON_VALUES


def _get_settings(parsed: dict[str, Any]) -> PgSettings | None:
    """The parsed pg_settings table, or None when uncollected."""
    settings: PgSettings | None = parsed.get("pg.settings")
    return settings


def _off_setting(
    parsed: dict[str, Any], guc: str
) -> PgSetting | None:
    """Return the GUC's row when present and off, else None."""
    settings = _get_settings(parsed)
    if settings is None:
        return None
    s = settings.get(guc)
    if s is None or _is_on(s.setting):
        return None
    return s


@register("PostgreSQL Configuration")
def fsync_off(parsed: dict[str, Any]) -> list[Finding]:
    """Critical if fsync is disabled: durability is gone."""
    s = _off_setting(parsed, "fsync")
    if s is None:
        return []
    return [
        Finding(
            rule_id="pg.config.fsync_off",
            severity="critical",
            title="fsync is disabled",
            detail=(
                f"fsync = {s.setting}. Data durability is "
                "NOT guaranteed across crashes. Set fsync = on "
                "unless this is a disposable instance."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def synchronous_commit_off(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn if synchronous_commit is weakened or off."""
    settings = _get_settings(parsed)
    if settings is None:
        return []
    s = settings.get("synchronous_commit")
    if s is None:
        return []
    if s.setting.lower() in _SYNC_COMMIT_SAFE:
        return []
    severity = (
        "critical" if s.setting.lower() == "off"
        else "warning"
    )
    return [
        Finding(
            rule_id="pg.config.synchronous_commit_off",
            severity=severity,
            title=(
                "synchronous_commit is weaker than on"
            ),
            detail=(
                f"synchronous_commit = {s.setting}. "
                "Committed transactions can be lost in a crash. "
                "Use 'on' (or 'remote_write'/'remote_apply' with "
                "replication) unless the trade-off is deliberate."
            ),
        )
    ]


def _mcx_description(
    n: int, cpu_count: int, exceeds_cpu_multiplier: bool
) -> tuple[str, list[str]]:
    """Title and detail fragments for max_connections_high."""
    bits: list[str] = [f"max_connections = {n}"]
    if exceeds_cpu_multiplier:
        bits.append(
            f"is more than 4× the {cpu_count} CPU cores on "
            f"this host"
        )
    elif n >= 500:
        bits.append("is high in absolute terms")
    else:
        bits.append("is elevated")
    title_suffix = (
        " (over 4× CPU cores)"
        if exceeds_cpu_multiplier and n < 500
        else ""
    )
    title = f"max_connections = {n} is high{title_suffix}"
    return title, bits


@register("PostgreSQL Configuration")
def max_connections_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Flag unusually high max_connections without a pooler.

    Severity:
    - silent below 200,
    - info from 200 up to (but excluding) 500 when the value
      is also within 4× the CPU count,
    - warning when the value reaches 500, OR when it exceeds
      4× the system CPU count regardless of absolute size.

    The CPU multiplier captures that 500 connections on a 4-core
    VM is a serious mistake while 500 on a 256-core box may be
    reasonable; the absolute 500 floor catches the common
    "too many backends for a single instance, period" case.
    CPU count is read from ``parsed["sys.lscpu"]["CPU(s)"]``;
    if absent the multiplier check is skipped.
    """
    settings = _get_settings(parsed)
    if settings is None:
        return []
    s = settings.get("max_connections")
    if s is None:
        return []
    try:
        n = int(s.setting)
    except ValueError:
        return []
    if n < 200:
        return []
    cpu_count = cpu_count_from_lscpu(
        parsed.get("sys.lscpu") or {}
    )
    exceeds_cpu_multiplier = (
        cpu_count > 0 and n > 4 * cpu_count
    )
    is_warning = n >= 500 or exceeds_cpu_multiplier
    severity = "warning" if is_warning else "info"
    title, bits = _mcx_description(
        n, cpu_count, exceeds_cpu_multiplier
    )
    return [
        Finding(
            rule_id="pg.config.max_connections_high",
            severity=severity,
            title=title,
            detail=(
                ", ".join(bits) + ". Each backend consumes "
                "memory and scheduling capacity; sizing "
                "max_connections in proportion to CPU cores "
                "(typically 2–4× cores plus headroom for the "
                "pooler) keeps context-switch overhead and "
                "work_mem footprint sane. For values >200 "
                "consider a connection pooler (PgBouncer) in "
                "front of PostgreSQL rather than provisioning "
                "for peak backend count."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def work_mem_risk(parsed: dict[str, Any]) -> list[Finding]:
    """Warn if work_mem × max_connections could blow the RAM budget."""
    settings = _get_settings(parsed)
    meminfo: dict[str, int] | None = parsed.get(
        "sys.proc.meminfo"
    )
    if settings is None or not meminfo:
        return []
    wm = settings.get("work_mem")
    mc = settings.get("max_connections")
    mem_total = meminfo.get("MemTotal")
    if wm is None or mc is None or not mem_total:
        return []
    wm_bytes = _value_to_bytes(wm.setting, wm.unit)
    try:
        conns = int(mc.setting)
    except ValueError:
        return []
    if wm_bytes is None:
        return []
    worst = wm_bytes * conns
    ratio = worst / mem_total
    if ratio < 0.30:
        return []
    worst_gib = worst / (1024**3)
    ram_gib = mem_total / (1024**3)
    return [
        Finding(
            rule_id="pg.config.work_mem_risk",
            severity="warning",
            title=(
                "work_mem × max_connections could exceed 30% of RAM"
            ),
            detail=(
                f"work_mem = {wm.setting} {wm.unit}, "
                f"max_connections = {conns}. Worst-case ~"
                f"{worst_gib:.1f} GiB ({ratio * 100:.0f}% of "
                f"{ram_gib:.1f} GiB RAM). Lower work_mem, or "
                "cap concurrency via PgBouncer, or rely on "
                "role/database SET statements for ad-hoc workers."
            ),
        )
    ]


_DEBUG_LOG_LEVELS = frozenset(
    {"debug1", "debug2", "debug3", "debug4", "debug5"}
)


@register("PostgreSQL Configuration")
def track_counts_off(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when track_counts is disabled.

    Without ``track_counts``, autovacuum has no idea which tables need
    work, statistics views are blank, and bloat / dead-tuple
    monitoring stops functioning.
    """
    s = _off_setting(parsed, "track_counts")
    if s is None:
        return []
    return [
        Finding(
            rule_id="pg.config.track_counts_off",
            severity="warning",
            title="track_counts is disabled",
            detail=(
                f"track_counts = {s.setting}. Autovacuum and the "
                "pg_stat_* views rely on it. Re-enable unless this "
                "is a deliberate, short-lived diagnostic toggle."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def enable_indexscan_off(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when enable_indexscan has been disabled at cluster level."""
    s = _off_setting(parsed, "enable_indexscan")
    if s is None:
        return []
    return [
        Finding(
            rule_id="pg.config.enable_indexscan_off",
            severity="warning",
            title="enable_indexscan is disabled",
            detail=(
                f"enable_indexscan = {s.setting}. Cluster-wide off "
                "forces sequential scans and is almost never the "
                "right setting outside short ad-hoc planner "
                "experiments."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def enable_indexonlyscan_off(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when enable_indexonlyscan has been disabled."""
    s = _off_setting(parsed, "enable_indexonlyscan")
    if s is None:
        return []
    return [
        Finding(
            rule_id="pg.config.enable_indexonlyscan_off",
            severity="warning",
            title="enable_indexonlyscan is disabled",
            detail=(
                f"enable_indexonlyscan = {s.setting}. The planner "
                "is forced to hit the heap even when a covering "
                "index would answer the query: a measurable "
                "performance loss for read-heavy workloads."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def excessive_logging(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when logging GUCs are configured to flood the log.

    Aggregates three independent checks into one finding so the
    operator gets a single actionable item:

    - ``log_statement`` in {all, mod}: every (mutating) statement
    - ``log_min_duration_statement = 0``: every statement timed
    - ``log_min_messages`` at DEBUG level
    """
    settings = _get_settings(parsed)
    if settings is None:
        return []
    offenders: list[str] = []
    s = settings.get("log_statement")
    if s is not None and s.setting.lower() in {"all", "mod"}:
        offenders.append(f"log_statement = {s.setting}")
    s = settings.get("log_min_duration_statement")
    if s is not None and s.setting.strip() == "0":
        offenders.append("log_min_duration_statement = 0")
    s = settings.get("log_min_messages")
    if s is not None and s.setting.lower() in _DEBUG_LOG_LEVELS:
        offenders.append(f"log_min_messages = {s.setting}")
    if not offenders:
        return []
    return [
        Finding(
            rule_id="pg.config.excessive_logging",
            severity="warning",
            title="Logging is configured to flood the log",
            detail=(
                "Excessive log GUCs in effect: "
                + "; ".join(offenders)
                + ". High-volume logging hurts throughput and "
                "fills disks. Use targeted logging "
                "(log_min_duration_statement = 250ms; "
                "log_statement = ddl) unless this is a short-"
                "lived diagnostic window."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def outdated_extensions(parsed: dict[str, Any]) -> list[Finding]:
    """Info finding listing extensions with a newer available version.

    Compares each extension's installed version against the highest
    version present in ``pg_available_extension_versions``. The
    operator gets one consolidated finding listing the upgrade
    candidates with their (installed → latest) pairs.
    """
    av: AvailableExtensions | None = parsed.get(
        "pg.available_extensions"
    )
    if av is None:
        return []
    upgradable = sorted(av.outdated(), key=lambda e: e.name)
    if not upgradable:
        return []
    pairs = ", ".join(
        f"{e.name} ({e.installed} → {e.latest})"
        for e in upgradable
    )
    return [
        Finding(
            rule_id="pg.config.outdated_extensions",
            severity="info",
            title=(
                f"{len(upgradable)} installed extension(s) have "
                "a newer version available"
            ),
            detail=(
                f"Upgrade candidates: {pairs}. Run "
                "ALTER EXTENSION <name> UPDATE during a "
                "maintenance window after reviewing each "
                "extension's release notes."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def shared_buffers_low(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn if shared_buffers is under 10% of total RAM.

    This is pgEdge in-house guidance: the classic "25% of RAM"
    figure is folklore. Anything under 10% on a PostgreSQL host is a
    meaningful tuning opportunity; above 10% we don't bother the
    operator.
    """
    settings = _get_settings(parsed)
    meminfo: dict[str, int] | None = parsed.get(
        "sys.proc.meminfo"
    )
    if settings is None or meminfo is None:
        return []

    sb = settings.get("shared_buffers")
    mem_total = meminfo.get("MemTotal")
    if sb is None or not mem_total:
        return []

    sb_bytes = _value_to_bytes(sb.setting, sb.unit)
    if sb_bytes is None:
        return []

    ratio = sb_bytes / mem_total
    if ratio >= _SHARED_BUFFERS_MIN_RATIO:
        return []

    sb_mib = sb_bytes // (1024 * 1024)
    ram_gib = mem_total / (1024**3)
    recommended_gib = max(1, int(ram_gib * 0.10))
    return [
        Finding(
            rule_id="pg.config.shared_buffers_low",
            severity="warning",
            title=(
                "shared_buffers is under 10% of total RAM"
            ),
            detail=(
                f"shared_buffers = {sb_mib} MiB "
                f"({ratio * 100:.2f}% of {ram_gib:.1f} GiB "
                f"RAM). Recommend raising to at least "
                f"{recommended_gib} GiB."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def shared_buffers_high(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when shared_buffers exceeds ~40% of total RAM.

    40% gives the operator a clear "this is probably starving
    the page cache" signal without second-guessing every
    reasonable tuning choice.
    """
    settings = _get_settings(parsed)
    meminfo: dict[str, int] | None = parsed.get(
        "sys.proc.meminfo"
    )
    if settings is None or meminfo is None:
        return []
    sb = settings.get("shared_buffers")
    mem_total = meminfo.get("MemTotal")
    if sb is None or not mem_total:
        return []
    sb_bytes = _value_to_bytes(sb.setting, sb.unit)
    if sb_bytes is None:
        return []
    ratio = sb_bytes / mem_total
    if ratio < _SHARED_BUFFERS_MAX_RATIO:
        return []
    sb_gib = sb_bytes / (1024 ** 3)
    ram_gib = mem_total / (1024 ** 3)
    return [
        Finding(
            rule_id="pg.config.shared_buffers_high",
            severity="warning",
            title=(
                "shared_buffers is over 40% of total RAM"
            ),
            detail=(
                f"shared_buffers = {sb_gib:.1f} GiB "
                f"({ratio * 100:.0f}% of {ram_gib:.1f} GiB "
                "RAM). Above ~40% the OS page cache is "
                "starved and effective_cache_size assumptions "
                "break down. Lower shared_buffers unless you "
                "have profiled this configuration and have a "
                "reason for it."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def maintenance_work_mem_low(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Info when maintenance_work_mem is small on a large host.

    Default 64 MiB is a hard floor for VACUUM / CREATE INDEX
    throughput. On hosts ≥ 16 GiB RAM, anything ≤ 128 MiB is
    leaving easy wins on the table.
    """
    settings = _get_settings(parsed)
    meminfo: dict[str, int] | None = parsed.get(
        "sys.proc.meminfo"
    )
    if settings is None or meminfo is None:
        return []
    mw = settings.get("maintenance_work_mem")
    mem_total = meminfo.get("MemTotal")
    if mw is None or not mem_total:
        return []
    if mem_total < _MAINT_WORK_MEM_RAM_FLOOR:
        return []
    mw_bytes = _value_to_bytes(mw.setting, mw.unit)
    if mw_bytes is None:
        return []
    if mw_bytes > _MAINT_WORK_MEM_LOW_BYTES:
        return []
    mw_mib = mw_bytes // (1024 * 1024)
    ram_gib = mem_total / (1024 ** 3)
    recommended = max(256, int(ram_gib * 16))  # ~16 MiB / GiB
    return [
        Finding(
            rule_id="pg.config.maintenance_work_mem_low",
            severity="info",
            title=(
                f"maintenance_work_mem = {mw_mib} MiB on a "
                f"{ram_gib:.0f} GiB host"
            ),
            detail=(
                f"maintenance_work_mem = {mw_mib} MiB. "
                "VACUUM, CREATE INDEX and ALTER TABLE all "
                "scale with this value. On a host with this "
                "much RAM, raising it to "
                f"{recommended} MiB (or higher for batch "
                "maintenance windows) speeds bulk operations "
                "without affecting steady-state memory use."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def max_wal_size_low(parsed: dict[str, Any]) -> list[Finding]:
    """Info when max_wal_size is at the 1 GiB default.

    Postgres defaults `max_wal_size` to 1 GiB. On busy clusters
    that triggers requested (vs. timed) checkpoints, which
    cause I/O spikes. Doesn't fire if the operator already
    raised the value: we trust their tuning.
    """
    settings = _get_settings(parsed)
    if settings is None:
        return []
    mw = settings.get("max_wal_size")
    if mw is None:
        return []
    bytes_value = _value_to_bytes(mw.setting, mw.unit)
    if bytes_value is None:
        return []
    if bytes_value > _MAX_WAL_SIZE_DEFAULT_BYTES:
        return []
    return [
        Finding(
            rule_id="pg.config.max_wal_size_low",
            severity="info",
            title=(
                f"max_wal_size = {bytes_value // (1024 * 1024)}"
                " MiB (default)"
            ),
            detail=(
                "On a busy cluster the 1 GiB default forces "
                "frequent requested checkpoints, causing "
                "I/O spikes and increased WAL fsync pressure. "
                "Raise to 4–16 GiB to let "
                "checkpoint_timeout drive checkpoint cadence; "
                "watch the bgwriter / checkpointer stats to "
                "confirm fewer requested checkpoints."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def checkpoint_timeout_short(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Info when checkpoint_timeout is below the 5 min default.

    Anything shorter is unusual; flag for the operator to
    confirm it was deliberate.
    """
    settings = _get_settings(parsed)
    if settings is None:
        return []
    s = settings.get("checkpoint_timeout")
    if s is None:
        return []
    seconds = _value_to_seconds(s.setting, s.unit)
    if seconds is None or seconds >= _CHECKPOINT_TIMEOUT_MIN_S:
        return []
    return [
        Finding(
            rule_id="pg.config.checkpoint_timeout_short",
            severity="info",
            title=(
                f"checkpoint_timeout = {s.setting} {s.unit} "
                "(below 5 min)"
            ),
            detail=(
                "Short checkpoint_timeout values force more "
                "frequent full-page writes and increase WAL "
                "volume. The 5-min default is appropriate for "
                "most workloads; values like 15–30 min reduce "
                "I/O pressure on write-heavy clusters. Below "
                "5 min usually only makes sense for "
                "low-write demo systems."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def missing_essential_preload_libs(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when shared_preload_libraries is missing pg_stat_statements.

    `pg_stat_statements` is the only library worth flagging as
    always-on: it's the foundation of any query-level workload
    investigation and has minimal overhead. Diagnostic-only
    libraries (auto_explain) are deliberately not recommended:
    they belong in short-term troubleshooting sessions, not the
    base configuration.
    """
    settings = _get_settings(parsed)
    if settings is None:
        return []
    s = settings.get("shared_preload_libraries")
    if s is None:
        return []
    loaded = {
        piece.strip()
        for piece in s.setting.split(",")
        if piece.strip()
    }
    missing_essential = [
        name
        for name in _ESSENTIAL_PRELOAD_LIBS
        if name not in loaded
    ]
    if not missing_essential:
        return []
    return [
        Finding(
            rule_id="pg.config.missing_essential_preload_libs",
            severity="warning",
            title=(
                "shared_preload_libraries is missing "
                "pg_stat_statements"
            ),
            detail=(
                f"shared_preload_libraries = '{s.setting}'. "
                "Missing: "
                + ", ".join(missing_essential)
                + ". pg_stat_statements is the foundation of "
                "any query-level workload analysis; without "
                "it, slow-query investigation is log-scraping. "
                "Add it to shared_preload_libraries and "
                "restart the cluster."
            ),
        )
    ]


# EOL warning windows: used by `pg_version_eol` below.
_EOL_WARN_WINDOW = timedelta(days=180)  # 6 months


@register("PostgreSQL Configuration")
def pg_version_eol(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when PostgreSQL major is near or past EOL.

    - Past EOL → critical.
    - Within 6 months → warning.
    Otherwise silent. Unknown majors are silent (we'd rather
    miss than hallucinate an EOL date).
    """
    pg: PgVersionInfo | None = parsed.get("pg.version")
    if pg is None or pg.major == 0:
        return []
    eol = PG_MAJOR_EOL.get(pg.major)
    if eol is None:
        return []
    today = date.today()
    if today > eol:
        return [
            Finding(
                rule_id="pg.config.pg_version_eol",
                severity="critical",
                title=(
                    f"PostgreSQL {pg.major} is past "
                    f"end-of-life (was {eol.isoformat()})"
                ),
                detail=(
                    "Past-EOL Postgres receives no security "
                    "or bug fixes from the community. Plan an "
                    "upgrade to a supported major version "
                    "(see postgresql.org/support/versioning)."
                ),
            )
        ]
    if today + _EOL_WARN_WINDOW >= eol:
        return [
            Finding(
                rule_id="pg.config.pg_version_eol",
                severity="warning",
                title=(
                    f"PostgreSQL {pg.major} EOL on "
                    f"{eol.isoformat()}"
                ),
                detail=(
                    "PostgreSQL "
                    f"{pg.major}.{pg.minor} reaches "
                    "community end-of-life within 6 months "
                    f"({eol.isoformat()}). After EOL there "
                    "are no further patches. Plan the major "
                    "upgrade now to avoid running unsupported "
                    "in production."
                ),
            )
        ]
    return []
