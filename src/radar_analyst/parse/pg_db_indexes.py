"""Parse per-database ``databases/{db}/indexes.tsv``.

Radar joins ``pg_index``, ``pg_class``, ``pg_namespace`` and
``pg_stat_all_indexes`` to produce one row per user index with
the catalog identity columns (``indrelid``, ``indclass``,
``indkey``, ``indexprs``, ``indpred``), validity flags
(``indisvalid``, ``indisunique``, ``indisprimary``), the index
size in bytes, and the ``idx_scan / idx_tup_read /
idx_tup_fetch`` counters from the stats view.

System schemas are filtered out at the collector level.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.parse.coerce import (
    as_bool,
    as_int,
)
from radar_analyst.parse.tsv import parse_tsv_bytes


@dataclass(frozen=True)
class IndexRow:
    """One index row with its dedup-key columns."""
    schemaname: str
    tablename: str
    indexname: str
    indexdef: str = ""
    indrelid: str = ""
    indexrelid: str = ""
    indisunique: bool = False
    indisprimary: bool = False
    indisvalid: bool = True
    indclass: str = ""
    indkey: str = ""
    indexprs: str = ""
    indpred: str = ""
    index_size: int = 0
    idx_scan: int = 0
    idx_tup_read: int = 0
    idx_tup_fetch: int = 0

    @property
    def fqname(self) -> str:
        """Schema-qualified index name."""
        return f"{self.schemaname}.{self.indexname}"

    @property
    def dedup_key(self) -> tuple[str, str, str, str, str]:
        """Tuple identifying semantically-equivalent indexes.

        Two indexes that produce the same key are duplicates,
        regardless of name.
        """
        return (
            self.indrelid,
            self.indclass,
            self.indkey,
            self.indexprs,
            self.indpred,
        )


@dataclass(frozen=True)
class IndexesPerDb:
    """One database's index rows."""
    rows: list[IndexRow]

    def __len__(self) -> int:
        """Return how many rows were parsed."""
        return len(self.rows)


_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"schemaname", "tablename", "indexname"}
)


def parse_db_indexes(data: bytes) -> IndexesPerDb:
    """Parse ``databases/{db}/indexes.tsv`` into ``IndexesPerDb``.

    Empty input or missing required columns yields an empty
    result. Optional columns (validity flags, size, scan
    counters) default sensibly when absent.
    """
    table = parse_tsv_bytes(data)
    if not _REQUIRED_COLUMNS.issubset(table.columns):
        return IndexesPerDb(rows=[])

    out: list[IndexRow] = []
    for r in table.rows:
        schema = r.get("schemaname", "")
        tname = r.get("tablename", "")
        iname = r.get("indexname", "")
        if not schema or not tname or not iname:
            continue
        out.append(
            IndexRow(
                schemaname=schema,
                tablename=tname,
                indexname=iname,
                indexdef=r.get("indexdef", "") or "",
                indrelid=r.get("indrelid", "") or "",
                indexrelid=r.get("indexrelid", "") or "",
                indisunique=as_bool(r.get("indisunique", "")),
                indisprimary=as_bool(r.get("indisprimary", "")),
                # Defaults to True when the column is absent or
                # the value is empty: that matches pg's default
                # for pre-existing indexes and avoids false
                # "invalid" findings on schema drift.
                indisvalid=as_bool(r.get("indisvalid", "t"))
                if r.get("indisvalid", "")
                else True,
                indclass=r.get("indclass", "") or "",
                indkey=r.get("indkey", "") or "",
                indexprs=r.get("indexprs", "") or "",
                indpred=r.get("indpred", "") or "",
                index_size=as_int(r.get("index_size", "")),
                idx_scan=as_int(r.get("idx_scan", "")),
                idx_tup_read=as_int(
                    r.get("idx_tup_read", "")
                ),
                idx_tup_fetch=as_int(
                    r.get("idx_tup_fetch", "")
                ),
            )
        )
    return IndexesPerDb(rows=out)
