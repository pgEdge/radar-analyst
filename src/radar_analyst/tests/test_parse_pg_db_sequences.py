"""Tests for parse/pg_db_sequences.py."""

from radar_analyst.parse.pg_db_sequences import (
    SequenceRow,
    SequencesPerDb,
    parse_db_sequences,
)


_HEADER = (
    "schemaname\tsequencename\tdata_type\tlast_value\t"
    "max_value\tmin_value\tincrement_by\tcycle\tcache_size\n"
)


def _row(
    name: str = "s",
    *,
    schema: str = "public",
    last: str = "1",
    max_v: str = "9223372036854775807",
    min_v: str = "1",
    inc: str = "1",
) -> str:
    return (
        f"{schema}\t{name}\tbigint\t{last}\t{max_v}\t"
        f"{min_v}\t{inc}\tf\t1\n"
    )


def test_empty_returns_empty() -> None:
    assert parse_db_sequences(b"").rows == []


def test_missing_columns_returns_empty() -> None:
    assert parse_db_sequences(b"schemaname\nfoo\n").rows == []


def test_unbounded_bigint_returns_none_remaining() -> None:
    tsv = _HEADER + _row("ids", last="1000")
    row = parse_db_sequences(tsv.encode()).rows[0]
    assert row.is_unbounded is True
    assert row.remaining_percent is None


def test_capped_int_remaining_percent_computed() -> None:
    # int sequence with max=2147483647 used 25% of the way through.
    last = 536_870_912
    tsv = _HEADER + _row(
        "small_ids",
        last=str(last),
        max_v="2147483647",
        min_v="1",
    )
    row = parse_db_sequences(tsv.encode()).rows[0]
    assert row.is_unbounded is False
    assert row.remaining_percent is not None
    assert 70.0 < row.remaining_percent < 80.0


def test_remaining_percent_clamps_to_zero_on_overflow() -> None:
    tsv = _HEADER + _row(
        "exhausted",
        last="2200000000",
        max_v="2147483647",
        min_v="1",
    )
    row = parse_db_sequences(tsv.encode()).rows[0]
    assert row.remaining_percent == 0.0


def test_no_last_value_means_no_percent() -> None:
    tsv = _HEADER + _row(
        "fresh",
        last="",
        max_v="2147483647",
    )
    row = parse_db_sequences(tsv.encode()).rows[0]
    assert row.last_value is None
    assert row.remaining_percent is None


def test_returns_sequences_per_db_dataclass() -> None:
    tsv = _HEADER + _row("a") + _row("b")
    out = parse_db_sequences(tsv.encode())
    assert isinstance(out, SequencesPerDb)
    assert isinstance(out.rows[0], SequenceRow)
    assert len(out) == 2
    assert out.rows[0].fqname == "public.a"
