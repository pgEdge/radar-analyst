"""Tests for parse/pg_db_bloat.py: both pgstattuple and heuristic."""

from radar_analyst.parse.pg_db_bloat import (
    BloatPerDb,
    BloatRow,
    PgStatTuplePerDb,
    PgStatTupleRow,
    parse_db_bloat,
    parse_db_pgstattuple,
)


def test_pgstattuple_empty_returns_empty() -> None:
    assert parse_db_pgstattuple(b"").rows == []


def test_pgstattuple_missing_columns_returns_empty() -> None:
    assert parse_db_pgstattuple(b"foo\n1\n").rows == []


def test_pgstattuple_parses_dead_tuple_percent() -> None:
    tsv = (
        "schemaname\ttablename\ttable_len\ttuple_count\t"
        "tuple_len\ttuple_percent\tdead_tuple_count\t"
        "dead_tuple_len\tdead_tuple_percent\tfree_space\t"
        "free_percent\n"
        "public\torders\t10485760\t90000\t9000000\t85.83\t"
        "10000\t1000000\t9.54\t486760\t4.64\n"
    )
    out = parse_db_pgstattuple(tsv.encode())
    assert isinstance(out, PgStatTuplePerDb)
    assert len(out) == 1
    row = out.rows[0]
    assert isinstance(row, PgStatTupleRow)
    assert row.fqname == "public.orders"
    assert row.dead_tuple_percent == 9.54
    assert row.dead_tuple_count == 10000


def test_bloat_empty_returns_empty() -> None:
    assert parse_db_bloat(b"").rows == []


def test_bloat_parses_ratio_and_wasted() -> None:
    tsv = (
        "current_database\tschemaname\ttablename\t"
        "table_bloat_ratio\twastedbytes\tiname\tituples\t"
        "ipages\tiotta\n"
        "mydb\tpublic\torders\t1.8\t52428800\tt_pkey\t1000\t"
        "10\t8\n"
    )
    out = parse_db_bloat(tsv.encode())
    assert isinstance(out, BloatPerDb)
    assert len(out) == 1
    row = out.rows[0]
    assert isinstance(row, BloatRow)
    assert row.fqname == "public.orders"
    assert row.table_bloat_ratio == 1.8
    assert row.wastedbytes == 52428800


def test_bloat_skips_rows_without_schema_or_table() -> None:
    tsv = (
        "schemaname\ttablename\ttable_bloat_ratio\twastedbytes\n"
        "\tt\t1.0\t100\n"
        "public\t\t1.0\t100\n"
        "public\tok\t1.5\t1024\n"
    )
    out = parse_db_bloat(tsv.encode())
    assert len(out) == 1
    assert out.rows[0].tablename == "ok"
