"""Tests for parse/pg_diagnostics.py: tablespaces, roles,
shmem_allocations, stat_progress.
"""

from __future__ import annotations

from radar_analyst.parse.pg_diagnostics import (
    PgRole,
    ProgressRow,
    ShmemAllocation,
    Tablespace,
    TablespaceSize,
    parse_roles,
    parse_shmem_allocations,
    parse_stat_progress,
    parse_tablespace_sizes,
    parse_tablespaces,
)


# ---------------------------------------------------------------
# parse_tablespaces
# ---------------------------------------------------------------

_TABLESPACES_TSV = (
    b"oid\tspcname\tspcowner\tspcacl\tspcoptions\tspclocation\n"
    b"1663\tpg_default\t10\t\t\t\n"
    b"1664\tpg_global\t10\t\t\t\n"
    b"16384\tusertbs\t10\t\t\t/data/pg_tbs\n"
)


def test_parse_tablespaces_returns_list() -> None:
    result = parse_tablespaces(_TABLESPACES_TSV)
    assert result is not None
    assert len(result) == 3


def test_parse_tablespaces_default_empty_location() -> None:
    result = parse_tablespaces(_TABLESPACES_TSV)
    assert result is not None
    pg_default = next(r for r in result if r.spcname == "pg_default")
    assert isinstance(pg_default, Tablespace)
    assert pg_default.spclocation == ""


def test_parse_tablespaces_custom_location() -> None:
    result = parse_tablespaces(_TABLESPACES_TSV)
    assert result is not None
    usertbs = next(r for r in result if r.spcname == "usertbs")
    assert usertbs.spclocation == "/data/pg_tbs"


def test_parse_tablespaces_empty_returns_none() -> None:
    assert parse_tablespaces(b"") is None


def test_parse_tablespaces_header_only_returns_empty() -> None:
    result = parse_tablespaces(
        b"oid\tspcname\tspcowner\tspcacl\tspcoptions\tspclocation\n"
    )
    assert result == []


# ---------------------------------------------------------------
# parse_tablespace_sizes
# ---------------------------------------------------------------

_TABLESPACE_SIZES_TSV = (
    b"spcname\tsize\n"
    b"pg_default\t1190 MB\n"
    b"pg_global\t604 kB\n"
    b"usertbs\t2 GB\n"
)


def test_parse_tablespace_sizes_returns_list() -> None:
    result = parse_tablespace_sizes(_TABLESPACE_SIZES_TSV)
    assert result is not None
    assert len(result) == 3


def test_parse_tablespace_sizes_mb() -> None:
    result = parse_tablespace_sizes(_TABLESPACE_SIZES_TSV)
    assert result is not None
    pg_default = next(r for r in result if r.spcname == "pg_default")
    assert isinstance(pg_default, TablespaceSize)
    # 1190 MiB = 1190 * 1024 * 1024 bytes
    assert pg_default.size_bytes == 1190 * 1024 * 1024


def test_parse_tablespace_sizes_kb() -> None:
    result = parse_tablespace_sizes(_TABLESPACE_SIZES_TSV)
    assert result is not None
    pg_global = next(r for r in result if r.spcname == "pg_global")
    assert pg_global.size_bytes == 604 * 1024


def test_parse_tablespace_sizes_gb() -> None:
    result = parse_tablespace_sizes(_TABLESPACE_SIZES_TSV)
    assert result is not None
    usertbs = next(r for r in result if r.spcname == "usertbs")
    assert usertbs.size_bytes == 2 * 1024 * 1024 * 1024


def test_parse_tablespace_sizes_empty_returns_none() -> None:
    assert parse_tablespace_sizes(b"") is None


# ---------------------------------------------------------------
# parse_roles
# ---------------------------------------------------------------

_ROLES_TSV = (
    b"oid\trolname\trolsuper\trolreplication\trolcanlogin"
    b"\trolvaliduntil\n"
    b"10\tpostgres\ttrue\ttrue\ttrue\t\n"
    b"16384\tapp_user\tfalse\tfalse\ttrue\t\n"
    b"16385\trepl_user\tfalse\ttrue\ttrue\t2030-01-01 00:00:00+00\n"
    b"16386\tnosupergroup\tfalse\tfalse\tfalse\t\n"
)


def test_parse_roles_returns_list() -> None:
    result = parse_roles(_ROLES_TSV)
    assert result is not None
    assert len(result) == 4


def test_parse_roles_superuser_flag() -> None:
    result = parse_roles(_ROLES_TSV)
    assert result is not None
    pg = next(r for r in result if r.rolname == "postgres")
    assert isinstance(pg, PgRole)
    assert pg.rolsuper is True
    assert pg.rolreplication is True
    assert pg.rolcanlogin is True


def test_parse_roles_non_superuser() -> None:
    result = parse_roles(_ROLES_TSV)
    assert result is not None
    app = next(r for r in result if r.rolname == "app_user")
    assert app.rolsuper is False
    assert app.rolreplication is False


def test_parse_roles_replication_flag() -> None:
    result = parse_roles(_ROLES_TSV)
    assert result is not None
    repl = next(r for r in result if r.rolname == "repl_user")
    assert repl.rolreplication is True
    assert repl.rolvaliduntil == "2030-01-01 00:00:00+00"


def test_parse_roles_null_validuntil_empty() -> None:
    result = parse_roles(_ROLES_TSV)
    assert result is not None
    app = next(r for r in result if r.rolname == "app_user")
    assert app.rolvaliduntil == ""


def test_parse_roles_empty_returns_none() -> None:
    assert parse_roles(b"") is None


# ---------------------------------------------------------------
# parse_shmem_allocations
# ---------------------------------------------------------------

_SHMEM_TSV = (
    b"name\toff\tsize\tallocated_size\n"
    b"Buffer headers\t0\t3276800\t3276800\n"
    b"Buffer blocks\t3276800\t134217728\t134217728\n"
    b"XLOG\t\t1048576\t1048576\n"
)


def test_parse_shmem_allocations_returns_list() -> None:
    result = parse_shmem_allocations(_SHMEM_TSV)
    assert result is not None
    assert len(result) == 3


def test_parse_shmem_allocations_size_parsed() -> None:
    result = parse_shmem_allocations(_SHMEM_TSV)
    assert result is not None
    buf = next(r for r in result if r.name == "Buffer blocks")
    assert isinstance(buf, ShmemAllocation)
    assert buf.size == 134217728


def test_parse_shmem_allocations_empty_returns_none() -> None:
    assert parse_shmem_allocations(b"") is None


# ---------------------------------------------------------------
# parse_stat_progress
# ---------------------------------------------------------------

_STAT_PROGRESS_VACUUM_TSV = (
    b"pid\tdatid\tdatname\trelid\tphase\theap_blks_total"
    b"\theap_blks_scanned\theap_blks_vacuumed\n"
    b"12345\t16384\tmydb\t24601\tvacuuming heap\t10000"
    b"\t3000\t2000\n"
)

_STAT_PROGRESS_CREATE_INDEX_TSV = (
    b"pid\tdatid\tdatname\trelid\tphase\tblocks_done\tblocks_total\n"
    b"99999\t16384\tmydb\t24700\tbuilding index\t500\t1000\n"
)


def test_parse_stat_progress_vacuum_has_row() -> None:
    result = parse_stat_progress(_STAT_PROGRESS_VACUUM_TSV)
    assert result is not None
    assert len(result) == 1
    row = result[0]
    assert isinstance(row, ProgressRow)
    assert row.pid == 12345
    assert row.datname == "mydb"
    assert row.phase == "vacuuming heap"


def test_parse_stat_progress_blocks_from_vacuum() -> None:
    result = parse_stat_progress(_STAT_PROGRESS_VACUUM_TSV)
    assert result is not None
    row = result[0]
    # heap_blks_vacuumed maps to blocks_done, heap_blks_total to blocks_total
    assert row.blocks_done == 2000
    assert row.blocks_total == 10000


def test_parse_stat_progress_create_index() -> None:
    result = parse_stat_progress(_STAT_PROGRESS_CREATE_INDEX_TSV)
    assert result is not None
    row = result[0]
    assert row.pid == 99999
    assert row.blocks_done == 500
    assert row.blocks_total == 1000


def test_parse_stat_progress_header_only_returns_empty() -> None:
    result = parse_stat_progress(
        b"pid\tdatid\tdatname\trelid\tphase\n"
    )
    assert result == []


def test_parse_stat_progress_empty_returns_none() -> None:
    assert parse_stat_progress(b"") is None


def test_parse_stat_progress_no_blocks_columns() -> None:
    data = b"pid\tdatname\tphase\n12345\tmydb\tvacuuming\n"
    result = parse_stat_progress(data)
    assert result is not None
    assert len(result) == 1
    assert result[0].blocks_done is None
    assert result[0].blocks_total is None
