"""Tests for parse/pg_stat_statements.py."""

from radar_analyst.parse.pg_stat_statements import (
    StatementRow,
    parse_stat_statements,
)


_HEADER = (
    "userid\tdbid\tquery\tcalls\ttotal_exec_time\t"
    "mean_exec_time\tmax_exec_time\trows\n"
)


def test_empty_input_returns_empty() -> None:
    assert parse_stat_statements(b"") == []


def test_parses_basic_row() -> None:
    tsv = (
        _HEADER
        + "10\t16400\tSELECT * FROM t\t1500\t"
        + "12345.678\t8.23\t125.5\t1500000\n"
    )
    out = parse_stat_statements(tsv.encode())
    assert len(out) == 1
    s = out[0]
    assert isinstance(s, StatementRow)
    assert s.calls == 1500
    assert s.mean_exec_time == 8.23
    assert s.max_exec_time == 125.5
    assert s.query == "SELECT * FROM t"


def test_silent_on_missing_columns() -> None:
    tsv = "userid\tquery\n10\tSELECT 1\n"
    out = parse_stat_statements(tsv.encode())
    # No required-column gate; missing fields default to 0.
    assert len(out) == 1
    assert out[0].calls == 0
    assert out[0].mean_exec_time == 0.0


def test_query_text_is_cut_to_1024_characters() -> None:
    query = "SELECT " + "1, " * 1000 + "1"
    tsv = _HEADER + f"10\t16400\t{query}\t1\t1.0\t1.0\t1.0\t1\n"
    out = parse_stat_statements(tsv.encode())
    assert out[0].query == query[:1024]
