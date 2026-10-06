"""Deterministic rules for the Host & OS category."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from radar_analyst.analyze.eol import OS_EOL
from radar_analyst.parse.diskspace import DiskFilesystem
from radar_analyst.parse.host_os import DmesgSummary, IostatDevice, PsiPressure
from radar_analyst.parse.loadavg import LoadAverage
from radar_analyst.parse.swaps import SwapDevice
from radar_analyst.parse.system_facts import cpu_count_from_lscpu
from radar_analyst.rules.base import (
    Finding,
    register,
    tier,
    top_n,
)


# Thresholds
_CGROUP_MEM_WARN_RATIO = 0.80    # 80 % of cgroup memory limit
_PRESSURE_MEMORY_WARN = 25.0     # avg300 > 25 % stall time
_PRESSURE_IO_WARN = 10.0         # full avg300 > 10 % stall time
_IOSTAT_WARN_PCT = 80.0
_IOSTAT_CRIT_PCT = 95.0
# Filesystem capacity thresholds. 80% gives the operator runway
# to react; 95% is "WAL or temp_files will start failing soon".
_DISK_USE_WARN_PCT = 80
_DISK_USE_CRIT_PCT = 95
# Memory: warn when MemAvailable / MemTotal is below 15% (i.e.
# "memory used %" > 85). PSI memory is a stronger leading
# indicator (covered separately); this is the absolute view.
_MEM_USE_WARN_PCT = 85.0
# Load average is reported as a multiplier of available CPU
# parallelism. 1.5× cores warns; 4× cores is critical.
_LOAD_AVG_WARN_MULTIPLIER = 1.5
_LOAD_AVG_CRIT_MULTIPLIER = 4.0

# Linux's default vm.swappiness is 60. Postgres workloads
# typically want 1–10: leave a tiny tail of swap willingness for
# emergency situations but never proactively swap database pages.
_SWAPPINESS_WARN = 10

# I/O schedulers known to be poor fits for database workloads.
# ``cfq`` and ``bfq`` reorder writes for fairness, which hurts
# Postgres' write patterns; ``deadline`` (single-queue) is fine
# but legacy. Modern good defaults: ``none`` for NVMe,
# ``mq-deadline`` or ``kyber`` for SATA SSDs.
_BAD_SCHEDULERS = frozenset({"cfq", "bfq"})
_GOOD_SCHEDULERS = frozenset(
    {"none", "mq-deadline", "kyber", "deadline"}
)


@register("Host & OS")
def transparent_hugepage_always(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when THP is set to always."""
    thp = parsed.get("sys.sys.transparent_hugepage")
    if thp != "always":
        return []
    return [
        Finding(
            rule_id="sys.transparent_hugepage_enabled",
            severity="warning",
            title=(
                "Transparent Huge Pages is set to 'always'"
            ),
            detail=(
                "THP 'always' is a well-known source of "
                "latency spikes on PostgreSQL hosts: the "
                "kernel's khugepaged scan can pause a busy "
                "backend mid-query. Set /sys/kernel/mm/"
                "transparent_hugepage/enabled to 'madvise' or "
                "'never' (via the tuned profile or a systemd "
                "one-shot on boot)."
            ),
        )
    ]


@register("Host & OS")
def scaling_governor_not_performance(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when the CPU scaling governor is not 'performance'.

    Governors like ``powersave``, ``ondemand``, or ``schedutil``
    vary CPU frequency under load, causing P-state transitions that
    add latency jitter to PostgreSQL backends. A dedicated database
    host should use the ``performance`` governor (fixed max
    frequency) or at minimum ``ondemand`` with aggressive
    thresholds.
    """
    governor: str | None = parsed.get(
        "sys.sys.cpu_scaling_governor"
    )
    if governor is None or governor == "performance":
        return []
    return [
        Finding(
            rule_id="sys.scaling_governor",
            severity="warning",
            title=(
                f"CPU scaling governor is '{governor}', "
                "not 'performance'"
            ),
            detail=(
                f"The CPU frequency governor is set to "
                f"'{governor}'. Variable-frequency governors "
                "cause P-state transitions under load, adding "
                "latency jitter to PostgreSQL query execution. "
                "Set to 'performance' for a dedicated database "
                "host: echo performance | tee "
                "/sys/devices/system/cpu/cpu*/cpufreq/"
                "scaling_governor, or configure via tuned."
            ),
        )
    ]


@register("Host & OS")
def cgroup_memory_near_limit(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when cgroup v2 memory usage exceeds 80 % of the limit.

    A PostgreSQL process in a container or cgroup with a memory
    limit near capacity risks OOM termination. ``memory_max`` of
    ``None`` means unlimited: no finding is generated.
    """
    current: int | None = parsed.get("sys.cgroup.memory_current")
    limit: int | None = parsed.get("sys.cgroup.memory_max")
    if current is None or limit is None:
        return []
    ratio = current / limit
    if ratio < _CGROUP_MEM_WARN_RATIO:
        return []
    pct = ratio * 100
    current_gib = current / (1024 ** 3)
    limit_gib = limit / (1024 ** 3)
    return [
        Finding(
            rule_id="sys.cgroup_memory_near_limit",
            severity="warning",
            title=(
                f"cgroup memory usage at {pct:.0f}% of limit "
                f"({current_gib:.1f} / {limit_gib:.1f} GiB)"
            ),
            detail=(
                f"The process cgroup is using "
                f"{current_gib:.1f} GiB of its "
                f"{limit_gib:.1f} GiB memory limit "
                f"({pct:.0f}%). If usage continues to grow "
                "PostgreSQL will be OOM-killed. Consider "
                "increasing the cgroup memory limit, reducing "
                "shared_buffers, or migrating to a host with "
                "more RAM."
            ),
        )
    ]


@register("Host & OS")
def pressure_memory_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when memory pressure ``some.avg300`` exceeds 25 %.

    PSI memory pressure above 25 % on a 5-minute average means the
    host is regularly stalling waiting for memory reclaim. On a
    PostgreSQL host this typically leads to backend latency spikes
    and increased checkpoint pressure.
    """
    pressure: PsiPressure | None = parsed.get(
        "sys.proc.pressure_memory"
    )
    if pressure is None:
        return []
    if pressure.some.avg300 <= _PRESSURE_MEMORY_WARN:
        return []
    return [
        Finding(
            rule_id="sys.pressure_memory_high",
            severity="warning",
            title=(
                f"Memory pressure avg300 = "
                f"{pressure.some.avg300:.1f}% "
                f"(threshold {_PRESSURE_MEMORY_WARN}%)"
            ),
            detail=(
                f"Linux PSI reports memory stall time of "
                f"{pressure.some.avg300:.1f}% over the last "
                "5 minutes. The OS is spending significant "
                "time reclaiming memory, which stalls "
                "PostgreSQL backends. Check for memory "
                "overcommit, large sorts spilling to disk, "
                "or another process competing for RAM."
            ),
        )
    ]


@register("Host & OS")
def pressure_io_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when I/O pressure ``full.avg300`` exceeds 10 %.

    PSI I/O ``full`` pressure tracks time when ALL tasks are
    stalled on I/O: a strong signal that the storage subsystem
    is saturated. On a PostgreSQL host this directly delays WAL
    fsync, checkpoint writes, and random-read buffer misses.
    """
    pressure: PsiPressure | None = parsed.get(
        "sys.proc.pressure_io"
    )
    if pressure is None or pressure.full is None:
        return []
    if pressure.full.avg300 <= _PRESSURE_IO_WARN:
        return []
    return [
        Finding(
            rule_id="sys.pressure_io_high",
            severity="warning",
            title=(
                f"I/O pressure (full) avg300 = "
                f"{pressure.full.avg300:.1f}% "
                f"(threshold {_PRESSURE_IO_WARN}%)"
            ),
            detail=(
                f"Linux PSI reports full I/O stall time of "
                f"{pressure.full.avg300:.1f}% over the last "
                "5 minutes. All tasks on this host are "
                "periodically blocked waiting for I/O, which "
                "delays WAL fsync and checkpoint I/O. "
                "Investigate iostat for saturated devices and "
                "consider faster storage or I/O scheduling "
                "tuning."
            ),
        )
    ]


@register("Host & OS")
def dmesg_has_oom_kill(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Critical when the kernel OOM killer fired recently.

    An OOM kill on a PostgreSQL host means at least one process
    was terminated for memory pressure. If PostgreSQL itself was
    killed, the cluster will have restarted; if another process
    was killed, the pressure that caused it may still be present.
    """
    summary: DmesgSummary | None = parsed.get("sys.dmesg")
    if summary is None or summary.oom_count == 0:
        return []
    sample = (
        "; ".join(summary.oom_lines[:3])
        if summary.oom_lines
        else ""
    )
    return [
        Finding(
            rule_id="sys.dmesg_oom_kill",
            severity="critical",
            title=(
                f"OOM killer fired {summary.oom_count} time(s) "
                "in dmesg"
            ),
            detail=(
                f"The kernel OOM killer has fired "
                f"{summary.oom_count} time(s). Sample: "
                f"{sample}. If PostgreSQL was killed, the "
                "cluster will have crash-recovered. Increase "
                "available memory, reduce shared_buffers or "
                "work_mem, or add a cgroup memory limit to "
                "protect the PostgreSQL process."
            ),
        )
    ]


@register("Host & OS")
def dmesg_has_io_error(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when dmesg contains storage I/O errors.

    Block-layer I/O errors indicate potential storage hardware
    failure, filesystem corruption, or transient SCSI/NVMe issues.
    On a PostgreSQL host these errors can cause WAL corruption or
    data loss if they occur during a write.
    """
    summary: DmesgSummary | None = parsed.get("sys.dmesg")
    if summary is None or summary.io_error_count == 0:
        return []
    sample = (
        "; ".join(summary.io_error_lines[:3])
        if summary.io_error_lines
        else ""
    )
    return [
        Finding(
            rule_id="sys.dmesg_io_error",
            severity="warning",
            title=(
                f"Storage I/O errors in dmesg "
                f"({summary.io_error_count} occurrence(s))"
            ),
            detail=(
                f"dmesg contains {summary.io_error_count} "
                "storage I/O error line(s). Sample: "
                f"{sample}. Run smartctl / nvme smart-log on "
                "affected devices to check drive health, and "
                "inspect the filesystem for corruption "
                "(fsck / xfs_repair)."
            ),
        )
    ]


@register("Host & OS")
def iostat_device_saturation(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn / critical when any storage device exceeds %util threshold.

    Device %util > 80% signals the storage is near saturation;
    > 95% means it is the bottleneck for every I/O request. On
    a PostgreSQL host this manifests as slow checkpoints, WAL
    sync delays, and read amplification for buffer misses.
    """
    devices: list[IostatDevice] | None = parsed.get("sys.iostat")
    if not devices:
        return []
    hot = [
        d for d in devices
        if d.util_pct is not None
        and d.util_pct >= _IOSTAT_WARN_PCT
    ]
    if not hot:
        return []
    # Every item in hot guaranteed util_pct is not None.
    worst = max(
        hot,
        key=lambda d: d.util_pct,  # type: ignore[arg-type,return-value]
    )
    sev = (
        "critical"
        if worst.util_pct >= _IOSTAT_CRIT_PCT  # type: ignore[operator]
        else "warning"
    )
    names = ", ".join(
        f"{d.device} ({d.util_pct:.0f}%)" for d in hot
    )
    return [
        Finding(
            rule_id="sys.iostat_saturation",
            severity=sev,
            title=(
                f"{len(hot)} storage device(s) near saturation: "
                f"{names}"
            ),
            detail=(
                f"Device(s) with %util ≥ {_IOSTAT_WARN_PCT}%: "
                f"{names}. Device saturation directly delays "
                "PostgreSQL WAL writes, checkpoints, and "
                "buffer-miss reads. Investigate I/O patterns "
                "with iotop, consider faster storage, or "
                "distribute I/O across multiple devices."
            ),
        )
    ]


@register("Host & OS")
def swap_on_db_host(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when any swap device is configured."""
    swaps: list[SwapDevice] | None = parsed.get("sys.proc.swaps")
    if not swaps:
        return []
    total_kib = sum(d.size_kib for d in swaps)
    total_gib = total_kib / (1024 * 1024)
    return [
        Finding(
            rule_id="sys.swap_on_pg_host",
            severity="warning",
            title=(
                f"Swap is configured ({total_gib:.1f} GiB "
                "total) on a PostgreSQL host"
            ),
            detail=(
                "PostgreSQL assumes no swap: a paged-out "
                "buffer leads to unpredictable latency and "
                "misleading shared_buffers cache-hit metrics. "
                "If this is a dedicated database host, disable "
                "swap (swapoff -a + remove from /etc/fstab). "
                "If this is a shared workload, keep "
                "vm.swappiness at 1 and monitor SwapUsed."
            ),
        )
    ]


@register("Host & OS")
def swappiness_high(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when vm.swappiness is above the database-friendly cap.

    Default Linux is 60; database hosts typically want 1–10.
    """
    sysctl: dict[str, str] | None = parsed.get("sys.sysctl")
    if not sysctl:
        return []
    raw = sysctl.get("vm.swappiness")
    if raw is None:
        return []
    try:
        value = int(raw)
    except ValueError:
        return []
    if value <= _SWAPPINESS_WARN:
        return []
    return [
        Finding(
            rule_id="sys.swappiness_high",
            severity="warning",
            title=f"vm.swappiness = {value}",
            detail=(
                f"vm.swappiness = {value} encourages the kernel "
                "to evict Postgres pages under memory pressure. "
                "On dedicated database hosts the recommended "
                "range is 1–10 (lower if swap is configured "
                "only as an emergency overflow)."
            ),
        )
    ]


@register("Host & OS")
def overcommit_memory_misconfigured(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when vm.overcommit_memory is not set to 2.

    Mode 2 (never overcommit) is what Postgres documentation
    recommends: it lets backends fail allocation cleanly
    instead of getting OOM-killed. Skip the check on
    containerised hosts: overcommit is a host-kernel setting
    and the container's view doesn't reflect what's actually
    in effect.
    """
    sysctl: dict[str, str] | None = parsed.get("sys.sysctl")
    if not sysctl:
        return []
    if parsed.get("sys.is_container"):
        return []
    raw = sysctl.get("vm.overcommit_memory")
    if raw is None:
        return []
    try:
        value = int(raw)
    except ValueError:
        return []
    if value == 2:
        return []
    return [
        Finding(
            rule_id="sys.overcommit_memory_misconfigured",
            severity="warning",
            title=(
                f"vm.overcommit_memory = {value} (recommended: 2)"
            ),
            detail=(
                "Postgres recommends vm.overcommit_memory = 2 "
                "(never overcommit) so that allocation failures "
                "surface as ENOMEM instead of triggering the OOM "
                "killer (which can pick the postmaster). With "
                "mode 2, also tune vm.overcommit_ratio "
                "(typical: 50–80) for the host's RAM + swap "
                "budget."
            ),
        )
    ]


@register("Host & OS")
def io_scheduler_suboptimal(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when block devices use legacy I/O schedulers.

    pgEdge's guidance is to use ``none`` on NVMe and
    ``mq-deadline`` or ``kyber`` on SATA SSDs. ``cfq`` /
    ``bfq`` reorder writes for fairness in ways that hurt
    database write patterns.
    """
    sched: dict[str, str] | None = parsed.get(
        "sys.io_schedulers"
    )
    if not sched:
        return []
    bad: list[tuple[str, str]] = [
        (dev, name)
        for dev, name in sched.items()
        if name in _BAD_SCHEDULERS
    ]
    if not bad:
        return []
    examples = ", ".join(
        f"{dev}={name}" for dev, name in bad
    )
    return [
        Finding(
            rule_id="sys.io_scheduler_suboptimal",
            severity="warning",
            title=(
                f"{len(bad)} device(s) using a legacy I/O "
                "scheduler"
            ),
            detail=(
                f"Block devices on suboptimal schedulers: "
                f"{examples}. Switch to ``none`` (NVMe) or "
                "``mq-deadline``/``kyber`` (SATA SSD): "
                "echo into ``/sys/block/<dev>/queue/scheduler`` "
                "or set the udev rule for persistence."
            ),
        )
    ]


_OS_EOL_WARN_WINDOW = timedelta(days=180)


def _normalise_os_version(value: str) -> str:
    """Strip the .x patch suffix where the EOL table key omits it.

    /etc/os-release frequently reports e.g. "9.4" or
    "20.04.6 LTS"; the EOL table is keyed on "9" or "20.04".
    """
    cleaned = value.strip().split()[0] if value.strip() else ""
    if "." not in cleaned:
        return cleaned
    parts = cleaned.split(".")
    # RHEL-family: keep only the major.
    if len(parts) >= 2 and parts[1].isdigit() and len(parts) > 1:
        # "9.4" -> "9", "20.04.6" -> "20.04"
        if parts[0] in ("18", "19", "20", "21", "22", "23",
                        "24", "25"):
            return ".".join(parts[:2])
        return parts[0]
    return cleaned


@register("Host & OS")
def os_version_eol(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when the host OS release is near or past EOL.

    Past EOL → critical; within 6 months → warning.
    """
    osr: dict[str, str] | None = parsed.get("sys.os_release")
    if not osr:
        return []
    osid = (osr.get("ID") or "").strip().strip('"').lower()
    version = _normalise_os_version(
        osr.get("VERSION_ID") or ""
    )
    if not osid or not version:
        return []
    eol = OS_EOL.get((osid, version))
    if eol is None:
        return []
    today = date.today()
    pretty_name = (
        osr.get("PRETTY_NAME")
        or osr.get("NAME")
        or f"{osid} {version}"
    ).strip().strip('"')
    if today > eol:
        return [
            Finding(
                rule_id="sys.os_version_eol",
                severity="critical",
                title=(
                    f"{pretty_name} is past end-of-life "
                    f"(was {eol.isoformat()})"
                ),
                detail=(
                    "Past-EOL operating systems no longer "
                    "receive security patches from the "
                    "vendor. Plan a host migration / OS "
                    "upgrade."
                ),
            )
        ]
    if today + _OS_EOL_WARN_WINDOW >= eol:
        return [
            Finding(
                rule_id="sys.os_version_eol",
                severity="warning",
                title=(
                    f"{pretty_name} EOL on "
                    f"{eol.isoformat()}"
                ),
                detail=(
                    f"{pretty_name} reaches vendor "
                    "end-of-life within 6 months "
                    f"({eol.isoformat()}). Plan the host "
                    "migration / OS upgrade now."
                ),
            )
        ]
    return []


@register("Host & OS")
def disk_usage_high(parsed: dict[str, Any]) -> list[Finding]:
    """Warn / critical when any real-disk filesystem is near full.

    Pseudo filesystems (tmpfs, devtmpfs, overlay, squashfs) are
    pre-filtered by the parser. Threshold: warn ≥ 80%, crit ≥ 95%.
    """
    fs_list: list[DiskFilesystem] | None = parsed.get(
        "sys.diskspace"
    )
    if not fs_list:
        return []
    crit: list[DiskFilesystem] = [
        fs for fs in fs_list
        if fs.use_pct >= _DISK_USE_CRIT_PCT
    ]
    warn: list[DiskFilesystem] = [
        fs for fs in fs_list
        if _DISK_USE_WARN_PCT <= fs.use_pct < _DISK_USE_CRIT_PCT
    ]
    if not crit and not warn:
        return []
    severity = "critical" if crit else "warning"
    offenders = sorted(
        crit + warn, key=lambda f: -f.use_pct
    )
    examples, suffix = top_n(
        offenders,
        lambda f: (
            f"{f.mountpoint} ({f.use_pct}% of {f.size}, "
            f"{f.avail} free)"
        ),
    )
    return [
        Finding(
            rule_id="sys.disk_usage_high",
            severity=severity,
            title=(
                f"{len(offenders)} filesystem(s) ≥ "
                f"{_DISK_USE_WARN_PCT}% full"
            ),
            detail=(
                f"{examples}{suffix}. A full data-directory "
                "or pg_wal mount stops writes; a full archive "
                "destination stops WAL archiving and risks "
                "pg_wal filling next."
            ),
        )
    ]


@register("Host & OS")
def memory_usage_high(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when MemAvailable is below ~15 % of MemTotal.

    PSI memory pressure (covered separately) is the better
    leading indicator; this is the absolute snapshot view in
    case PSI is unavailable or hasn't yet surfaced sustained
    stalls.
    """
    meminfo: dict[str, int] | None = parsed.get(
        "sys.proc.meminfo"
    )
    if not meminfo:
        return []
    total = meminfo.get("MemTotal")
    avail = meminfo.get("MemAvailable")
    if not total or avail is None:
        return []
    used_pct = (1.0 - avail / total) * 100.0
    if used_pct < _MEM_USE_WARN_PCT:
        return []
    return [
        Finding(
            rule_id="sys.memory_usage_high",
            severity="warning",
            title=(
                f"Memory used = {used_pct:.0f}% of "
                f"{total // (1024 * 1024)} MiB"
            ),
            detail=(
                f"MemAvailable = {avail // (1024 * 1024)} MiB; "
                "the host is running out of headroom for the "
                "page cache, work_mem allocations, and "
                "transient buffers. Cross-check with PSI "
                "memory and process-level top consumers; "
                "tune work_mem / shared_buffers if Postgres "
                "is the dominant user, or reduce co-tenant "
                "load."
            ),
        )
    ]


@register("Host & OS")
def load_average_high(parsed: dict[str, Any]) -> list[Finding]:
    """Warn / critical on load15 vs CPU count.

    Load average is normalised by the number of CPUs available
    on the host (from ``sys.lscpu``), because an absolute
    threshold is CPU-count-blind and scales poorly across
    hardware sizes.
    """
    la: LoadAverage | None = parsed.get("sys.proc.loadavg")
    if la is None:
        return []
    cpu_count = cpu_count_from_lscpu(
        parsed.get("sys.lscpu") or {}
    )
    if cpu_count <= 0:
        return []
    ratio = la.load15 / cpu_count
    sev = tier(
        ratio,
        warn=_LOAD_AVG_WARN_MULTIPLIER,
        crit=_LOAD_AVG_CRIT_MULTIPLIER,
    )
    if sev is None:
        return []
    return [
        Finding(
            rule_id="sys.load_average_high",
            severity=sev,
            title=(
                f"15-min load average {la.load15:.2f} on "
                f"{cpu_count} CPU(s) ({ratio:.1f}× cores)"
            ),
            detail=(
                f"load1 = {la.load1:.2f}, load5 = "
                f"{la.load5:.2f}, load15 = {la.load15:.2f}. "
                "Sustained load above the CPU count means "
                "tasks are queuing for CPU or for I/O. "
                "Cross-check with PSI CPU / I/O and "
                "iostat saturation to identify whether "
                "the bottleneck is compute or storage."
            ),
        )
    ]
