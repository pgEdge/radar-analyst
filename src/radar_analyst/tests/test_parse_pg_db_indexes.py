"""Tests for parse/pg_db_indexes.py."""

from radar_analyst.parse.pg_db_indexes import (
    IndexesPerDb,
    IndexRow,
    parse_db_indexes,
)


_HEADER = (
    "schemaname\ttablename\tindexname\tindexdef\tindrelid\t"
    "indexrelid\tindisunique\tindisprimary\tindisvalid\t"
    "indclass\tindkey\tindexprs\tindpred\tindex_size\t"
    "idx_scan\tidx_tup_read\tidx_tup_fetch\n"
)


def _row(
    schema: str = "public",
    table: str = "t",
    index: str = "t_pkey",
    *,
    relid: str = "16384",
    indclass: str = "10001",
    indkey: str = "1",
    indexprs: str = "",
    indpred: str = "",
    valid: str = "t",
    unique_flag: str = "t",
    size: int = 0,
    scan: int = 0,
) -> str:
    return (
        f"{schema}\t{table}\t{index}\t\t{relid}\t99\t"
        f"{unique_flag}\tt\t{valid}\t{indclass}\t{indkey}\t"
        f"{indexprs}\t{indpred}\t{size}\t{scan}\t0\t0\n"
    )


def test_parse_empty_returns_empty() -> None:
    assert parse_db_indexes(b"").rows == []


def test_parse_missing_columns_returns_empty() -> None:
    tsv = "schemaname\ttablename\nfoo\tbar\n"
    assert parse_db_indexes(tsv.encode()).rows == []


def test_parse_basic_row() -> None:
    tsv = _HEADER + _row(
        schema="public", table="users", index="users_pkey",
        scan=10000, size=4096,
    )
    out = parse_db_indexes(tsv.encode())
    assert isinstance(out, IndexesPerDb)
    assert len(out) == 1
    row = out.rows[0]
    assert isinstance(row, IndexRow)
    assert row.fqname == "public.users_pkey"
    assert row.idx_scan == 10000
    assert row.index_size == 4096
    assert row.indisvalid is True


def test_invalid_index_parsed() -> None:
    tsv = _HEADER + _row(index="broken", valid="f")
    row = parse_db_indexes(tsv.encode()).rows[0]
    assert row.indisvalid is False


def test_dedup_key_groups_semantic_duplicates() -> None:
    tsv = (
        _HEADER
        + _row(
            index="idx_a", relid="16400",
            indclass="10001", indkey="1",
        )
        + _row(
            index="idx_b", relid="16400",
            indclass="10001", indkey="1",
        )
        + _row(
            index="idx_c", relid="16400",
            indclass="10001", indkey="2",
        )
    )
    rows = {r.indexname: r for r in parse_db_indexes(tsv.encode()).rows}
    assert rows["idx_a"].dedup_key == rows["idx_b"].dedup_key
    assert rows["idx_a"].dedup_key != rows["idx_c"].dedup_key


def test_idx_scan_zero_for_unused_indexes() -> None:
    tsv = _HEADER + _row(index="dead", scan=0)
    row = parse_db_indexes(tsv.encode()).rows[0]
    assert row.idx_scan == 0
