"""Parsers for Host & OS diagnostic files.

Covers:
- ``system/proc/pressure_{cpu,io,memory}.out``: Linux PSI
- ``system/iostat.out``: iostat device utilisation
- ``system/cgroup/memory_{current,max,stat}.out``: cgroup v2 memory
- ``system/dmesg.out`` / ``system/dmesg_t.out``: kernel log
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# PSI (Pressure Stall Information)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PsiLine:
    """One line from a PSI pressure file (some or full)."""

    avg10: float
    avg60: float
    avg300: float
    total: int


@dataclass(frozen=True)
class PsiPressure:
    """Contents of a ``/proc/pressure/*`` file."""

    some: PsiLine
    full: PsiLine | None  # CPU has no 'full' line on some kernels


_PSI_RE = re.compile(
    r"(?:some|full)\s+"
    r"avg10=([\d.]+)\s+"
    r"avg60=([\d.]+)\s+"
    r"avg300=([\d.]+)\s+"
    r"total=(\d+)"
)


def _parse_psi_line(text: str) -> PsiLine | None:
    m = _PSI_RE.search(text)
    if m is None:
        return None
    try:
        return PsiLine(
            avg10=float(m.group(1)),
            avg60=float(m.group(2)),
            avg300=float(m.group(3)),
            total=int(m.group(4)),
        )
    except ValueError:
        return None


def parse_pressure(data: bytes) -> PsiPressure | None:
    """Parse a ``/proc/pressure/*`` file.

    Returns ``None`` for empty input or if the ``some`` line
    cannot be parsed.
    """
    text = data.decode("utf-8", errors="replace")
    some: PsiLine | None = None
    full: PsiLine | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("some"):
            some = _parse_psi_line(stripped)
        elif stripped.startswith("full"):
            full = _parse_psi_line(stripped)
    if some is None:
        return None
    return PsiPressure(some=some, full=full)


# ---------------------------------------------------------------------------
# iostat
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IostatDevice:
    """Per-device row from ``iostat`` output."""

    device: str
    util_pct: float | None  # %util column; None when absent


def _iostat_header(
    lines: list[str],
) -> tuple[int | None, int | None]:
    """Index of the Device header line and of its %util column."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("Device"):
            continue
        util_col = next(
            (
                idx
                for idx, col in enumerate(stripped.split())
                if col in ("%util", "util")
            ),
            None,
        )
        return i, util_col
    return None, None


def _iostat_rows(
    lines: list[str], util_col: int | None
) -> list[IostatDevice]:
    """Device rows after the header, first interval only.

    A second ``Device`` header starts a new iostat interval, so
    reading stops there.
    """
    out: list[IostatDevice] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Device"):
            break
        parts = stripped.split()
        util: float | None = None
        if util_col is not None and util_col < len(parts):
            with contextlib.suppress(ValueError):
                util = float(parts[util_col])
        out.append(
            IostatDevice(device=parts[0], util_pct=util)
        )
    return out


def parse_iostat(data: bytes) -> list[IostatDevice] | None:
    """Parse ``system/iostat.out``.

    Returns ``None`` for completely empty input. Returns ``[]``
    when there is no device section (avg-cpu header only).
    Handles the ``%util`` column regardless of how many other
    columns precede it.
    """
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    lines = text.splitlines()
    header_idx, util_col = _iostat_header(lines)
    if header_idx is None:
        return []
    return _iostat_rows(lines[header_idx + 1:], util_col)


# ---------------------------------------------------------------------------
# cgroup v2 memory files (single-line byte values)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CgroupMemoryStat:
    """The file page cache counters of a cgroup v2 ``memory.stat``."""
    active_file: int
    inactive_file: int

    @property
    def page_cache(self) -> int:
        """File page cache, which the kernel reclaims before OOM.

        shmem, where PostgreSQL's shared_buffers live, is swap-backed
        and kept on the anonymous lists, so it is not part of it.
        """
        return self.active_file + self.inactive_file


def parse_cgroup_memory_stat(data: bytes) -> CgroupMemoryStat | None:
    """Parse ``memory.stat``; None without its file page counters."""
    counters: dict[str, int] = {}
    for line in data.decode("utf-8", errors="replace").splitlines():
        key, _, value = line.partition(" ")
        if value.strip().isdigit():
            counters[key] = int(value)
    if "active_file" not in counters or "inactive_file" not in counters:
        return None
    return CgroupMemoryStat(
        active_file=counters["active_file"],
        inactive_file=counters["inactive_file"],
    )


def parse_cgroup_memory_bytes(data: bytes) -> int | None:
    """Parse a cgroup v2 single-value memory file.

    Returns ``None`` for:
    - Empty input
    - The literal string ``"max"`` (unlimited)
    - Non-integer content

    Otherwise returns the integer byte value.
    """
    text = data.decode("utf-8", errors="replace").strip()
    if not text or text == "max":
        return None
    try:
        return int(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# dmesg
# ---------------------------------------------------------------------------

# Patterns that indicate OOM killer activity.
_OOM_PATTERNS = re.compile(
    r"Out of memory|oom_kill|Killed process|"
    r"oom-killer|memory cgroup out of memory",
    re.IGNORECASE,
)

# Patterns that indicate I/O or storage errors.
_IO_ERROR_PATTERNS = re.compile(
    r"I/O error|blk_update_request|EXT4-fs error|"
    r"BTRFS.*error|XFS.*error|SCSI error|"
    r"end_request.*I/O error|Buffer I/O error",
    re.IGNORECASE,
)

_MAX_SAMPLE_LINES = 5


@dataclass
class DmesgSummary:
    """Aggregated signal from a dmesg log."""

    oom_count: int = 0
    io_error_count: int = 0
    oom_lines: list[str] = field(default_factory=list)
    io_error_lines: list[str] = field(default_factory=list)


def parse_dmesg(data: bytes) -> DmesgSummary:
    """Parse ``system/dmesg.out``.

    Always returns a ``DmesgSummary`` (never None). Counts matching
    lines and retains up to 5 sample lines per bucket for the LLM
    facts block.
    """
    summary = DmesgSummary()
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if _OOM_PATTERNS.search(line):
            summary.oom_count += 1
            if len(summary.oom_lines) < _MAX_SAMPLE_LINES:
                summary.oom_lines.append(line.strip())
        if _IO_ERROR_PATTERNS.search(line):
            summary.io_error_count += 1
            if len(summary.io_error_lines) < _MAX_SAMPLE_LINES:
                summary.io_error_lines.append(line.strip())
    return summary
