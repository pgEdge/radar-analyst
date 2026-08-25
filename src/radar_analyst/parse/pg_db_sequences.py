"""Parse per-database ``databases/{db}/sequences.tsv``.

Source view: ``pg_sequences`` (PG10+). Radar selects
``schemaname, sequencename, data_type, last_value, max_value,
min_value, increment_by, cycle, cache_size``.

A bigint sequence with the default ``max_value =
9_223_372_036_854_775_807`` is treated as effectively
inexhaustible. For non-default ranges we compute the
remaining percentage.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.parse.coerce import as_int_or_none
from radar_analyst.parse.tsv import parse_tsv_bytes

_BIGINT_MAX = 9_223_372_036_854_775_807


@dataclass(frozen=True)
class SequenceRow:
    """One pg_sequences row."""
    schemaname: str
    sequencename: str
    data_type: str = "bigint"
    last_value: int | None = None
    max_value: int = _BIGINT_MAX
    min_value: int = 1
    increment_by: int = 1

    @property
    def fqname(self) -> str:
        """Schema-qualified sequence name."""
        return f"{self.schemaname}.{self.sequencename}"

    @property
    def is_unbounded(self) -> bool:
        """True for bigint sequences using the default max value."""
        return self.max_value == _BIGINT_MAX

    @property
    def remaining_percent(self) -> float | None:
        """Percent of the value range still ahead of last_value.

        Returns ``None`` if last_value is unknown (never used)
        or if the range is unbounded.
        """
        if self.is_unbounded:
            return None
        if self.last_value is None:
            return None
        span = self.max_value - self.min_value
        if span <= 0:
            return None
        remaining = self.max_value - self.last_value
        return max(0.0, remaining / span * 100.0)


@dataclass(frozen=True)
class SequencesPerDb:
    """One database's sequence rows."""
    rows: list[SequenceRow]

    def __len__(self) -> int:
        return len(self.rows)


_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"schemaname", "sequencename"}
)


def parse_db_sequences(data: bytes) -> SequencesPerDb:
    """Parse ``databases/{db}/sequences.tsv`` → ``SequencesPerDb``."""
    table = parse_tsv_bytes(data)
    if not _REQUIRED_COLUMNS.issubset(table.columns):
        return SequencesPerDb(rows=[])

    out: list[SequenceRow] = []
    for r in table.rows:
        schema = r.get("schemaname", "")
        name = r.get("sequencename", "")
        if not schema or not name:
            continue
        last = as_int_or_none(r.get("last_value", ""))
        max_v = as_int_or_none(r.get("max_value", ""))
        min_v = as_int_or_none(r.get("min_value", ""))
        inc = as_int_or_none(r.get("increment_by", ""))
        out.append(
            SequenceRow(
                schemaname=schema,
                sequencename=name,
                data_type=r.get("data_type", "") or "bigint",
                last_value=last,
                max_value=(
                    max_v if max_v is not None else _BIGINT_MAX
                ),
                min_value=min_v if min_v is not None else 1,
                increment_by=inc if inc is not None else 1,
            )
        )
    return SequencesPerDb(rows=out)


__all__ = [
    "SequenceRow",
    "SequencesPerDb",
    "parse_db_sequences",
    "_BIGINT_MAX",
]
