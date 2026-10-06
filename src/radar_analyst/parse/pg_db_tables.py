"""Parse per-database ``databases/{db}/tables.tsv``.

Radar's query (``radar/postgres_tasks.go``) joins ``pg_class``,
``pg_namespace``, ``pg_tablespace`` and ``pg_stat_all_tables`` to
yield one row per user table with size / dead-tup / autovacuum
metadata. The collector already filters out ``pg_catalog``,
``information_schema`` and ``pg_toast`` schemas, so radar-analyst
treats every row as a user table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from radar_analyst.parse.coerce import (
    as_bool,
    as_int_or_none,
    row_float,
    row_int,
)
from radar_analyst.parse.tsv import parse_tsv_bytes


def _parse_reloptions(value: str) -> list[str]:
    """Parse a Postgres array-as-text reloptions value.

    Postgres dumps ``text[]`` columns as ``{"opt=val","other=x"}``
    in the default text format. We strip the braces and split on
    commas, tolerating both quoted and unquoted entries.
    """
    s = value.strip()
    if not s or s in ("NULL", "{}"):
        return []
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    out: list[str] = []
    for piece in s.split(","):
        p = piece.strip().strip('"')
        if p:
            out.append(p)
    return out


@dataclass(frozen=True)
class TableRow:
    """One per-table statistics row."""
    schemaname: str
    tablename: str
    tableowner: str = ""
    tablespace: str = ""
    hasindexes: bool = False
    hasrules: bool = False
    hastriggers: bool = False
    relpersistence: str = "p"
    reltuples: float = 0.0
    reloptions: list[str] = field(default_factory=list)
    heap_size: int = 0
    table_size: int = 0
    toast_table: str = ""
    toast_size: int | None = None
    n_live_tup: int = 0
    n_dead_tup: int = 0
    n_mod_since_analyze: int = 0
    n_ins_since_vacuum: int | None = None
    last_vacuum: str = ""
    last_autovacuum: str = ""
    last_analyze: str = ""
    last_autoanalyze: str = ""
    # Server-side ages added in radar 0.5.0 (seconds since the
    # corresponding ``last_*`` timestamp, computed by the
    # collector against ``clock_timestamp()``). None on older
    # zips that don't carry the columns.
    last_vacuum_age_seconds: int | None = None
    last_autovacuum_age_seconds: int | None = None
    last_analyze_age_seconds: int | None = None
    last_autoanalyze_age_seconds: int | None = None

    @property
    def fqname(self) -> str:
        """Schema-qualified table name."""
        return f"{self.schemaname}.{self.tablename}"

    @property
    def is_unlogged(self) -> bool:
        """Whether relpersistence marks the table unlogged."""
        return self.relpersistence == "u"

    @property
    def autovacuum_disabled(self) -> bool:
        """Whether reloptions disable autovacuum."""
        for opt in self.reloptions:
            low = opt.lower().replace(" ", "")
            if low in (
                "autovacuum_enabled=off",
                "autovacuum_enabled=false",
            ):
                return True
        return False

    @property
    def dead_ratio(self) -> float:
        """Dead tuples as a fraction of live plus dead."""
        denom = self.n_live_tup + self.n_dead_tup
        if denom == 0:
            return 0.0
        return self.n_dead_tup / denom


@dataclass(frozen=True)
class TablesPerDb:
    """One database's table rows."""
    rows: list[TableRow]

    def __len__(self) -> int:
        """Return how many rows were parsed."""
        return len(self.rows)


_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"schemaname", "tablename"}
)


def parse_db_tables(data: bytes) -> TablesPerDb:
    """Parse ``databases/{db}/tables.tsv`` into ``TablesPerDb``.

    Empty input or schema drift (missing required columns) yields
    an empty result. Optional columns that radar may or may not
    emit are tolerated row-by-row.
    """
    table = parse_tsv_bytes(data)
    if not _REQUIRED_COLUMNS.issubset(table.columns):
        return TablesPerDb(rows=[])

    out: list[TableRow] = []
    for r in table.rows:
        schema = r.get("schemaname", "")
        name = r.get("tablename", "")
        if not schema or not name:
            continue
        persistence = (r.get("relpersistence", "p") or "p")[:1]
        out.append(
            TableRow(
                schemaname=schema,
                tablename=name,
                tableowner=r.get("tableowner", "") or "",
                tablespace=r.get("tablespace", "") or "",
                hasindexes=as_bool(r.get("hasindexes", "")),
                hasrules=as_bool(r.get("hasrules", "")),
                hastriggers=as_bool(r.get("hastriggers", "")),
                relpersistence=persistence,
                reltuples=row_float(r, "reltuples"),
                reloptions=_parse_reloptions(
                    r.get("reloptions", "")
                ),
                heap_size=row_int(r, "heap_size"),
                table_size=row_int(r, "table_size"),
                toast_table=r.get("toast_table", "") or "",
                toast_size=as_int_or_none(
                    r.get("toast_size", "")
                ),
                n_live_tup=row_int(r, "n_live_tup"),
                n_dead_tup=row_int(r, "n_dead_tup"),
                n_mod_since_analyze=row_int(
                    r, "n_mod_since_analyze"
                ),
                n_ins_since_vacuum=as_int_or_none(
                    r.get("n_ins_since_vacuum", "")
                ),
                last_vacuum=r.get("last_vacuum", "") or "",
                last_autovacuum=(
                    r.get("last_autovacuum", "") or ""
                ),
                last_analyze=r.get("last_analyze", "") or "",
                last_autoanalyze=(
                    r.get("last_autoanalyze", "") or ""
                ),
                last_vacuum_age_seconds=as_int_or_none(
                    r.get("last_vacuum_age_seconds", "")
                ),
                last_autovacuum_age_seconds=as_int_or_none(
                    r.get("last_autovacuum_age_seconds", "")
                ),
                last_analyze_age_seconds=as_int_or_none(
                    r.get("last_analyze_age_seconds", "")
                ),
                last_autoanalyze_age_seconds=as_int_or_none(
                    r.get(
                        "last_autoanalyze_age_seconds", ""
                    )
                ),
            )
        )
    return TablesPerDb(rows=out)
