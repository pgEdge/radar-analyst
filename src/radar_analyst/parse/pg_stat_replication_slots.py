"""Parse ``postgresql/stat_replication_slots.tsv``.

Source view: ``pg_stat_replication_slots`` (PG14+). Carries
spill / stream / total counters per logical replication slot.
The basic ``replication_slots.tsv`` file (from
``pg_replication_slots``) doesn't have the spill columns:
this is a separate view that has to be queried alongside.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.parse.coerce import (
    as_int,
)
from radar_analyst.parse.tsv import parse_tsv_bytes


@dataclass(frozen=True)
class SlotStat:
    """One pg_stat_replication_slots row."""
    slot_name: str
    spill_txns: int = 0
    spill_count: int = 0
    spill_bytes: int = 0
    stream_txns: int = 0
    stream_count: int = 0
    stream_bytes: int = 0
    total_txns: int = 0
    total_bytes: int = 0
    stats_reset: str = ""

    @property
    def is_spilling(self) -> bool:
        """Whether the slot spilled reorder buffers to disk."""
        return self.spill_count > 0 and self.spill_bytes > 0


@dataclass(frozen=True)
class StatReplicationSlots:
    """All slot stats, with a spilling view."""
    rows: list[SlotStat]

    def __len__(self) -> int:
        return len(self.rows)

    def spilling(self) -> list[SlotStat]:
        """The slots that spilled to disk."""
        return [r for r in self.rows if r.is_spilling]


_REQUIRED_COLUMNS: frozenset[str] = frozenset({"slot_name"})


def parse_stat_replication_slots(
    data: bytes,
) -> StatReplicationSlots:
    """Parse stat_replication_slots.tsv."""
    table = parse_tsv_bytes(data)
    if not _REQUIRED_COLUMNS.issubset(table.columns):
        return StatReplicationSlots(rows=[])

    out: list[SlotStat] = []
    for r in table.rows:
        name = r.get("slot_name", "").strip()
        if not name:
            continue
        out.append(
            SlotStat(
                slot_name=name,
                spill_txns=as_int(r.get("spill_txns", "")),
                spill_count=as_int(r.get("spill_count", "")),
                spill_bytes=as_int(r.get("spill_bytes", "")),
                stream_txns=as_int(r.get("stream_txns", "")),
                stream_count=as_int(r.get("stream_count", "")),
                stream_bytes=as_int(r.get("stream_bytes", "")),
                total_txns=as_int(r.get("total_txns", "")),
                total_bytes=as_int(r.get("total_bytes", "")),
                stats_reset=r.get("stats_reset", "") or "",
            )
        )
    return StatReplicationSlots(rows=out)
