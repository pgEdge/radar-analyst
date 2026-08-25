"""Parse ``postgresql/version.tsv`` (output of ``SELECT version()``).

Expected shape:

    version
    PostgreSQL 17.2 on x86_64-pc-linux-gnu, compiled by gcc 13.2.0, 64-bit
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from radar_analyst.parse.tsv import parse_tsv_bytes

_VERSION_RE = re.compile(
    r"PostgreSQL\s+(\d+)(?:\.(\d+))?"
)


@dataclass(frozen=True)
class PgVersionInfo:
    """Parsed server version: raw string plus major."""
    raw: str
    major: int
    minor: int


def parse_version(data: bytes) -> PgVersionInfo | None:
    """Return version info, or ``None`` if the file is absent/empty."""
    table = parse_tsv_bytes(data)
    if "version" not in table.columns or not table.rows:
        return None
    raw = table.rows[0].get("version", "").strip()
    if not raw:
        return None
    m = _VERSION_RE.search(raw)
    if m is None:
        return PgVersionInfo(raw=raw, major=0, minor=0)
    minor = int(m.group(2)) if m.group(2) is not None else 0
    return PgVersionInfo(
        raw=raw, major=int(m.group(1)), minor=minor
    )
