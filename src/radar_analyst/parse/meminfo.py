"""Parse ``system/proc/meminfo.out`` (raw ``/proc/meminfo`` contents).

Each line is ``Key: value [unit]``. For size-like fields the unit is
``kB``: those are normalized to **bytes** here so downstream consumers
don't have to think about units. Count-like fields (``HugePages_*``) are
kept as raw integers. Malformed lines are silently dropped.
"""

from __future__ import annotations


def parse_meminfo(data: bytes) -> dict[str, int]:
    """Return ``{key: value}``: bytes for kB-units, raw count otherwise."""
    out: dict[str, int] = {}
    for line in data.decode("utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        parts = rest.split()
        if not parts:
            continue
        try:
            num = int(parts[0])
        except ValueError:
            continue
        if len(parts) >= 2 and parts[1] == "kB":
            out[key] = num * 1024
        elif len(parts) == 1:
            out[key] = num
        # Unknown unit suffix → skip (defensive).
    return out
