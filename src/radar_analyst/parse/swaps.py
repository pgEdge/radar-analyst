"""Parse ``/proc/swaps``: active swap devices.

Format::

    Filename    Type        Size      Used   Priority
    /dev/sda2   partition   8388604   0      -2

Just the header when no swap is active. We return the list of
active devices (name + size in KiB + used KiB).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SwapDevice:
    """One /proc/swaps device row."""
    name: str
    kind: str  # 'partition' | 'file'
    size_kib: int
    used_kib: int


def parse_swaps(data: bytes) -> list[SwapDevice]:
    """Parse /proc/swaps into device rows."""
    out: list[SwapDevice] = []
    for line in data.decode(
        "utf-8", errors="replace"
    ).splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            size = int(parts[2])
            used = int(parts[3])
        except ValueError:
            continue
        out.append(
            SwapDevice(
                name=parts[0],
                kind=parts[1],
                size_kib=size,
                used_kib=used,
            )
        )
    return out
