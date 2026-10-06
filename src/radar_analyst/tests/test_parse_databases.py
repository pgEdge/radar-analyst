"""Tests for instance-level per-database parsers."""

from radar_analyst.parse.databases import (
    count_tsv_rows,
    count_user_objects,
    parse_database_conflicts,
    parse_database_sizes,
    parse_databases,
    parse_databases_blk,
    parse_databases_checksums,
    parse_databases_tup,
    parse_databases_xact,
    parse_db_stat_database,
    parse_extension_names,
    parse_schema_oids,
)


def test_parse_databases_real_radar_columns() -> None:
    # Radar's query is ``SELECT oid, datname, datdba, encoding,
    # datcollate, datctype FROM pg_database``: no datallowconn /
    # datistemplate columns. Templates are identified by name
    # (template0 / template1) alone.
    tsv = (
        "oid\tdatname\tdatdba\tencoding\tdatcollate\tdatctype\n"
        "5\tpostgres\t10\t6\ten_US.UTF-8\ten_US.UTF-8\n"
        "4\ttemplate0\t10\t6\ten_US.UTF-8\ten_US.UTF-8\n"
        "1\ttemplate1\t10\t6\ten_US.UTF-8\ten_US.UTF-8\n"
        "17028\tmydb\t10\t6\ten_US.UTF-8\ten_US.UTF-8\n"
    )
    out = parse_databases(tsv.encode())
    names = [d.datname for d in out]
    assert names == [
        "postgres",
        "template0",
        "template1",
        "mydb",
    ]
    by_name = {d.datname: d for d in out}
    assert by_name["template0"].datistemplate is True
    assert by_name["template1"].datistemplate is True
    assert by_name["postgres"].datistemplate is False
    assert by_name["mydb"].datistemplate is False


def test_parse_databases_with_wraparound_columns() -> None:
    # Updated radar collectors include datistemplate, datallowconn,
    # datconnlimit, datfrozenxid, frozenxid_age, datminmxid,
    # minmxid_age.
    tsv = (
        "oid\tdatname\tdatdba\tencoding\tdatcollate\tdatctype\t"
        "datistemplate\tdatallowconn\tdatconnlimit\t"
        "datfrozenxid\tfrozenxid_age\tdatminmxid\tminmxid_age\n"
        "5\tpostgres\t10\t6\tC\tC\tf\tt\t-1\t"
        "100000\t12345\t1\t0\n"
        "4\ttemplate0\t10\t6\tC\tC\tt\tf\t-1\t"
        "100000\t12345\t1\t0\n"
        "999\tdoomed\t10\t6\tC\tC\tf\tt\t-2\t"
        "100000\t12345\t1\t0\n"
    )
    out = parse_databases(tsv.encode())
    by = {d.datname: d for d in out}
    pg = by["postgres"]
    assert pg.datistemplate is False
    assert pg.datallowconn is True
    assert pg.datconnlimit == -1
    assert pg.datfrozenxid == 100000
    assert pg.frozenxid_age == 12345
    assert pg.datminmxid == 1
    assert pg.minmxid_age == 0
    assert by["template0"].datistemplate is True
    assert by["template0"].datallowconn is False
    assert by["doomed"].datconnlimit == -2


def test_parse_databases_legacy_columns_still_work() -> None:
    # Older radar archives don't have the wraparound / template
    # columns: fall back to name-based template detection and
    # default values.
    tsv = (
        "oid\tdatname\tdatdba\tencoding\tdatcollate\tdatctype\n"
        "4\ttemplate0\t10\t6\tC\tC\n"
        "5\tpostgres\t10\t6\tC\tC\n"
    )
    out = parse_databases(tsv.encode())
    by = {d.datname: d for d in out}
    assert by["template0"].datistemplate is True
    assert by["postgres"].datistemplate is False
    assert by["postgres"].datfrozenxid is None
    assert by["postgres"].frozenxid_age is None
    assert by["postgres"].datconnlimit == -1


def test_parse_database_sizes_returns_pretty_strings() -> None:
    tsv = (
        "datname\tsize\n"
        "postgres\t8248 kB\n"
        "mydb\t450 MB\n"
    )
    out = parse_database_sizes(tsv.encode())
    assert out == {"postgres": "8248 kB", "mydb": "450 MB"}


def test_parse_databases_tup_real_columns() -> None:
    # Radar's query is ``SELECT datname, tup_returned, tup_fetched,
    # tup_inserted, tup_updated, tup_deleted FROM pg_stat_database
    # …``: NO deadlocks or temp_files columns (those are in the
    # per-db stat_database file, not the instance-level
    # databases_tup.tsv).
    tsv = (
        "datname\ttup_returned\ttup_fetched\ttup_inserted\t"
        "tup_updated\ttup_deleted\n"
        "postgres\t1419495\t39855\t0\t0\t0\n"
        "mydb\t45414245\t42578917\t288\t9\t0\n"
    )
    out = parse_databases_tup(tsv.encode())
    assert out["postgres"].tup_returned == 1_419_495
    assert out["postgres"].tup_fetched == 39_855
    assert out["mydb"].tup_returned == 45_414_245
    assert out["mydb"].tup_inserted == 288
    assert out["mydb"].tup_updated == 9
    assert out["mydb"].tup_deleted == 0


def test_parse_databases_checksums_captures_failures() -> None:
    tsv = (
        "datname\tchecksum_failures\tchecksum_last_failure\n"
        "postgres\t0\t\n"
        "mydb\t3\t2026-04-15 11:45:57+01\n"
    )
    out = parse_databases_checksums(tsv.encode())
    assert out["postgres"].checksum_failures == 0
    assert out["mydb"].checksum_failures == 3
    assert (
        out["mydb"].checksum_last_failure
        == "2026-04-15 11:45:57+01"
    )


def test_count_tsv_rows_ignores_header() -> None:
    assert count_tsv_rows(b"a\tb\n1\t2\n3\t4\n") == 2
    assert count_tsv_rows(b"") == 0


def test_parse_extension_names() -> None:
    tsv = (
        "extname\textowner\n"
        "pg_stat_statements\t10\n"
        "pgcrypto\t10\n"
    )
    assert parse_extension_names(tsv.encode()) == [
        "pg_stat_statements",
        "pgcrypto",
    ]


def test_parse_databases_xact() -> None:
    tsv = (
        "datname\txact_commit\txact_rollback\n"
        "postgres\t12345\t67\n"
        "mydb\t1000000\t0\n"
    )
    out = parse_databases_xact(tsv.encode())
    assert out["postgres"].xact_commit == 12_345
    assert out["postgres"].xact_rollback == 67
    assert out["mydb"].xact_commit == 1_000_000
    assert out["mydb"].xact_rollback == 0


def test_parse_databases_blk() -> None:
    tsv = (
        "datname\tblks_read\tblks_hit\tblk_read_time\t"
        "blk_write_time\n"
        "postgres\t123\t456789\t4.2\t0.1\n"
    )
    out = parse_databases_blk(tsv.encode())
    assert out["postgres"].blks_read == 123
    assert out["postgres"].blks_hit == 456_789
    assert out["postgres"].blk_read_time == 4.2
    assert out["postgres"].blk_write_time == 0.1


def test_parse_database_conflicts() -> None:
    # radar's query is SELECT * FROM pg_stat_database_conflicts,
    # which yields datid, datname, confl_* columns.
    tsv = (
        "datid\tdatname\tconfl_tablespace\tconfl_lock\t"
        "confl_snapshot\tconfl_bufferpin\tconfl_deadlock\n"
        "5\tpostgres\t0\t0\t0\t0\t0\n"
        "16385\tstandby_heavy\t0\t2\t3\t0\t1\n"
    )
    out = parse_database_conflicts(tsv.encode())
    assert out["postgres"].confl_lock == 0
    assert out["standby_heavy"].confl_lock == 2
    assert out["standby_heavy"].confl_snapshot == 3
    assert out["standby_heavy"].confl_deadlock == 1


def test_parse_db_stat_database_real_columns() -> None:
    # Radar's per-db query selects:
    #   datname, conflicts, deadlocks, temp_files, temp_bytes,
    #   stats_reset.
    # This is where deadlocks and temp_files actually live in
    # radar-collected data.
    tsv = (
        "datname\tconflicts\tdeadlocks\ttemp_files\t"
        "temp_bytes\tstats_reset\n"
        "mydb\t0\t3\t12\t104857600\t2026-01-01 00:00:00+00\n"
    )
    out = parse_db_stat_database(tsv.encode())
    assert out is not None
    assert out.datname == "mydb"
    assert out.conflicts == 0
    assert out.deadlocks == 3
    assert out.temp_files == 12
    assert out.temp_bytes == 104_857_600


def test_parse_db_stat_database_empty() -> None:
    assert parse_db_stat_database(b"") is None
    assert (
        parse_db_stat_database(
            b"datname\tconflicts\tdeadlocks\n"
        )
        is None
    )


# ---------------------------------------------------------------
# parse_schema_oids: namespace OID → name mapping
# ---------------------------------------------------------------

_SCHEMAS_TSV = (
    b"oid\tnspname\tnspowner\tnspacl\n"
    b"11\tpg_catalog\t10\t\n"
    b"13331\tinformation_schema\t10\t\n"
    b"99\tpg_toast\t10\t\n"
    b"2200\tpublic\t6171\t\n"
    b"16392\tmyapp\t10\t\n"
)


def test_parse_schema_oids_returns_mapping() -> None:
    result = parse_schema_oids(_SCHEMAS_TSV)
    assert result == {
        "11": "pg_catalog",
        "13331": "information_schema",
        "99": "pg_toast",
        "2200": "public",
        "16392": "myapp",
    }


def test_parse_schema_oids_empty() -> None:
    assert parse_schema_oids(b"") == {}


# ---------------------------------------------------------------
# count_user_objects: filter out system schemas
# ---------------------------------------------------------------

_TABLES_TSV = (
    b"schemaname\ttablename\ttableowner\n"
    b"pg_catalog\tpg_class\tpostgres\n"
    b"pg_catalog\tpg_type\tpostgres\n"
    b"information_schema\ttables\tpostgres\n"
    b"public\tusers\tapp\n"
    b"myapp\torders\tapp\n"
)

_FUNCS_TSV = (
    b"oid\tproname\tpronamespace\tproowner\tprolang\n"
    b"100\tarray_agg\t11\t10\t12\n"
    b"200\tmy_func\t2200\t10\t14\n"
    b"300\tother_func\t16392\t10\t14\n"
)

_TRIGGERS_TSV = (
    b"oid\ttgrelid\ttgparentid\ttgname\t"
    b"tgfoid\ttgtype\ttgenabled\ttgisinternal\n"
    b"1\t100\t0\tRI_trigger\t200\t5\tO\ttrue\n"
    b"2\t200\t0\tmy_trigger\t300\t5\tO\tfalse\n"
    b"3\t300\t0\taudit_trigger\t400\t5\tO\tfalse\n"
)


def test_count_user_tables_excludes_system_schemas() -> None:
    schema_map = {
        "11": "pg_catalog",
        "13331": "information_schema",
        "2200": "public",
        "16392": "myapp",
    }
    result = count_user_objects(
        _TABLES_TSV, schema_map, kind="tables"
    )
    assert result == 2  # public.users + myapp.orders


def test_count_user_funcs_excludes_pg_catalog() -> None:
    schema_map = {
        "11": "pg_catalog",
        "2200": "public",
        "16392": "myapp",
    }
    result = count_user_objects(
        _FUNCS_TSV, schema_map, kind="funcs"
    )
    assert result == 2  # my_func + other_func


_TYPES_TSV = (
    b"oid\ttypname\ttypnamespace\ttyptype\ttypcategory\n"
    b"100\tint4\t11\tb\tN\n"
    b"200\tmy_enum\t2200\te\tE\n"
    b"300\t_my_enum\t2200\tb\tA\n"
    b"400\torders\t16392\tc\tC\n"
    b"500\tmy_domain\t2200\td\tN\n"
)


def test_count_user_types_excludes_auto_generated() -> None:
    schema_map = {
        "11": "pg_catalog",
        "2200": "public",
        "16392": "myapp",
    }
    result = count_user_objects(
        _TYPES_TSV, schema_map, kind="types"
    )
    # my_enum (e) + my_domain (d) only; _my_enum (b=array)
    # and orders (c=composite) are auto-generated.
    assert result == 2


def test_count_user_triggers_excludes_internal() -> None:
    schema_map: dict[str, str] = {}  # not for triggers
    result = count_user_objects(
        _TRIGGERS_TSV, schema_map, kind="triggers"
    )
    assert result == 2  # my_trigger + audit_trigger


def test_count_user_objects_empty() -> None:
    assert count_user_objects(b"", {}, kind="tables") == 0
