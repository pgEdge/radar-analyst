"""Parse ``radar.out`` from the zip root.

Radar 0.5.0 and later writes a small key/value file at the zip
root identifying the binary that produced the archive::

    version: v0.5.0
    commit: abc1234

Older radar (≤ 0.4.1) doesn't emit the file at all, in which case
the parser returns ``None`` and the orchestrator records
"unknown": rules that depend on 0.5.0+ collector data gate on
the result so they skip silently rather than misfire.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RadarMeta:
    """Radar's version and commit from radar.out."""
    version: str
    commit: str = ""


def parse_radar_meta(data: bytes) -> RadarMeta | None:
    """Parse ``radar.out`` ``key: value`` lines into RadarMeta.

    Returns ``None`` when the file is empty or carries no
    ``version`` line. Any unknown keys are ignored: the format
    may grow new fields and this parser must keep working.
    """
    text = data.decode("utf-8", errors="replace")
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        fields[key.strip().lower()] = value.strip()
    version = fields.get("version", "")
    if not version:
        return None
    return RadarMeta(version=version, commit=fields.get("commit", ""))
