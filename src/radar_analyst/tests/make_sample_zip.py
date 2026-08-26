"""Generate a radar-format sample zip for tests and CI.

The generated archive follows radar's documented layout and value
formatting: TSV values rendered the way radar's ``rowsToTSV``
renders them through Go's ``%v`` (booleans as ``true``/``false``,
NULL as an empty string, timestamps in Go's time format). CI points
``RADAR_SAMPLE_ZIP`` at a generated file so the format-validation
suite always runs; pointing the variable at a real archive instead
exercises the same tests against live radar output.

Usage: ``python -m radar_analyst.tests.make_sample_zip OUT.zip``
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


_VERSION_TSV = (
    "version\n"
    "PostgreSQL 17.2 on x86_64-pc-linux-gnu, compiled by gcc "
    "13.2.0, 64-bit\n"
)

_SYSCTL_OUT = (
    "vm.swappiness = 10\n"
    "vm.overcommit_memory = 2\n"
    "vm.nr_hugepages = 0\n"
    "kernel.shmmax = 18446744073692774399\n"
    "net.core.somaxconn = 4096\n"
)

_MEMINFO_OUT = (
    "MemTotal:       16384000 kB\n"
    "MemFree:         1024000 kB\n"
    "MemAvailable:    8192000 kB\n"
    "Buffers:          128000 kB\n"
    "Cached:          4096000 kB\n"
    "SwapTotal:       0 kB\n"
    "SwapFree:        0 kB\n"
)

_RADAR_OUT = "version: v0.5.0\ncommit: 0000000\n"

# Go's %v rendering of pg_roles booleans: true/false.
_ROLES_TSV = (
    "rolname\trolsuper\trolreplication\trolcanlogin\t"
    "rolvaliduntil\n"
    "postgres\ttrue\ttrue\ttrue\t\n"
    "app\tfalse\tfalse\ttrue\t\n"
)

_DATABASES_TSV = (
    "oid\tdatname\tdatdba\tencoding\tdatcollate\tdatctype\n"
    "5\tpostgres\t10\t6\ten_US.UTF-8\ten_US.UTF-8\n"
)

# Go time.Time %v shape, as radar renders timestamps.
_POSTMASTER_TSV = (
    "pg_postmaster_start_time\n"
    "2026-04-30 10:26:54.03875 +0100 BST\n"
)

# Settings the format-validation tests name explicitly.
_NAMED_SETTINGS = (
    ("shared_buffers", "16384", "8kB"),
    ("max_connections", "100", ""),
    ("wal_level", "replica", ""),
    ("fsync", "on", ""),
    ("work_mem", "4096", "kB"),
)


def _settings_tsv(rows: int = 150) -> str:
    """A pg_settings TSV with realistic width (150+ rows)."""
    lines = ["name\tsetting\tunit\tcategory\tshort_desc"]
    for name, setting, unit in _NAMED_SETTINGS:
        lines.append(
            f"{name}\t{setting}\t{unit}\tSettings\t"
            f"Server setting {name}."
        )
    for i in range(rows):
        lines.append(
            f"generated_setting_{i:03d}\t{i}\t\tSettings\t"
            f"Generated filler setting {i}."
        )
    return "\n".join(lines) + "\n"


def _statviz_tsv(target_bytes: int = 4 * 1024 * 1024) -> str:
    """A pg_statviz time-series TSV of roughly *target_bytes*."""
    header = (
        "snapshot_tstamp\tblks_read\tblks_hit\n"
    )
    row = "2026-04-30 10:26:54 +0000 UTC\t123456\t7890123\n"
    n = max(1, target_bytes // len(row))
    return header + row * n


def build_sample_zip(path: Path) -> Path:
    """Write the sample archive to *path* and return it."""
    with zipfile.ZipFile(
        path, "w", compression=zipfile.ZIP_DEFLATED
    ) as zf:
        zf.writestr("radar.out", _RADAR_OUT)
        zf.writestr("postgresql/version.tsv", _VERSION_TSV)
        zf.writestr(
            "postgresql/configuration.tsv", _settings_tsv()
        )
        zf.writestr("postgresql/roles.tsv", _ROLES_TSV)
        zf.writestr("postgresql/databases.tsv", _DATABASES_TSV)
        zf.writestr(
            "postgresql/postmaster_start_time.tsv",
            _POSTMASTER_TSV,
        )
        zf.writestr("system/sysctl.out", _SYSCTL_OUT)
        zf.writestr("system/proc/meminfo.out", _MEMINFO_OUT)
        zf.writestr(
            "pg_statviz/postgres/buf.tsv", _statviz_tsv()
        )
    return path


def main(argv: list[str]) -> int:
    """CLI entry: write the sample zip to ``argv[1]``."""
    if len(argv) != 2:
        print(
            "usage: python -m "
            "radar_analyst.tests.make_sample_zip OUT.zip",
            file=sys.stderr,
        )
        return 2
    out = build_sample_zip(Path(argv[1]))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
