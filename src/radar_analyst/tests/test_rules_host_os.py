"""Tests for rules/host_os.py.

Covers all eight rules in the module.
"""

from __future__ import annotations

import pytest

from radar_analyst.parse.host_os import (
    CgroupMemoryStat,
    DmesgSummary,
    IostatDevice,
    PsiLine,
    PsiPressure,
)
from radar_analyst.parse.swaps import SwapDevice
from radar_analyst.rules.host_os import (
    cgroup_memory_near_limit,
    dmesg_has_io_error,
    dmesg_has_oom_kill,
    iostat_device_saturation,
    pressure_io_high,
    pressure_memory_high,
    scaling_governor_not_performance,
    swap_on_db_host,
    transparent_hugepage_always,
)


# ---------------------------------------------------------------
# Existing rules regression guard
# ---------------------------------------------------------------

def test_transparent_hugepage_warns_on_always() -> None:
    parsed = {"sys.sys.transparent_hugepage": "always"}
    out = transparent_hugepage_always(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"


def test_swap_warns_when_swap_configured() -> None:
    parsed = {
        "sys.proc.swaps": [
            SwapDevice(
                name="/dev/sda2",
                kind="partition",
                size_kib=8388608,
                used_kib=0,
            )
        ]
    }
    out = swap_on_db_host(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"


# ---------------------------------------------------------------
# scaling_governor_not_performance
# ---------------------------------------------------------------

def test_scaling_governor_warns_on_powersave() -> None:
    parsed = {"sys.sys.cpu_scaling_governor": "powersave"}
    out = scaling_governor_not_performance(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "sys.scaling_governor"


def test_scaling_governor_warns_on_schedutil() -> None:
    parsed = {"sys.sys.cpu_scaling_governor": "schedutil"}
    out = scaling_governor_not_performance(parsed)
    assert len(out) == 1


def test_scaling_governor_silent_on_performance() -> None:
    parsed = {"sys.sys.cpu_scaling_governor": "performance"}
    assert scaling_governor_not_performance(parsed) == []


def test_scaling_governor_silent_when_no_data() -> None:
    assert scaling_governor_not_performance({}) == []


# ---------------------------------------------------------------
# cgroup_memory_near_limit
# ---------------------------------------------------------------

def _cgroup(
    current_gib: float, limit_gib: float | None, cache_gib: float = 0
) -> dict[str, object]:
    gib = 1024 * 1024 * 1024
    return {
        "sys.cgroup.memory_current": int(current_gib * gib),
        "sys.cgroup.memory_max": (
            None if limit_gib is None else int(limit_gib * gib)
        ),
        "sys.cgroup.memory_stat": CgroupMemoryStat(
            active_file=0, inactive_file=int(cache_gib * gib)
        ),
    }


def test_cgroup_memory_warns_at_80pct() -> None:
    out = cgroup_memory_near_limit(_cgroup(8, 10))
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "sys.cgroup_memory_near_limit"


def test_cgroup_memory_silent_below_80pct() -> None:
    assert cgroup_memory_near_limit(_cgroup(7, 10)) == []


def test_cgroup_memory_leaves_out_page_cache() -> None:
    assert cgroup_memory_near_limit(_cgroup(10, 10, cache_gib=4)) == []


def test_cgroup_memory_silent_when_max_is_none() -> None:
    # max=None means unlimited: no limit to check against.
    assert cgroup_memory_near_limit(_cgroup(1, None)) == []


def test_cgroup_memory_silent_without_memory_stat() -> None:
    # Without memory.stat, page cache cannot be told from the rest.
    parsed = _cgroup(10, 10)
    del parsed["sys.cgroup.memory_stat"]
    assert cgroup_memory_near_limit(parsed) == []


def test_cgroup_memory_silent_when_no_data() -> None:
    assert cgroup_memory_near_limit({}) == []


# ---------------------------------------------------------------
# pressure_memory_high
# ---------------------------------------------------------------

def _psi(some_avg300: float, full_avg300: float = 0.0) -> PsiPressure:
    return PsiPressure(
        some=PsiLine(
            avg10=0.0, avg60=0.0, avg300=some_avg300, total=0
        ),
        full=PsiLine(
            avg10=0.0, avg60=0.0, avg300=full_avg300, total=0
        ),
    )


def test_pressure_memory_warns_above_threshold() -> None:
    parsed = {"sys.proc.pressure_memory": _psi(30.0)}
    out = pressure_memory_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "sys.pressure_memory_high"


def test_pressure_memory_silent_below_threshold() -> None:
    parsed = {"sys.proc.pressure_memory": _psi(10.0)}
    assert pressure_memory_high(parsed) == []


def test_pressure_memory_silent_when_no_data() -> None:
    assert pressure_memory_high({}) == []


# ---------------------------------------------------------------
# pressure_io_high
# ---------------------------------------------------------------

def test_pressure_io_warns_above_threshold() -> None:
    parsed = {"sys.proc.pressure_io": _psi(0.0, full_avg300=15.0)}
    out = pressure_io_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "sys.pressure_io_high"


def test_pressure_io_silent_below_threshold() -> None:
    parsed = {"sys.proc.pressure_io": _psi(0.0, full_avg300=5.0)}
    assert pressure_io_high(parsed) == []


def test_pressure_io_silent_when_full_is_none() -> None:
    # Some metrics sources (older kernels) may not have a full line.
    pressure = PsiPressure(
        some=PsiLine(avg10=0.0, avg60=0.0, avg300=50.0, total=0),
        full=None,
    )
    parsed = {"sys.proc.pressure_io": pressure}
    assert pressure_io_high(parsed) == []


def test_pressure_io_silent_when_no_data() -> None:
    assert pressure_io_high({}) == []


# ---------------------------------------------------------------
# dmesg_has_oom_kill
# ---------------------------------------------------------------

def test_dmesg_oom_critical_when_count_positive() -> None:
    summary = DmesgSummary(
        oom_count=2,
        io_error_count=0,
        oom_lines=["kernel: Out of memory: Kill process 1234"],
        io_error_lines=[],
    )
    parsed = {"sys.dmesg": summary}
    out = dmesg_has_oom_kill(parsed)
    assert len(out) == 1
    assert out[0].severity == "critical"
    assert out[0].rule_id == "sys.dmesg_oom_kill"


def test_dmesg_oom_silent_when_count_zero() -> None:
    summary = DmesgSummary(
        oom_count=0,
        io_error_count=0,
        oom_lines=[],
        io_error_lines=[],
    )
    parsed = {"sys.dmesg": summary}
    assert dmesg_has_oom_kill(parsed) == []


def test_dmesg_oom_silent_when_no_data() -> None:
    assert dmesg_has_oom_kill({}) == []


# ---------------------------------------------------------------
# dmesg_has_io_error
# ---------------------------------------------------------------

def test_dmesg_io_error_warns_when_count_positive() -> None:
    summary = DmesgSummary(
        oom_count=0,
        io_error_count=3,
        oom_lines=[],
        io_error_lines=["blk_update_request: I/O error, dev sda"],
    )
    parsed = {"sys.dmesg": summary}
    out = dmesg_has_io_error(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "sys.dmesg_io_error"


def test_dmesg_io_error_silent_when_count_zero() -> None:
    summary = DmesgSummary(
        oom_count=0,
        io_error_count=0,
        oom_lines=[],
        io_error_lines=[],
    )
    assert dmesg_has_io_error({"sys.dmesg": summary}) == []


def test_dmesg_io_error_silent_when_no_data() -> None:
    assert dmesg_has_io_error({}) == []


# ---------------------------------------------------------------
# iostat_device_saturation
# ---------------------------------------------------------------

def _dev(device: str, util_pct: float) -> IostatDevice:
    return IostatDevice(device=device, util_pct=util_pct)


def test_iostat_warns_above_80pct() -> None:
    parsed = {
        "sys.iostat": [_dev("sda", 85.0), _dev("sdb", 20.0)]
    }
    out = iostat_device_saturation(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "sys.iostat_saturation"
    assert "sda" in out[0].title or "sda" in out[0].detail


def test_iostat_critical_above_95pct() -> None:
    parsed = {"sys.iostat": [_dev("nvme0n1", 97.0)]}
    out = iostat_device_saturation(parsed)
    assert len(out) == 1
    assert out[0].severity == "critical"


def test_iostat_silent_below_threshold() -> None:
    parsed = {"sys.iostat": [_dev("sda", 70.0)]}
    assert iostat_device_saturation(parsed) == []


def test_iostat_silent_when_util_none() -> None:
    parsed = {
        "sys.iostat": [IostatDevice(device="sda", util_pct=None)]
    }
    assert iostat_device_saturation(parsed) == []


def test_iostat_silent_when_no_data() -> None:
    assert iostat_device_saturation({}) == []


# ----------------------------------------------------------------------
# swappiness_high
# ----------------------------------------------------------------------


def test_swappiness_high_silent_under_threshold() -> None:
    from radar_analyst.rules.host_os import swappiness_high

    parsed = {"sys.sysctl": {"vm.swappiness": "10"}}
    assert swappiness_high(parsed) == []


def test_swappiness_high_warns_at_default_60() -> None:
    from radar_analyst.rules.host_os import swappiness_high

    parsed = {"sys.sysctl": {"vm.swappiness": "60"}}
    findings = swappiness_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "60" in findings[0].title


def test_swappiness_high_silent_when_no_data() -> None:
    from radar_analyst.rules.host_os import swappiness_high

    assert swappiness_high({}) == []
    assert swappiness_high({"sys.sysctl": {}}) == []


# ----------------------------------------------------------------------
# overcommit_memory_misconfigured
# ----------------------------------------------------------------------


def test_overcommit_silent_when_two() -> None:
    from radar_analyst.rules.host_os import (
        overcommit_memory_misconfigured,
    )

    parsed = {"sys.sysctl": {"vm.overcommit_memory": "2"}}
    assert overcommit_memory_misconfigured(parsed) == []


def test_overcommit_warns_on_default_zero() -> None:
    from radar_analyst.rules.host_os import (
        overcommit_memory_misconfigured,
    )

    parsed = {"sys.sysctl": {"vm.overcommit_memory": "0"}}
    findings = overcommit_memory_misconfigured(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_overcommit_skipped_inside_container() -> None:
    from radar_analyst.rules.host_os import (
        overcommit_memory_misconfigured,
    )

    parsed = {
        "sys.sysctl": {"vm.overcommit_memory": "0"},
        "sys.is_container": True,
    }
    assert overcommit_memory_misconfigured(parsed) == []


# ----------------------------------------------------------------------
# io_scheduler_suboptimal
# ----------------------------------------------------------------------


def test_io_scheduler_silent_on_modern_defaults() -> None:
    from radar_analyst.rules.host_os import io_scheduler_suboptimal

    parsed = {
        "sys.io_schedulers": {
            "nvme0n1": "none",
            "sda": "mq-deadline",
        }
    }
    assert io_scheduler_suboptimal(parsed) == []


def test_io_scheduler_warns_on_cfq() -> None:
    from radar_analyst.rules.host_os import io_scheduler_suboptimal

    parsed = {
        "sys.io_schedulers": {
            "sda": "cfq",
            "sdb": "mq-deadline",
        }
    }
    findings = io_scheduler_suboptimal(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "sda=cfq" in findings[0].detail


def test_io_scheduler_silent_when_no_data() -> None:
    from radar_analyst.rules.host_os import io_scheduler_suboptimal

    assert io_scheduler_suboptimal({}) == []


# ----------------------------------------------------------------------
# os_version_eol
# ----------------------------------------------------------------------


def test_os_eol_silent_when_unknown_distro() -> None:
    from radar_analyst.rules.host_os import os_version_eol

    parsed = {
        "sys.os_release": {
            "ID": "obscuredistro",
            "VERSION_ID": "1.0",
        }
    }
    assert os_version_eol(parsed) == []


def test_os_eol_critical_for_centos_7(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    import radar_analyst.rules.host_os as mod

    class _Fixed(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            return date(2026, 1, 1)

    monkeypatch.setattr(mod, "date", _Fixed)
    parsed = {
        "sys.os_release": {
            "ID": "centos",
            "VERSION_ID": "7",
            "PRETTY_NAME": "CentOS Linux 7 (Core)",
        }
    }
    findings = mod.os_version_eol(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "critical"


def test_os_eol_warning_within_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    import radar_analyst.rules.host_os as mod

    class _Fixed(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            # 5 months before Ubuntu 20.04 EOL (2025-05-29)
            return date(2024, 12, 29)

    monkeypatch.setattr(mod, "date", _Fixed)
    parsed = {
        "sys.os_release": {
            "ID": "ubuntu",
            "VERSION_ID": "20.04",
            "PRETTY_NAME": "Ubuntu 20.04 LTS",
        }
    }
    findings = mod.os_version_eol(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_os_eol_handles_minor_in_version_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    import radar_analyst.rules.host_os as mod

    class _Fixed(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            return date(2026, 1, 1)

    monkeypatch.setattr(mod, "date", _Fixed)
    parsed = {
        "sys.os_release": {
            "ID": "rhel",
            "VERSION_ID": "9.4",
        }
    }
    # 9.4 normalises to 9; EOL 2032-05-31 is far away → silent.
    assert mod.os_version_eol(parsed) == []


# ----------------------------------------------------------------------
# disk_usage_high
# ----------------------------------------------------------------------


def test_disk_usage_silent_below_threshold() -> None:
    from radar_analyst.parse.diskspace import DiskFilesystem
    from radar_analyst.rules.host_os import disk_usage_high

    parsed = {
        "sys.diskspace": [
            DiskFilesystem(
                filesystem="/dev/sda1",
                mountpoint="/",
                use_pct=70,
                size="100G",
                used="70G",
                avail="30G",
            ),
        ]
    }
    assert disk_usage_high(parsed) == []


def test_disk_usage_warns_at_80pct() -> None:
    from radar_analyst.parse.diskspace import DiskFilesystem
    from radar_analyst.rules.host_os import disk_usage_high

    parsed = {
        "sys.diskspace": [
            DiskFilesystem(
                filesystem="/dev/sda1",
                mountpoint="/",
                use_pct=85,
                size="100G",
                used="85G",
                avail="15G",
            ),
        ]
    }
    findings = disk_usage_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_disk_usage_critical_at_95pct() -> None:
    from radar_analyst.parse.diskspace import DiskFilesystem
    from radar_analyst.rules.host_os import disk_usage_high

    parsed = {
        "sys.diskspace": [
            DiskFilesystem(
                filesystem="/dev/root",
                mountpoint="/",
                use_pct=97,
                size="158G",
                used="150G",
                avail="5.6G",
            ),
        ]
    }
    findings = disk_usage_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "critical"


def test_disk_usage_silent_when_no_data() -> None:
    from radar_analyst.rules.host_os import disk_usage_high

    assert disk_usage_high({}) == []
    assert disk_usage_high({"sys.diskspace": []}) == []


# ----------------------------------------------------------------------
# memory_usage_high
# ----------------------------------------------------------------------


def test_memory_usage_warns_above_85pct() -> None:
    from radar_analyst.rules.host_os import memory_usage_high

    gib = 1024 * 1024
    parsed = {
        "sys.proc.meminfo": {
            "MemTotal": 16 * gib,
            "MemAvailable": 1 * gib,  # 6.25% available → 93% used
        }
    }
    findings = memory_usage_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_memory_usage_silent_with_headroom() -> None:
    from radar_analyst.rules.host_os import memory_usage_high

    gib = 1024 * 1024
    parsed = {
        "sys.proc.meminfo": {
            "MemTotal": 16 * gib,
            "MemAvailable": 8 * gib,  # 50% used
        }
    }
    assert memory_usage_high(parsed) == []


def test_memory_usage_silent_when_no_data() -> None:
    from radar_analyst.rules.host_os import memory_usage_high

    assert memory_usage_high({}) == []
    assert memory_usage_high({"sys.proc.meminfo": {}}) == []


# ----------------------------------------------------------------------
# load_average_high
# ----------------------------------------------------------------------


def test_load_average_silent_below_warn() -> None:
    from radar_analyst.parse.loadavg import LoadAverage
    from radar_analyst.rules.host_os import load_average_high

    parsed = {
        "sys.proc.loadavg": LoadAverage(1.0, 1.0, 4.0),
        "sys.lscpu": {"CPU(s)": "8"},  # 4 / 8 = 0.5× cores
    }
    assert load_average_high(parsed) == []


def test_load_average_warns_at_1_5x_cores() -> None:
    from radar_analyst.parse.loadavg import LoadAverage
    from radar_analyst.rules.host_os import load_average_high

    parsed = {
        "sys.proc.loadavg": LoadAverage(1.0, 1.0, 12.0),
        "sys.lscpu": {"CPU(s)": "8"},  # 12 / 8 = 1.5× cores
    }
    findings = load_average_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_load_average_critical_at_4x_cores() -> None:
    from radar_analyst.parse.loadavg import LoadAverage
    from radar_analyst.rules.host_os import load_average_high

    parsed = {
        "sys.proc.loadavg": LoadAverage(1.0, 1.0, 32.0),
        "sys.lscpu": {"CPU(s)": "8"},  # 32 / 8 = 4× cores
    }
    findings = load_average_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "critical"


def test_load_average_silent_when_no_cpu_count() -> None:
    from radar_analyst.parse.loadavg import LoadAverage
    from radar_analyst.rules.host_os import load_average_high

    parsed = {
        "sys.proc.loadavg": LoadAverage(1.0, 1.0, 100.0),
    }
    assert load_average_high(parsed) == []


def test_load_average_silent_when_no_data() -> None:
    from radar_analyst.rules.host_os import load_average_high

    assert load_average_high({}) == []
