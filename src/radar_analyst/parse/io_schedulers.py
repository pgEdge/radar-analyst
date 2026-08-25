"""Parse ``system/io_schedulers.out``.

Radar emits one line per block device:

    sda: [mq-deadline] kyber bfq none
    sdb: noop deadline [cfq]

The bracketed entry is the currently-active scheduler. We parse
to ``{device: active_scheduler}`` and ignore the alternatives.
"""

from __future__ import annotations

import re

_LINE_RE = re.compile(r"^(?P<dev>[^:]+):\s*(?P<rest>.+)$")
_ACTIVE_RE = re.compile(r"\[([^\]]+)\]")


def parse_io_schedulers(data: bytes) -> dict[str, str]:
    """Return ``{device: active_scheduler}`` for every line.

    Devices whose schedulers list does not include an active
    bracketed entry (rare: typically empty `none` listings) are
    omitted so consumers don't have to filter sentinel values.
    """
    out: dict[str, str] = {}
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if m is None:
            continue
        active = _ACTIVE_RE.search(m.group("rest"))
        if active is None:
            continue
        device = m.group("dev").strip()
        if device:
            out[device] = active.group(1).strip()
    return out
