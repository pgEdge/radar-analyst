"""Parse ``system/diskspace.out`` (output of ``df -h``).

One row per filesystem: ``(filesystem, mountpoint, use_pct, size,
used, avail)``. Pseudo-filesystems (tmpfs, devtmpfs, overlay,
squashfs, etc.) are filtered out: they're not capacity concerns.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiskFilesystem:
    """One df row for a real disk filesystem."""
    filesystem: str
    mountpoint: str
    use_pct: int
    size: str
    used: str
    avail: str


# Filesystem types that don't represent persistent disk capacity.
# Strings are matched against the leading whitespace-trimmed
# ``Filesystem`` column from df.
_PSEUDO_FS_PREFIXES: tuple[str, ...] = (
    "tmpfs",
    "devtmpfs",
    "overlay",
    "squashfs",
    "udev",
    "proc",
    "sysfs",
    "cgroup",
    "none",
)


def _is_pseudo_fs(filesystem: str) -> bool:
    f = filesystem.strip()
    if not f:
        return True
    return any(
        f == p or f.startswith(p + "/") for p in _PSEUDO_FS_PREFIXES
    )


def parse_diskspace(data: bytes) -> list[DiskFilesystem]:
    """Parse ``df -h`` output into a list of real-disk filesystems.

    Parses the fixed column layout ``filesystem size used avail
    use% mountpoint``, where the trailing mountpoint may itself
    contain spaces. Pseudo-filesystems are skipped by device
    name.
    """
    text = data.decode("utf-8", errors="replace")
    out: list[DiskFilesystem] = []
    for raw in text.splitlines()[1:]:  # skip header
        line = raw.rstrip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        # Layout: filesystem size used avail use% mountpoint
        filesystem = parts[0]
        if _is_pseudo_fs(filesystem):
            continue
        size, used, avail, use_pct_raw = parts[1:5]
        mountpoint = " ".join(parts[5:])
        use_pct_str = use_pct_raw.rstrip("%")
        try:
            use_pct = int(use_pct_str)
        except ValueError:
            continue
        out.append(
            DiskFilesystem(
                filesystem=filesystem,
                mountpoint=mountpoint,
                use_pct=use_pct,
                size=size,
                used=used,
                avail=avail,
            )
        )
    return out
