"""Tests for parse/host_os.py: PSI pressure, iostat,
cgroup memory bytes, dmesg summary.
"""

from __future__ import annotations

from radar_analyst.parse.host_os import (
    DmesgSummary,
    IostatDevice,
    PsiPressure,
    parse_cgroup_memory_bytes,
    parse_dmesg,
    parse_iostat,
    parse_pressure,
)


# ---------------------------------------------------------------
# parse_pressure (PSI: /proc/pressure/*)
# ---------------------------------------------------------------

_PRESSURE_MEMORY = (
    b"some avg10=0.00 avg60=0.00 avg300=0.20 total=13180\n"
    b"full avg10=0.00 avg60=0.00 avg300=0.10 total=9496\n"
)

_PRESSURE_CPU = (
    b"some avg10=0.00 avg60=0.33 avg300=0.36 total=344791509\n"
    b"full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
)


def test_parse_pressure_memory_some_line() -> None:
    result = parse_pressure(_PRESSURE_MEMORY)
    assert result is not None
    assert isinstance(result, PsiPressure)
    assert result.some.avg300 == 0.20
    assert result.some.avg10 == 0.00
    assert result.some.total == 13180


def test_parse_pressure_memory_full_line() -> None:
    result = parse_pressure(_PRESSURE_MEMORY)
    assert result is not None
    assert result.full is not None
    assert result.full.avg300 == 0.10
    assert result.full.total == 9496


def test_parse_pressure_cpu_has_some_and_full() -> None:
    # CPU pressure also has a 'full' line.
    result = parse_pressure(_PRESSURE_CPU)
    assert result is not None
    assert result.some.avg300 == 0.36
    assert result.full is not None
    assert result.full.avg300 == 0.00


def test_parse_pressure_empty_returns_none() -> None:
    assert parse_pressure(b"") is None


def test_parse_pressure_some_only() -> None:
    data = b"some avg10=1.00 avg60=2.00 avg300=3.00 total=999\n"
    result = parse_pressure(data)
    assert result is not None
    assert result.some.avg300 == 3.00
    assert result.full is None


# ---------------------------------------------------------------
# parse_iostat
# ---------------------------------------------------------------

_IOSTAT_OUTPUT = (
    "Linux 6.17.0-20-generic (sarlacc)\t15/04/26\t_x86_64_\t"
    "(16 CPU)\n"
    "\n"
    "avg-cpu:  %user   %nice %system %iowait  %steal   %idle\n"
    "           3.97    0.00    1.32    0.01    0.00   94.70\n"
    "\n"
    "Device            r/s     rkB/s   rrqm/s  %rrqm r_await"
    " rareq-sz     w/s     wkB/s   wrqm/s  %wrqm w_await"
    " wareq-sz     d/s     dkB/s   drqm/s  %drqm d_await"
    " dareq-sz     f/s f_await  aqu-sz  %util\n"
    "sda              5.00    200.00     0.00   0.00    1.20"
    "    40.00    3.00    120.00     0.00   0.00    0.80"
    "    40.00    0.00      0.00     0.00   0.00    0.00"
    "     0.00    0.00    0.00    0.00  85.00\n"
    "sdb              1.00     50.00     0.00   0.00    0.50"
    "    50.00    0.50     25.00     0.00   0.00    0.50"
    "    50.00    0.00      0.00     0.00   0.00    0.00"
    "     0.00    0.00    0.00    0.00  10.00\n"
)


def test_parse_iostat_returns_devices() -> None:
    result = parse_iostat(_IOSTAT_OUTPUT.encode())
    assert result is not None
    assert len(result) == 2


def test_parse_iostat_first_device_util() -> None:
    result = parse_iostat(_IOSTAT_OUTPUT.encode())
    assert result is not None
    d = result[0]
    assert isinstance(d, IostatDevice)
    assert d.device == "sda"
    assert d.util_pct is not None
    assert abs(d.util_pct - 85.0) < 0.01


def test_parse_iostat_second_device_util() -> None:
    result = parse_iostat(_IOSTAT_OUTPUT.encode())
    assert result is not None
    d = result[1]
    assert d.device == "sdb"
    assert d.util_pct is not None
    assert abs(d.util_pct - 10.0) < 0.01


def test_parse_iostat_empty_returns_none() -> None:
    assert parse_iostat(b"") is None


def test_parse_iostat_no_device_section_returns_empty() -> None:
    data = (
        b"Linux 6.17.0 (host)\n\n"
        b"avg-cpu:  %user   %nice %system\n"
        b"           3.97    0.00    1.32\n"
    )
    result = parse_iostat(data)
    assert result == []


# ---------------------------------------------------------------
# parse_cgroup_memory_bytes
# ---------------------------------------------------------------

def test_cgroup_memory_bytes_integer() -> None:
    assert parse_cgroup_memory_bytes(b"8589934592\n") == 8589934592


def test_cgroup_memory_bytes_max_returns_none() -> None:
    assert parse_cgroup_memory_bytes(b"max\n") is None


def test_cgroup_memory_bytes_empty_returns_none() -> None:
    assert parse_cgroup_memory_bytes(b"") is None


def test_cgroup_memory_bytes_invalid_returns_none() -> None:
    assert parse_cgroup_memory_bytes(b"not_a_number\n") is None


# ---------------------------------------------------------------
# parse_dmesg
# ---------------------------------------------------------------

_DMESG_CLEAN = b"[1234.0] network interface eth0 up\n"

_DMESG_OOM = (
    b"[1234.0] kernel: Out of memory: Kill process 12345 "
    b"(postgres) score 200 or sacrifice child\n"
    b"[1235.0] kernel: Killed process 12345 (postgres)\n"
)

_DMESG_IO_ERROR = (
    b"[1234.0] blk_update_request: I/O error, dev sda, "
    b"sector 12345\n"
    b"[1235.0] EXT4-fs error (device sda1): ext4_validate_block_bitmap_csum\n"
)

_DMESG_MIXED = _DMESG_OOM + _DMESG_IO_ERROR


def test_parse_dmesg_clean_returns_zero_counts() -> None:
    result = parse_dmesg(_DMESG_CLEAN)
    assert isinstance(result, DmesgSummary)
    assert result.oom_count == 0
    assert result.io_error_count == 0


def test_parse_dmesg_oom_detected() -> None:
    result = parse_dmesg(_DMESG_OOM)
    assert result.oom_count == 2


def test_parse_dmesg_io_error_detected() -> None:
    result = parse_dmesg(_DMESG_IO_ERROR)
    assert result.io_error_count == 2


def test_parse_dmesg_mixed_counts() -> None:
    result = parse_dmesg(_DMESG_MIXED)
    assert result.oom_count == 2
    assert result.io_error_count == 2


def test_parse_dmesg_captures_sample_lines() -> None:
    result = parse_dmesg(_DMESG_OOM)
    assert len(result.oom_lines) > 0
    assert "Out of memory" in result.oom_lines[0]


def test_parse_dmesg_empty_returns_zero_counts() -> None:
    result = parse_dmesg(b"")
    assert result.oom_count == 0
    assert result.io_error_count == 0
