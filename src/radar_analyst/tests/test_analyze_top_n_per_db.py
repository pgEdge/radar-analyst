"""Tests for the per-db top-N summary in Internals & I/O Health
facts. These guard the LLM prompt against unbounded per-table or
per-index dumps.
"""

from radar_analyst.analyze.facts import _append_top_n_per_db
from radar_analyst.parse.pg_db_indexes import IndexesPerDb, IndexRow
from radar_analyst.parse.pg_db_tables import TableRow, TablesPerDb


def _table(
    name: str,
    rels: float,
    *,
    size: int = 0,
    schema: str = "public",
) -> TableRow:
    return TableRow(
        schemaname=schema,
        tablename=name,
        reltuples=rels,
        table_size=size,
    )


def _idx(
    name: str,
    size: int,
    *,
    schema: str = "public",
    table: str = "t",
) -> IndexRow:
    return IndexRow(
        schemaname=schema,
        tablename=table,
        indexname=name,
        index_size=size,
    )


def test_silent_when_no_per_db_data() -> None:
    lines: list[str] = []
    _append_top_n_per_db({}, lines, max_per_list=10)
    assert lines == []


def test_caps_at_max_per_list_for_tables() -> None:
    rows = [
        _table(f"t{i}", float(i * 1000), size=i * 1024 * 1024)
        for i in range(50)
    ]
    parsed = {
        "pg.db.tables": {"mydb": TablesPerDb(rows=rows)},
    }
    lines: list[str] = []
    _append_top_n_per_db(parsed, lines, max_per_list=10)
    assert any("Top 10 tables by size" in ln for ln in lines)
    # Highest table_size first.
    table_line = next(
        ln for ln in lines if "Top 10 tables" in ln
    )
    assert "t49" in table_line
    # 11th-largest must NOT appear.
    assert "t39" not in table_line


def test_tables_sort_by_size_then_reltuples() -> None:
    # Disagreement case: tableA has more rows but smaller size,
    # tableB has fewer rows but bigger size: B sorts first.
    rows = [
        _table("small_but_busy", rels=1_000_000.0, size=1024),
        _table("big_dataset", rels=1000.0, size=10 * 1024 * 1024),
    ]
    parsed = {
        "pg.db.tables": {"mydb": TablesPerDb(rows=rows)},
    }
    lines: list[str] = []
    _append_top_n_per_db(parsed, lines, max_per_list=10)
    table_line = next(
        ln for ln in lines if "Top" in ln and "tables" in ln
    )
    assert table_line.index("big_dataset") < (
        table_line.index("small_but_busy")
    )


def test_table_line_includes_size_and_rows() -> None:
    rows = [_table("orders", rels=1500.0, size=2 * 1024 * 1024)]
    parsed = {
        "pg.db.tables": {"mydb": TablesPerDb(rows=rows)},
    }
    lines: list[str] = []
    _append_top_n_per_db(parsed, lines, max_per_list=10)
    table_line = next(ln for ln in lines if "orders" in ln)
    assert "MiB" in table_line
    assert "1.5K" in table_line  # row count rendered too


def test_caps_at_max_per_list_for_indexes() -> None:
    rows = [
        _idx(f"i{i}", size=i * 1024 * 1024) for i in range(50)
    ]
    parsed = {
        "pg.db.indexes": {"mydb": IndexesPerDb(rows=rows)},
    }
    lines: list[str] = []
    _append_top_n_per_db(parsed, lines, max_per_list=10)
    idx_line = next(ln for ln in lines if "Top 10 indexes" in ln)
    # Top size first.
    assert "i49" in idx_line
    assert "i39" not in idx_line


def test_emits_db_header_with_counts() -> None:
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[_table("orders", 1000.0)]
            ),
        },
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[_idx("orders_pkey", 4096)]
            ),
        },
    }
    lines: list[str] = []
    _append_top_n_per_db(parsed, lines, max_per_list=10)
    header = lines[0]
    assert "mydb" in header
    assert "1 tables" in header
    assert "1 indexes" in header


def test_iterates_multiple_databases_alphabetically() -> None:
    parsed = {
        "pg.db.tables": {
            "zee": TablesPerDb(rows=[_table("a", 1.0)]),
            "alpha": TablesPerDb(rows=[_table("a", 1.0)]),
        }
    }
    lines: list[str] = []
    _append_top_n_per_db(parsed, lines, max_per_list=10)
    headers = [
        ln for ln in lines if ln.startswith("Database ")
    ]
    assert headers[0].startswith("Database alpha")
    assert headers[1].startswith("Database zee")


def test_size_formatting_uses_human_units() -> None:
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[
                    _idx(
                        "huge",
                        size=4 * 1024 ** 3,
                    ),
                ]
            )
        }
    }
    lines: list[str] = []
    _append_top_n_per_db(parsed, lines, max_per_list=10)
    line = next(ln for ln in lines if "huge" in ln)
    assert "GiB" in line


def test_silent_when_size_columns_unavailable() -> None:
    # Pre-0.5.0 radar zips have neither table_size nor index_size
    # nor reltuples in their per-db dumps. Without the gate, the
    # renderer would emit "(0 B, 0 rows)" for every line: noise
    # in the LLM prompt. Verify it stays silent.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[_table("t", rels=0.0, size=0)],
            ),
        },
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[_idx("i", size=0)],
            ),
        },
    }
    lines: list[str] = []
    _append_top_n_per_db(parsed, lines, max_per_list=10)
    # Header may still render (counts are useful even without
    # sizes), but no per-table/per-index "Top N" lines.
    assert not any("Top " in ln for ln in lines)
