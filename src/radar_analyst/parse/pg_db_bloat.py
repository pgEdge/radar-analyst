"""Parse per-database bloat sources.

Two complementary inputs from radar:

- ``databases/{db}/pgstattuple.tsv``: output of the
  ``pgstattuple_approx()`` function from the
  ``pgstattuple`` extension. Authoritative when available.
- ``databases/{db}/bloat.tsv``: radar's long-form
  ``pg_stats``-derived bloat estimate. Approximate;
  used when pgstattuple isn't installed.

Both produce one row per user table; pgstattuple has tuple
counts and dead-tuple ratios, the heuristic produces a
"wasted bytes" estimate. The rule layer prefers pgstattuple
data when both are present for a given database.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.parse.coerce import (
    as_float,
    as_int,
)
from radar_analyst.parse.tsv import parse_tsv_bytes


# ----------------------------------------------------------------------
# pgstattuple
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PgStatTupleRow:
    """One pgstattuple_approx row."""
    schemaname: str
    tablename: str
    table_len: int = 0
    tuple_count: int = 0
    tuple_len: int = 0
    tuple_percent: float = 0.0
    dead_tuple_count: int = 0
    dead_tuple_len: int = 0
    dead_tuple_percent: float = 0.0
    free_space: int = 0
    free_percent: float = 0.0

    @property
    def fqname(self) -> str:
        """Schema-qualified table name."""
        return f"{self.schemaname}.{self.tablename}"


@dataclass(frozen=True)
class PgStatTuplePerDb:
    """One database's pgstattuple rows."""
    rows: list[PgStatTupleRow]

    def __len__(self) -> int:
        return len(self.rows)


_PGSTATTUPLE_REQUIRED: frozenset[str] = frozenset(
    {"schemaname", "tablename"}
)


def parse_db_pgstattuple(data: bytes) -> PgStatTuplePerDb:
    """Parse pgstattuple.tsv for one database."""
    table = parse_tsv_bytes(data)
    if not _PGSTATTUPLE_REQUIRED.issubset(table.columns):
        return PgStatTuplePerDb(rows=[])
    out: list[PgStatTupleRow] = []
    for r in table.rows:
        schema = r.get("schemaname", "")
        name = r.get("tablename", "")
        if not schema or not name:
            continue
        out.append(
            PgStatTupleRow(
                schemaname=schema,
                tablename=name,
                table_len=as_int(r.get("table_len", "")),
                tuple_count=as_int(r.get("tuple_count", "")),
                tuple_len=as_int(r.get("tuple_len", "")),
                tuple_percent=as_float(r.get("tuple_percent", "")),
                dead_tuple_count=as_int(
                    r.get("dead_tuple_count", "")
                ),
                dead_tuple_len=as_int(r.get("dead_tuple_len", "")),
                dead_tuple_percent=as_float(
                    r.get("dead_tuple_percent", "")
                ),
                free_space=as_int(r.get("free_space", "")),
                free_percent=as_float(r.get("free_percent", "")),
            )
        )
    return PgStatTuplePerDb(rows=out)


# ----------------------------------------------------------------------
# pg_stats-derived bloat heuristic
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class BloatRow:
    """One pg_stats-estimate bloat row."""
    schemaname: str
    tablename: str
    table_bloat_ratio: float = 0.0
    wastedbytes: int = 0

    @property
    def fqname(self) -> str:
        """Schema-qualified table name."""
        return f"{self.schemaname}.{self.tablename}"


@dataclass(frozen=True)
class BloatPerDb:
    """One database's bloat-estimate rows."""
    rows: list[BloatRow]

    def __len__(self) -> int:
        return len(self.rows)


_BLOAT_REQUIRED: frozenset[str] = frozenset(
    {"schemaname", "tablename"}
)


def parse_db_bloat(data: bytes) -> BloatPerDb:
    """Parse bloat.tsv for one database."""
    table = parse_tsv_bytes(data)
    if not _BLOAT_REQUIRED.issubset(table.columns):
        return BloatPerDb(rows=[])
    out: list[BloatRow] = []
    for r in table.rows:
        schema = r.get("schemaname", "")
        name = r.get("tablename", "")
        if not schema or not name:
            continue
        out.append(
            BloatRow(
                schemaname=schema,
                tablename=name,
                table_bloat_ratio=as_float(
                    r.get("table_bloat_ratio", "")
                ),
                wastedbytes=as_int(r.get("wastedbytes", "")),
            )
        )
    return BloatPerDb(rows=out)
