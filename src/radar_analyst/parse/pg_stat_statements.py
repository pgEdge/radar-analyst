"""Parse the three ``postgresql/stat_statements_*.tsv`` files.

Radar emits three rotations of the same ``pg_stat_statements``
selection (sorted by calls / max_exec_time / total_exec_time
respectively, each top-100). The columns are identical in each
file so a single ``parse_stat_statements`` handles them all.

When the ``pg_stat_statements`` extension isn't installed on the
host, radar skips the queries and the files are absent: the
parser must therefore degrade silently. Callers should treat an
empty list as "no data, don't fire".
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.parse.coerce import (
    row_float,
    row_int,
)
from radar_analyst.parse.tsv import parse_tsv_bytes


# Statements built from literal lists run to megabytes of text. 1024
# is the default track_activity_query_size, how much of a query's
# text pg_stat_activity keeps.
_QUERY_TEXT_CHARS = 1024


@dataclass(frozen=True)
class StatementRow:
    """One pg_stat_statements row, its query text cut short."""
    userid: str
    dbid: str
    query: str
    calls: int
    total_exec_time: float
    mean_exec_time: float
    max_exec_time: float
    rows: int


def parse_stat_statements(data: bytes) -> list[StatementRow]:
    """Parse one stat_statements TSV."""
    table = parse_tsv_bytes(data)
    out: list[StatementRow] = []

    for r in table.rows:
        out.append(
            StatementRow(
                userid=r.get("userid", "") or "",
                dbid=r.get("dbid", "") or "",
                query=(r.get("query", "") or "")[:_QUERY_TEXT_CHARS],
                calls=row_int(r, "calls"),
                total_exec_time=row_float(r, "total_exec_time"),
                mean_exec_time=row_float(r, "mean_exec_time"),
                max_exec_time=row_float(r, "max_exec_time"),
                rows=row_int(r, "rows"),
            )
        )
    return out
