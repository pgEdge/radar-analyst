"""Tests for parse/pg_db_tables.py."""

from radar_analyst.parse.pg_db_tables import (
    TableRow,
    TablesPerDb,
    parse_db_tables,
)


_HEADER = (
    "schemaname\ttablename\ttableowner\ttablespace\thasindexes\t"
    "hasrules\thastriggers\trelpersistence\treltuples\t"
    "reloptions\theap_size\ttable_size\ttoast_table\ttoast_size\t"
    "n_live_tup\tn_dead_tup\tn_mod_since_analyze\t"
    "n_ins_since_vacuum\tlast_vacuum\tlast_autovacuum\t"
    "last_analyze\tlast_autoanalyze\n"
)


def _row(
    schema: str = "public",
    name: str = "t",
    *,
    persistence: str = "p",
    reltuples: float = 0.0,
    reloptions: str = "",
    heap_size: str = "",
    table_size: str = "",
    toast: str = "",
    toast_size: str = "",
    live: int = 0,
    dead: int = 0,
) -> str:
    return (
        f"{schema}\t{name}\towner\t\tt\tf\tf\t{persistence}\t"
        f"{reltuples}\t{reloptions}\t{heap_size}\t{table_size}\t"
        f"{toast}\t{toast_size}\t"
        f"{live}\t{dead}\t0\t\t\t\t\t\n"
    )


def test_parse_empty_input_returns_empty() -> None:
    assert parse_db_tables(b"").rows == []


def test_parse_missing_required_columns_returns_empty() -> None:
    tsv = "schemaname\nfoo\n"  # no tablename
    assert parse_db_tables(tsv.encode()).rows == []


def test_parse_basic_row() -> None:
    tsv = _HEADER + _row(
        schema="public",
        name="orders",
        live=10000,
        dead=500,
    )
    out = parse_db_tables(tsv.encode())
    assert isinstance(out, TablesPerDb)
    assert len(out) == 1
    row = out.rows[0]
    assert isinstance(row, TableRow)
    assert row.schemaname == "public"
    assert row.tablename == "orders"
    assert row.fqname == "public.orders"
    assert row.n_live_tup == 10000
    assert row.n_dead_tup == 500


def test_dead_ratio_computed() -> None:
    tsv = _HEADER + _row(live=800, dead=200)
    row = parse_db_tables(tsv.encode()).rows[0]
    assert row.dead_ratio == 0.2


def test_dead_ratio_zero_when_no_tuples() -> None:
    tsv = _HEADER + _row(live=0, dead=0)
    row = parse_db_tables(tsv.encode()).rows[0]
    assert row.dead_ratio == 0.0


def test_unlogged_detection() -> None:
    tsv = (
        _HEADER
        + _row(name="permanent", persistence="p")
        + _row(name="ephemeral", persistence="u")
    )
    rows = {r.tablename: r for r in parse_db_tables(tsv.encode()).rows}
    assert rows["permanent"].is_unlogged is False
    assert rows["ephemeral"].is_unlogged is True


def test_autovacuum_disabled_via_reloptions() -> None:
    tsv = (
        _HEADER
        + _row(name="off1", reloptions='{"autovacuum_enabled=off"}')
        + _row(
            name="off2",
            reloptions='{"autovacuum_enabled=false"}',
        )
        + _row(name="on", reloptions="")
        + _row(
            name="other",
            reloptions='{"fillfactor=70"}',
        )
    )
    rows = {r.tablename: r for r in parse_db_tables(tsv.encode()).rows}
    assert rows["off1"].autovacuum_disabled is True
    assert rows["off2"].autovacuum_disabled is True
    assert rows["on"].autovacuum_disabled is False
    assert rows["other"].autovacuum_disabled is False


def test_reloptions_handles_multiple_settings() -> None:
    tsv = _HEADER + _row(
        reloptions='{"fillfactor=85","autovacuum_enabled=off"}'
    )
    row = parse_db_tables(tsv.encode()).rows[0]
    assert row.autovacuum_disabled is True
    assert "fillfactor=85" in row.reloptions


def test_toast_size_parsed() -> None:
    tsv = _HEADER + _row(toast="pg_toast.pg_toast_16384", toast_size="409600")
    row = parse_db_tables(tsv.encode()).rows[0]
    assert row.toast_table == "pg_toast.pg_toast_16384"
    assert row.toast_size == 409600


def test_toast_size_null_when_no_toast() -> None:
    tsv = _HEADER + _row(toast="-", toast_size="")
    row = parse_db_tables(tsv.encode()).rows[0]
    assert row.toast_size is None


def test_heap_size_and_table_size_parsed() -> None:
    tsv = _HEADER + _row(
        heap_size="465387520",
        table_size="465543168",
    )
    row = parse_db_tables(tsv.encode()).rows[0]
    assert row.heap_size == 465387520
    assert row.table_size == 465543168


def test_heap_size_and_table_size_default_to_zero() -> None:
    # Older radar collectors that don't emit the column.
    tsv = _HEADER + _row()
    row = parse_db_tables(tsv.encode()).rows[0]
    assert row.heap_size == 0
    assert row.table_size == 0


def test_last_age_seconds_default_to_none_when_missing() -> None:
    # Pre-0.5.0 radar tables.tsv omits the *_age_seconds columns.
    tsv = _HEADER + _row()
    row = parse_db_tables(tsv.encode()).rows[0]
    assert row.last_vacuum_age_seconds is None
    assert row.last_autovacuum_age_seconds is None
    assert row.last_analyze_age_seconds is None
    assert row.last_autoanalyze_age_seconds is None


def test_last_age_seconds_parsed_when_present() -> None:
    # Radar 0.5.0+ adds the *_age_seconds columns. Build the
    # fixture row directly here rather than extending _HEADER /
    # _row, since the new columns are radar-0.5.0-only and the
    # existing tests deliberately exercise the older shape.
    header = (
        "schemaname\ttablename\tn_live_tup\tn_dead_tup\t"
        "last_vacuum_age_seconds\tlast_autovacuum_age_seconds\t"
        "last_analyze_age_seconds\tlast_autoanalyze_age_seconds\n"
    )
    body = "public\torders\t100\t10\t1800\t3600\t900\t1200\n"
    out = parse_db_tables((header + body).encode())
    row = out.rows[0]
    assert row.last_vacuum_age_seconds == 1800
    assert row.last_autovacuum_age_seconds == 3600
    assert row.last_analyze_age_seconds == 900
    assert row.last_autoanalyze_age_seconds == 1200
