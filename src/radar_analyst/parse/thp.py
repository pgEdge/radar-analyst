"""Parse radar's transparent-hugepage dump.

Radar stores this as a flat "path:value" listing of every file
under ``/sys/kernel/mm/transparent_hugepage/``, not just the root
``enabled`` file. For example::

    .../hugepages-32kB/enabled:always inherit madvise [never]
    .../transparent_hugepage/enabled:always [madvise] never
    .../transparent_hugepage/defrag:...

We want the ROOT ``transparent_hugepage/enabled`` line: the per-
size-subdir entries describe a different setting. The active mode
is the token in square brackets; return it as a bare string, or
None if we can't identify the root line.
"""

from __future__ import annotations

import re


_BRACKETS_RE = re.compile(r"\[([a-z_]+)\]")


def parse_thp(data: bytes) -> str | None:
    """The selected transparent_hugepage mode."""
    for line in data.decode(
        "utf-8", errors="replace"
    ).splitlines():
        # The root line ends in "/transparent_hugepage/enabled:".
        # Per-hugepage-size subdirs are under hugepages-NNkB/enabled.
        if (
            "/transparent_hugepage/enabled:" not in line
            or "/hugepages-" in line
        ):
            continue
        m = _BRACKETS_RE.search(line)
        if m:
            return m.group(1)
    return None
